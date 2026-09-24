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
  local_gguf_path: string;
  autostart: boolean;
  pet_dormancy_mode: boolean;
  idle_vram_release_mins: number;
  has_openai_key: boolean;
  has_screenpipe_key: boolean;
}

export interface ServiceProcessInfo {
  is_running: boolean;
  pid: number | null;
}

export interface FullServicesStatus {
  llama_server: ServiceProcessInfo;
  open_llm_vtuber: ServiceProcessInfo;
  screenpipe: ServiceProcessInfo;
  vram_mb_estimated: number;
  is_switching_model: boolean;
}

// Check if Tauri is present
export function isTauriEnvironment(): boolean {
  return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
}

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
        local_gguf_path: 'C:\\Models\\Spark-X2.5-4B-Q8.gguf',
        autostart: true,
        pet_dormancy_mode: true,
        idle_vram_release_mins: 15,
        has_openai_key: false,
        has_screenpipe_key: false,
      } as T;
    case 'get_services_status':
      return {
        llama_server: { is_running: true, pid: 1234 },
        open_llm_vtuber: { is_running: true, pid: 5678 },
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

  async setSecret(secretType: string, secretValue: string): Promise<void> {
    return invokeTauri<void>('set_secret', {
      secret_type: secretType,
      secret_value: secretValue,
    });
  },

  async clearSecret(secretType: string): Promise<void> {
    return invokeTauri<void>('clear_secret', { secret_type: secretType });
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
};
