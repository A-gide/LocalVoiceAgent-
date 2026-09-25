import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type {
  CommandResult,
  EventEnvelope,
  Mode,
  PrivacyScope,
  RuntimeState,
} from '@/generated/lva-ipc';
import { TauriBridge } from '@/bridge/tauri-bridge';
import { reconcileSetMode } from './modeTransition.js';

/**
 * The wire always carries these fields: the Pydantic models give them
 * defaults, so `model_json_schema()` omits them from `required` and the
 * generated TypeScript marks them optional.  Core serializes them on every
 * snapshot, so treating them as present here matches the actual contract.
 */
type WireState = RuntimeState &
  Required<
    Pick<
      RuntimeState,
      | 'snapshot_version'
      | 'runtime_control_revision'
      | 'hub_binding_revision'
      | 'mode'
      | 'floor'
      | 'activity'
      | 'mic_capture'
      | 'managed_capture'
      | 'playback'
      | 'services'
      | 'providers'
      | 'privacy_scope'
    >
  >;

const INITIAL_STATE: WireState = {
  schema_version: '1.0',
  runtime_instance_id: '00000000-0000-0000-0000-000000000000',
  snapshot_version: 0,
  runtime_control_revision: 0,
  hub_binding_revision: 0,
  mode: 'standby',
  resume_mode: null,
  session_id: null,
  current_turn: null,
  floor: 'none',
  activity: 'idle',
  mic_capture: {
    active: false,
    device_name: null,
    frames_captured: 0,
    sample_rate: 16000,
  },
  managed_capture: {
    core_mic_stopped: true,
    managed_screenpipe_stopped: null,
    external_screenpipe_detected: false,
  },
  playback: {
    active: false,
    device_name: null,
    current_generation: 0,
    muted: false,
  },
  services: {},
  providers: {},
  hub_binding: null,
  privacy_scope: 'NOT_PAUSED',
};

