<template>
  <div class="settings-section">
    <h3>对话模型 (Conversation Model)</h3>
    <p class="section-desc">
      通过 llama.cpp-hub 统一管理模型运行时。LVA 不自行扫描 GGUF 或启动裸进程。
    </p>

    <!-- Hub Connection Status Card -->
    <div class="model-card">
      <div class="card-header">
        <strong>Hub 连接状态</strong>
        <span class="badge" :class="runtime.hubStatus === 'ready' ? 'badge-ready' : 'badge-warn'">
          {{ runtime.hubStatus === 'ready' ? '正常连接 (Loopback)' : runtime.hubStatus }}
        </span>
      </div>
      <div class="card-body">
        <p>当前绑定模型: <strong>{{ runtime.boundModel }}</strong></p>
        <p class="sub-hint">运行时权威: llama.cpp-hub (外部/接管模式)</p>
      </div>
      <div class="card-actions">
        <button class="action-btn" @click="settingsStore.refreshHubModels">
          🔄 刷新 Hub 模型
        </button>
        <button class="action-btn warn-btn" @click="settingsStore.sleepBoundModel">
          💤 休眠当前模型 (Sleep AI)
        </button>
      </div>
    </div>

    <!-- Fallback / Remote Provider Keys (Write-only secrets) -->
    <div class="model-card">
      <div class="card-header">
        <strong>备用云端推理接口 (可选)</strong>
      </div>
      <div class="card-body">
        <p class="sub-hint">当本地 Hub 不可用时作为降级备选。密钥采用单向写入保护，绝不回显到界面。</p>
        <div class="secret-input-row">
          <input
            v-model="openaiKeyInput"
            type="password"
            placeholder="输入 OpenAI 格式 API Key (sk-...)"
            class="secret-input"
          />
          <button class="action-btn" @click="saveOpenAIKey">保存密钥</button>
          <button class="action-btn clear-btn" @click="clearOpenAIKey">清除</button>
        </div>
        <div class="secret-status">
          状态:
          <span :class="settingsStore.settings?.cloud_api_key_configured ? 'text-green' : 'text-gray'">
            {{ settingsStore.settings?.cloud_api_key_configured ? '● 已配置 (写入保护中)' : '○ 未配置' }}
          </span>
        </div>
      </div>
    </div>

    <div v-if="settingsStore.lastOpMessage" class="op-message">
      {{ settingsStore.lastOpMessage }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRuntimeStore } from '@/stores/runtime';
import { useSettingsStore } from '@/stores/settings';

const runtime = useRuntimeStore();
const settingsStore = useSettingsStore();

const openaiKeyInput = ref('');

async function saveOpenAIKey() {
  if (!openaiKeyInput.value) return;
  await settingsStore.setSecret('openai_api_key', openaiKeyInput.value);
  openaiKeyInput.value = '';
}

async function clearOpenAIKey() {
  await settingsStore.clearSecret('openai_api_key');
}
</script>

<style scoped>
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.section-desc {
  font-size: 13px;
  color: #94a3b8;
}
.model-card {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.badge {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
}
.badge-ready {
  background: #10b981;
  color: #fff;
}
.badge-warn {
  background: #f59e0b;
  color: #fff;
}
.sub-hint {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
}
.card-actions {
  display: flex;
  gap: 8px;
}
.action-btn {
  background: #3b82f6;
  border: none;
  color: #fff;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}
.warn-btn {
  background: #475569;
}
.clear-btn {
  background: rgba(239, 68, 68, 0.2);
  border: 1px solid #ef4444;
  color: #f87171;
}
.secret-input-row {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.secret-input {
  flex: 1;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 6px;
  padding: 6px 10px;
  color: #fff;
  font-size: 13px;
}
.secret-status {
  font-size: 12px;
  margin-top: 6px;
}
.text-green {
  color: #10b981;
}
.text-gray {
  color: #94a3b8;
}
.op-message {
  font-size: 12px;
  color: #38bdf8;
}
</style>
