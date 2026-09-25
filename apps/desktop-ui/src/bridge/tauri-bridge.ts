/**
 * Tauri IPC bridge for LocalVoiceAgent Desktop UI.
 *
 * Implements Part 4.4 and Part 8.1:
 * - UI communicates only via Tauri invoke / events.
 * - WebView has NO access to Core port/token or Hub credentials.
 * - Handles optimistic command execution and event streaming.
 */
import type {
  Payload as CommandPayload,
  Precondition,
  CommandResult,
  EventEnvelope,
  RuntimeState,
} from '@/generated/lva-ipc';

export interface PublicAppSettings {
  /**
   * Mirrors the Rust `PublicAppSettings` returned by `get_public_settings`.
   *
   * The command is invoked by name, so TypeScript cannot check this shape
   * against the Rust struct.  An earlier version declared `has_openai_key` /
   * `has_screenpipe_key` / `autostart`, none of which exist on the wire, so
   * every secret read as "not configured" however many were set.  The parity
   * test `test_red_settings_dto_parity.py` keeps the two in step.
   *
   * Only booleans cross for secrets: the UI must never receive the value
   * (plan L993).  `autostart` is deliberately absent -- it comes from the
   * separate `get_autostart_status` command.
   */
  llm_mode: string;
  local_gguf_path: string;
  cloud_provider: string;
  cloud_base_url: string;
  cloud_api_key_configured: boolean;
  cloud_model: string;
  asr_provider: string;
  asr_base_url: string;
  asr_api_key_configured: boolean;
  asr_model: string;
  tts_provider: string;
  tts_base_url: string;
  tts_api_key_configured: boolean;
  tts_model: string;
  tts_voice: string;
  active_character: string;
  pet_dormancy_mode: boolean;
  idle_vram_release_mins: number;
  /** Settings aggregate revision, quoted as a CAS precondition (plan L397). */
  settings_revision: number;
}

export interface ServiceProcessInfo {
  is_running: boolean;
  pid: number | null;
}

/** Persisted window position and size, in logical coordinates (PR-031). */
export interface SavedWindowGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface FullServicesStatus {
  llama_server: ServiceProcessInfo;
  screenpipe: ServiceProcessInfo;
  vram_mb_estimated: number;
  is_switching_model: boolean;
}

// Check if Tauri is present
export function isTauriEnvironment(): boolean {
  return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
}

/// The live `lva://event` subscription, if any.  Module-level because the stream
/// belongs to the bridge, not to whichever component happened to subscribe first.
let eventSubscription: (() => void) | null = null;

async function invokeTauri<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (isTauriEnvironment()) {
    const { invoke } = await import('@tauri-apps/api/core');
    return invoke<T>(cmd, args);
  }
  return mockInvoke<T>(cmd, args);
}

// In-memory mock state for dev/testing when outside Tauri runtime
// The wire always carries these: the Pydantic models give them defaults, so
// the generated TypeScript marks them optional even though Core serializes
// them on every snapshot.
type MockState = RuntimeState &
  Required<Pick<RuntimeState, 'snapshot_version' | 'runtime_control_revision' | 'hub_binding_revision' | 'mic_capture' | 'playback'>>;