export const useRuntimeStore = defineStore('runtime', () => {
  const state = ref<WireState>({ ...INITIAL_STATE });
  const lastSequence = ref<number>(0);
  const isSyncing = ref<boolean>(false);
  const lastError = ref<string | null>(null);

  // Computeds
  const currentMode = computed<Mode>(() => state.value.mode);
  const isLive = computed(() => state.value.mode === 'live');
  const isPassive = computed(() => state.value.mode === 'passive');
  const isStandby = computed(() => state.value.mode === 'standby');
  const isPrivacyPause = computed(() => state.value.mode === 'privacy_pause');

  const privacyScope = computed<PrivacyScope>(() => state.value.privacy_scope);
  const isPrivacyVerified = computed(
    () => state.value.privacy_scope === 'VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF'
  );

  const floor = computed(() => state.value.floor);
  const activity = computed(() => state.value.activity);
  const isMicActive = computed(() => state.value.mic_capture.active);
  const isPlaybackActive = computed(() => state.value.playback.active);
  const isPlaybackMuted = computed(() => Boolean(state.value.playback.muted));

  const boundModel = computed(() => state.value.hub_binding?.active_model_id || '未绑定');
  const hubStatus = computed(() => state.value.hub_binding?.status || 'unbound');

  // Actions
  function setMuted(muted: boolean) {
    // Output Mute must reach the Core: a local ref changes the icon and leaves
    // the speakers playing (PR-024 / plan L989).  The Core publishes the state,
    // so the assignment below is only the optimistic echo of the command.
    state.value.playback.muted = muted;
    TauriBridge.sendCoreCommand(
      'playback.set_muted',
      { type: 'playback.set_muted', muted },
    )
      .then((result) => {
        if (result.status !== 'applied') {
          // The Core refused (e.g. the device rejected it): do not keep showing a
          // mute that did not happen.
          state.value.playback.muted = !muted;
          lastError.value = result.error?.message || 'Output mute was refused';
        }
      })
      .catch((err) => {
        state.value.playback.muted = !muted;
        lastError.value = err?.toString() || 'Output mute failed';
      });
  }

  function mutePlayback() {
    setMuted(true);
  }

  async function fetchSnapshotState(): Promise<RuntimeState | null> {
    isSyncing.value = true;
    try {
      const result = await TauriBridge.sendCoreCommand('runtime.get_snapshot', {
        type: 'runtime.get_snapshot',
      });
      if (result.status === 'applied' && result.data) {
        // Core returns `data` flat (the serialized RuntimeState), not `data.state`.
        const snap = (result.data as RuntimeState as unknown) as WireState;
        if (snap) {
          state.value = snap;
          lastError.value = null;
          return snap;
        }
      }
      return null;
    } catch (e: any) {
      lastError.value = e?.toString() || 'Failed to fetch snapshot';
      return null;
    } finally {
      isSyncing.value = false;
    }
  }

  async function fetchSnapshot(): Promise<void> {
    await fetchSnapshotState();
  }

  /**
   * Adopt the revision vector Core returned with a command result. Without
   * this the next CAS command re-sends the revision it started from and is
   * rejected with STALE_REVISION.
   */
  function applyResult(result: CommandResult) {
    state.value.snapshot_version = result.snapshot_version;
    const revisions = (result.revisions ?? {}) as Record<string, number>;
    if (typeof revisions.runtime_control === 'number') {
      state.value.runtime_control_revision = revisions.runtime_control;
    }
    if (typeof revisions.hub_binding === 'number') {
      state.value.hub_binding_revision = revisions.hub_binding;
    }
  }

  async function setMode(targetMode: Mode) {
    const prevMode = state.value.mode;
    state.value.mode = targetMode; // optimistic update
    let result: CommandResult | null = null;
    let refreshed: RuntimeState | null = null;
    try {
      result = await TauriBridge.sendCoreCommand(
        'runtime.set_mode',
        {
          type: 'runtime.set_mode',
          mode: targetMode,
        },
        { aggregate: 'runtime_control', revision: state.value.runtime_control_revision }
      );

      if (result.status === 'rejected' && result.error?.code === 'STALE_REVISION') {
        // Read the authoritative snapshot *before* deciding, so a successful
        // recovery is not undone by the rollback below.
        refreshed = await fetchSnapshotState();
      }
    } catch (err: any) {
      const next = reconcileSetMode({
        state: state.value,
        prevMode,
        result: result ?? { status: 'rejected' },
        refreshed: null,
      });
      state.value.mode = next.mode as Mode;
      throw err;
    }

    const next = reconcileSetMode({ state: state.value, prevMode, result, refreshed });
    state.value.mode = next.mode as Mode;
    state.value.snapshot_version = next.snapshot_version;
    state.value.runtime_control_revision = next.runtime_control_revision;
    state.value.hub_binding_revision = next.hub_binding_revision;
    if (result.status !== 'applied') {
      throw new Error(result.error?.message || 'Set mode rejected');
    }
  }

  async function restoreMode() {
    try {
      const result = await TauriBridge.sendCoreCommand(
          'runtime.restore_mode',
          { type: 'runtime.restore_mode' },
          { aggregate: 'runtime_control', revision: state.value.runtime_control_revision }
        )
      if (result.status === 'applied') {
        applyResult(result);
      }
    } catch (err: any) {
      lastError.value = err?.toString() || 'Restore mode failed';
    }
  }

  function handleEvent(envelope: EventEnvelope) {
    // Gap check: Part 8.1
    if (lastSequence.value > 0 && envelope.sequence > lastSequence.value + 1) {
      console.warn(
        `[EventGap] Gap detected: expected ${lastSequence.value + 1}, got ${envelope.sequence}. Fetching snapshot.`
      );
      fetchSnapshot();
    }
    lastSequence.value = envelope.sequence;

    switch (envelope.payload.type) {
      case 'runtime.snapshot':
        state.value = envelope.payload.state as WireState;
        break;
      case 'mode.changed':
        state.value.mode = envelope.payload.new_mode;
        state.value.resume_mode = envelope.payload.resume_mode ?? null;
        break;
      case 'privacy.scope_changed':
        state.value.privacy_scope = envelope.payload.new_scope;
        break;
      case 'hub.binding_changed':
        state.value.hub_binding = envelope.payload.binding;
        break;
      case 'interrupt.committed':
        state.value.floor = envelope.payload.new_floor || 'user';
        state.value.playback.active = false;
        break;
      case 'audio.playback_started':
        state.value.playback.active = true;
        break;
      case 'audio.playback_silenced':
        state.value.playback.active = false;
        break;
      case 'turn.started':
        state.value.current_turn = envelope.payload.turn_id;
        state.value.activity = 'listening';
        break;
      case 'turn.completed':
      case 'turn.cancelled':
        state.value.current_turn = null;
        state.value.activity = 'idle';
        break;
      case 'service.state_changed': {
        const { service_name, new_state } = envelope.payload;
        if (state.value.services[service_name]) {
          state.value.services[service_name].state = new_state;
        }
        break;
      }
      case 'provider.state_changed': {
        const { provider_id, new_state } = envelope.payload;
        if (state.value.providers[provider_id]) {
          state.value.providers[provider_id].state = new_state;
        }
        break;
      }
    }
  }

  return {
    state,
    lastSequence,
    isSyncing,
    lastError,
    currentMode,
    isLive,
    isPassive,
    isStandby,
    isPrivacyPause,
    privacyScope,
    isPrivacyVerified,
    floor,
    activity,
    isMicActive,
    isPlaybackActive,
    isPlaybackMuted,
    setMuted,
    mutePlayback,
    boundModel,
    hubStatus,
    fetchSnapshot,
    setMode,
    restoreMode,
    applyResult,
    handleEvent,
  };
});
