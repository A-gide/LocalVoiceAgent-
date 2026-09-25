import { defineStore } from 'pinia';
import { ref } from 'vue';
import {
  TauriBridge,
  type FullServicesStatus,
  type PublicAppSettings,
} from '@/bridge/tauri-bridge';
import { useRuntimeStore } from './runtime';

/**
 * One Hub inventory entry as the Core projects it (PR-026).
 *
 * Deliberately narrow: the Hub launch profile (ngl/context/mmproj/extraParams)
 * is not part of this shape, so the WebView never receives a value the plan
 * says must not be shown (L993 / PR-026 acceptance).
 */
export interface HubModelEntry {
  model_id: string;
  name: string;
  alias?: string;
  size_bytes?: number;
  supports_vision?: boolean;
}

export const useSettingsStore = defineStore('settings', () => {
  const runtime = useRuntimeStore();
  const settings = ref<PublicAppSettings | null>(null);
  const services = ref<FullServicesStatus | null>(null);
  const autostart = ref<boolean>(false);
  const isLoading = ref<boolean>(false);
  const lastOpMessage = ref<string | null>(null);

  /**
   * Hub inventory as the Core projects it (PR-026).  Only identity, size and
   * the alias cross the wire: the Hub launch profile (ngl/context/mmproj) is
   * deliberately absent, so the UI cannot render a parameter it must not show
   * and cannot offer to change one LVA is forbidden to guess (plan L593).
   */
  const hubModels = ref<HubModelEntry[]>([]);
  /** Model ids the Hub currently has loaded; null means "could not be read". */
  const hubLoaded = ref<string[] | null>(null);
  const isRefreshingHub = ref<boolean>(false);
  const hubProgress = ref<number | null>(null);
  /** Set when a bind came back needing confirmation to stop a preexisting model. */
  const hubConflict = ref<string | null>(null);
  const hubError = ref<string | null>(null);
  /** The last bind that failed, so the retry button re-issues exactly that one. */
  const lastBindAttempt = ref<{ modelId: string; force: boolean } | null>(null);

  async function loadSettings() {
    isLoading.value = true;
    try {
      settings.value = await TauriBridge.getPublicSettings();
      services.value = await TauriBridge.getServicesStatus();
      autostart.value = await TauriBridge.getAutostartStatus();
    } catch (e) {
      console.error('Failed to load settings', e);
    } finally {
      isLoading.value = false;
    }
  }

  async function setSecret(type: string, value: string) {
    if (!value.trim()) return;
    // Quote the revision this UI last saw so a concurrent edit is refused rather
    // than overwritten (plan L463).  `undefined` would be a missing argument, so a
    // not-yet-read revision is sent as null -- the documented first-write case.
    await TauriBridge.setSecret(type, value.trim(), settings.value?.settings_revision ?? null);
    await loadSettings();
    lastOpMessage.value = `已安全更新 ${type} 密钥 (写入保护)`;
  }

  async function clearSecret(type: string) {
    await TauriBridge.clearSecret(type, settings.value?.settings_revision ?? null);
    await loadSettings();
    lastOpMessage.value = `已清除 ${type} 密钥`;
  }

  async function toggleAutostart(enabled: boolean) {
    autostart.value = await TauriBridge.setAutostartStatus(enabled);
  }

  async function refreshHubModels() {
    try {
      const res = await TauriBridge.sendCoreCommand('hub.refresh', {
        type: 'hub.refresh',
      });
      // `hub.refresh` answers `accepted` (the read happened), not `applied`;
      // testing for `applied` reported every successful refresh as refused.
      if (res.status === 'accepted' || res.status === 'applied') {
        const data = (res.data || {}) as { models?: HubModelEntry[]; loaded?: string[] | null };
        hubModels.value = data.models || [];
        hubLoaded.value = data.loaded ?? null;
        hubError.value = null;
        lastOpMessage.value = `Hub 模型列表已刷新 (${hubModels.value.length} 个)`;
      } else {
        hubError.value = res.error?.message || 'Hub 刷新被拒绝';
        lastOpMessage.value = `Hub 刷新被拒绝: ${hubError.value}`;
      }
    } catch (e: any) {
      hubError.value = e?.toString() || '刷新失败';
      lastOpMessage.value = `刷新失败: ${e?.toString()}`;
    }
  }

  async function bindHubModel(modelId: string, force = false) {
    isRefreshingHub.value = true;
    hubProgress.value = 0;
    hubConflict.value = null;
    hubError.value = null;
    lastBindAttempt.value = { modelId, force };
    try {
      const res = await TauriBridge.sendCoreCommand('hub.bind_model', {
        type: 'hub.bind_model',
        model_id: modelId,
        force,
      },
        { aggregate: 'hub_binding', revision: runtime.state.hub_binding_revision }
      );
      if (res.status === 'applied' || res.status === 'accepted') {
          runtime.applyResult(res);
        lastOpMessage.value = `已绑定模型 ${modelId}`;
      } else {
        const code = res.error?.code || '';
        const message = res.error?.message || '未知错误';
        if (code === 'PROFILE_REQUIRED') {
          // Plan L593: LVA must not invent -ngl/-c/mmproj, so the user is sent
          // to the Hub to define the launch profile instead.
          hubError.value = `该模型在 Hub 中缺少启动配置 (PROFILE_REQUIRED)。请在 Hub 的模型配置中保存 profile 后重试。`;
        } else {
          hubError.value = message;
        }
        lastOpMessage.value = `绑定模型失败: ${hubError.value}`;
      }
    } catch (e: any) {
      hubError.value = e?.toString() || '绑定异常';
      lastOpMessage.value = `绑定异常: ${e?.toString()}`;
    } finally {
      isRefreshingHub.value = false;
      hubProgress.value = null;
    }
  }

  /**
   * Record the conflict the Core reported on the binding (plan 5.5).
   *
   * The conflict is not a failure -- the load proceeds and the old model stays
   * resident -- but stopping that old model requires the user's explicit
   * confirmation, which is what `force` carries.  The Core publishes the code on
   * `hub_binding.last_error`, so it is read from the state rather than invented.
   */
  function noteHubBinding(lastError: string | null | undefined) {
    if (lastError && lastError.includes('MODEL_CONFLICT_REQUIRES_CONFIRMATION')) {
      hubConflict.value = lastError;
    }
  }

  /** Re-issue the last bind that failed, so the retry button is honest. */
  async function retryBind() {
    const attempt = lastBindAttempt.value;
    if (!attempt) return;
    await bindHubModel(attempt.modelId, attempt.force);
  }

  async function sleepBoundModel() {
    try {
      const res = await TauriBridge.sendCoreCommand('hub.sleep_bound_model', {
        type: 'hub.sleep_bound_model',
      },
        { aggregate: 'hub_binding', revision: runtime.state.hub_binding_revision }
      );
      if (res.status === 'applied') {
        runtime.applyResult(res);
      }
      lastOpMessage.value = res.status === 'applied' ? '模型已进入休眠' : '模型休眠请求被拒绝';
    } catch (e: any) {
      lastOpMessage.value = `休眠异常: ${e?.toString()}`;
    }
  }

  return {
    settings,
    services,
    autostart,
    isLoading,
    lastOpMessage,
    hubModels,
    hubLoaded,
    isRefreshingHub,
    hubProgress,
    hubConflict,
    hubError,
    lastBindAttempt,
    loadSettings,
    setSecret,
    clearSecret,
    toggleAutostart,
    refreshHubModels,
    bindHubModel,
    noteHubBinding,
    retryBind,
    sleepBoundModel,
  };
});