const mockState: MockState = {
  schema_version: '1.0',
  runtime_instance_id: '00000000-0000-0000-0000-000000000001',
  snapshot_version: 1,
  runtime_control_revision: 0,
  hub_binding_revision: 0,
  mode: 'standby',
  resume_mode: null,
  session_id: '11111111-1111-1111-1111-111111111111',
  current_turn: null,
  floor: 'none',
  activity: 'idle',
  mic_capture: {
    active: false,
    device_name: 'Default Microphone',
    frames_captured: 0,
    sample_rate: 16000,
  },
  managed_capture: {
    core_mic_stopped: true,
    managed_screenpipe_stopped: true,
    external_screenpipe_detected: false,
  },
  playback: {
    active: false,
    device_name: 'Default Speaker',
    current_generation: 0,
    muted: false,
  },
  services: {
    lva_core: {
      name: 'lva_core',
      state: 'healthy',
      ownership: 'spawned',
      pid: null,
      port: null,
      endpoint: null,
      last_error: null,
    },
    screenpipe: {
      name: 'screenpipe',
      state: 'healthy',
      ownership: 'adopted',
      pid: null,
      port: null,
      endpoint: null,
      last_error: null,
    },
    llama_hub: {
      name: 'llama_hub',
      state: 'healthy',
      ownership: 'external',
      pid: null,
      port: null,
      endpoint: null,
      last_error: null,
    },
  },
  providers: {
    asr: {
      provider_id: 'sensevoice',
      kind: 'asr',
      state: 'ready',
      current_model: 'SenseVoiceSmall',
      epoch: 1,
      last_error: null,
    },
    llm: {
      provider_id: 'hub_llm',
      kind: 'llm',
      state: 'ready',
      current_model: 'Spark-X2.5-4B-Q8',
      epoch: 1,
      last_error: null,
    },
    tts: {
      provider_id: 'sherpa_tts',
      kind: 'tts',
      state: 'ready',
      current_model: 'vits-melo-tts-zh',
      epoch: 1,
      last_error: null,
    },
  },
  hub_binding: {
    desired_model_id: 'Spark-X2.5-4B-Q8',
    active_model_id: 'Spark-X2.5-4B-Q8',
    provider_epoch: 1,
    load_origin: 'loaded_by_lva',
    status: 'ready',
    last_error: null,
  },
  privacy_scope: 'NOT_PAUSED',
};

async function mockInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  console.debug(`[MockTauri] invoke('${cmd}', ${JSON.stringify(args)})`);
  switch (cmd) {
    case 'send_core_command': {
      const envelope = args?.cmd as any;
      mockState.snapshot_version++;
      if (envelope?.type === 'runtime.set_mode') {
        const targetMode = envelope.payload?.mode;
        mockState.mode = targetMode;
        if (targetMode === 'live') {
          mockState.mic_capture.active = true;
          mockState.privacy_scope = 'NOT_PAUSED';
        } else if (targetMode === 'privacy_pause') {
          mockState.mic_capture.active = false;
          mockState.privacy_scope = 'VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF';
        } else {
          mockState.mic_capture.active = false;
          mockState.privacy_scope = 'NOT_PAUSED';
        }
      } else if (envelope?.type === 'runtime.restore_mode') {
        mockState.mode = mockState.resume_mode || 'standby';
      }
      return {
        command_id: envelope?.command_id || 'mock-cmd-id',
        status: 'applied',
        snapshot_version: mockState.snapshot_version,
        revisions: {
          runtime_control: mockState.runtime_control_revision,
          hub_binding: mockState.hub_binding_revision,
        },
        // Core returns `data` flat (the serialized RuntimeState), not `data.state`.
        data: mockState,
      } as T;
    }
    case 'get_public_settings':
      return {
        llm_mode: 'local',
        local_gguf_path: 'C:\\Models\\Spark-X2.5-4B-Q8.gguf',
        cloud_provider: 'openai',
        cloud_base_url: '',
        cloud_api_key_configured: false,
        cloud_model: 'gpt-4o-mini',
        asr_provider: 'sensevoice',
        asr_base_url: '',
        asr_api_key_configured: false,
        asr_model: 'sensevoice-small',
        tts_provider: 'melotts',
        tts_base_url: '',
        tts_api_key_configured: false,
        tts_model: 'melotts-zh-en',
        tts_voice: 'default',
        active_character: 'haru',
        pet_dormancy_mode: true,
        idle_vram_release_mins: 15,
        settings_revision: 0,
      } as T;
    case 'get_services_status':
      return {
        llama_server: { is_running: true, pid: 1234 },
        screenpipe: { is_running: true, pid: 9012 },
        vram_mb_estimated: 4900,
        is_switching_model: false,
      } as T;
    case 'get_autostart_status':
      return true as T;
    case 'set_autostart_status':
      return Boolean(args?.enabled) as T;
    default:
      return {} as T;
  }
}

