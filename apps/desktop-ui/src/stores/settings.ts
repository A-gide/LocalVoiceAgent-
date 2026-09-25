import { defineStore } from 'pinia';
import { ref } from 'vue';
import {
  TauriBridge,
  type FullServicesStatus,
  type PublicAppSettings,
} from '@/bridge/tauri-bridge';
import { useRuntimeStore } from './runtime';

export const useSettingsStore = defineStore('settings', () => {
  const runtime = useRuntimeStore();
  const settings = ref<PublicAppSettings | null>(null);
  const services = ref<FullServicesStatus | null>(null);
  const autostart = ref<boolean>(false);
  const isLoading = ref<boolean>(false);
  const lastOpMessage = ref<string | null>(null);

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
      lastOpMessage.value = res.status === 'applied' ? 'Hub 模型列表已刷新' : 'Hub 刷新被拒绝';
    } catch (e: any) {
      lastOpMessage.value = `刷新失败: ${e?.toString()}`;
    }
  }

  async function bindHubModel(modelId: string, force = false) {
    try {
      const res = await TauriBridge.sendCoreCommand('hub.bind_model', {
        type: 'hub.bind_model',
        model_id: modelId,
        force,
      },
        { aggregate: 'hub_binding', revision: runtime.state.hub_binding_revision }
      );
      if (res.status === 'applied') {
          runtime.applyResult(res);
        lastOpMessage.value = `已绑定模型 ${modelId}`;
      } else {
        lastOpMessage.value = `绑定模型失败: ${res.error?.message || '未知错误'}`;
      }
    } catch (e: any) {
      lastOpMessage.value = `绑定异常: ${e?.toString()}`;
    }
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
    loadSettings,
    setSecret,
    clearSecret,
    toggleAutostart,
    refreshHubModels,
    bindHubModel,
    sleepBoundModel,
  };
});