export const TauriBridge = {
  async sendCoreCommand(
    type: string,
    payload: CommandPayload,
    precondition?: Precondition
  ): Promise<CommandResult> {
    const envelope = {
      schema_version: '1.0',
      command_id: typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : 'cmd-' + Date.now(),
      issued_at: new Date().toISOString(),
      type,
      payload,
      precondition: precondition ?? null,
    };
    return invokeTauri<CommandResult>('send_core_command', { cmd: envelope });
  },

  async getPublicSettings(): Promise<PublicAppSettings> {
    return invokeTauri<PublicAppSettings>('get_public_settings');
  },

  async setSecret(
    secretType: string,
    secretValue: string,
    secretRevision: number | null = null,
  ): Promise<void> {
    return invokeTauri<void>('set_secret', {
      secret_type: secretType,
      secret_value: secretValue,
      // Plan L463: a secret write carries the settings revision so a concurrent
      // edit is refused with STALE_REVISION instead of being silently clobbered.
      // Null means "this caller has not read the DTO yet", which the Rust side
      // accepts as the documented first-write case.
      settings_revision: secretRevision,
    });
  },

  async clearSecret(secretType: string, secretRevision: number | null = null): Promise<void> {
    return invokeTauri<void>('clear_secret', {
      secret_type: secretType,
      settings_revision: secretRevision,
    });
  },

  async getServicesStatus(): Promise<FullServicesStatus> {
    return invokeTauri<FullServicesStatus>('get_services_status');
  },

  async togglePet(): Promise<void> {
    return invokeTauri<void>('toggle_pet');
  },

  async openSettings(): Promise<void> {
    return invokeTauri<void>('open_settings');
  },

  async openChat(): Promise<void> {
    return invokeTauri<void>('open_chat');
  },

  async openMemory(): Promise<void> {
    return invokeTauri<void>('open_memory');
  },

  async getAutostartStatus(): Promise<boolean> {
    return invokeTauri<boolean>('get_autostart_status');
  },

  async setAutostartStatus(enabled: boolean): Promise<boolean> {
    return invokeTauri<boolean>('set_autostart_status', { enabled });
  },

  /** Saved pet-window geometry, or null when nothing usable was stored (PR-031). */
  async getWindowGeometry(): Promise<SavedWindowGeometry | null> {
    return invokeTauri<SavedWindowGeometry | null>('get_window_geometry');
  },

  async setWindowGeometry(geometry: SavedWindowGeometry): Promise<void> {
    return invokeTauri<void>('set_window_geometry', { ...geometry });
  },

  /** Forget the saved geometry, so Reset Position survives a restart. */
  async clearWindowGeometry(): Promise<void> {
    return invokeTauri<void>('clear_window_geometry');
  },

  async listenEvent(callback: (event: EventEnvelope) => void): Promise<() => void> {
    if (isTauriEnvironment()) {
      const { listen } = await import('@tauri-apps/api/event');
      const unlisten = await listen<EventEnvelope>('lva://event', (e) => {
        callback(e.payload);
      });
      return unlisten;
    }
    // Mock event listener
    return () => {};
  },

  /**
   * Subscribe to Core events, replacing any previous subscription (S-UI-01 §1.7).
   *
   * `listenEvent` is a one-shot subscription: a WebView that reloads (a dev-server
   * refresh, a renderer crash) loses it silently, and the UI keeps rendering stale
   * state with no error to notice.  This is the idempotent form -- calling it again
   * releases the old listener first, so a reload re-establishes the stream without
   * ever running two listeners that would apply each event twice.
   *
   * Returns an unlisten for the caller that owns the lifecycle.
   */
  async ensureEventSubscription(
    callback: (event: EventEnvelope) => void,
  ): Promise<() => void> {
    const previous = eventSubscription;
    if (previous) {
      try {
        previous();
      } catch (e) {
        console.warn('Failed to release the previous event subscription', e);
      }
      eventSubscription = null;
    }
    const unlisten = await TauriBridge.listenEvent(callback);
    eventSubscription = unlisten;
    return () => {
      if (eventSubscription === unlisten) eventSubscription = null;
      unlisten();
    };
  },
};
