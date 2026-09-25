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
        <button class="action-btn" :disabled="settingsStore.isRefreshingHub" @click="settingsStore.refreshHubModels">
          {{ settingsStore.isRefreshingHub ? '刷新中...' : '🔄 刷新 Hub 模型' }}
        </button>
        <button class="action-btn warn-btn" @click="settingsStore.sleepBoundModel">
          💤 休眠当前模型 (Sleep AI)
        </button>
      </div>
    </div>

    <!-- Hub Inventory: the models the Hub holds (PR-026 list) -->
    <div class="model-card">
      <div class="card-header">
        <strong>Hub 模型清单</strong>
        <span class="sub-hint">{{ settingsStore.hubModels.length }} 个可用模型</span>
      </div>

      <div v-if="settingsStore.hubModels.length === 0" class="empty-hint">
        尚未读取模型清单。点击上方「刷新 Hub 模型」从 Hub 获取。
      </div>

      <div v-for="m in settingsStore.hubModels" :key="m.model_id" class="model-row">
        <div class="row-main">
          <span class="model-name">{{ m.name }}</span>
          <span v-if="m.alias && m.alias !== m.name" class="model-alias">别名: {{ m.alias }}</span>
          <span v-if="m.size_bytes" class="model-size">{{ formatSize(m.size_bytes) }}</span>
        </div>
        <div class="row-tags">
          <!-- The bound marker comes from the *binding*, never from mere
               loaded membership: several models can be loaded at once and only
               one of them is LVA's current binding (plan 5.5). -->
          <span v-if="isBound(m.model_id)" class="tag tag-bound">当前绑定</span>
          <span v-if="isLoaded(m.model_id) && !isBound(m.model_id)" class="tag tag-loaded">已加载 (非当前绑定)</span>
        </div>
        <div class="row-actions">
          <button
            class="action-btn"
            :disabled="settingsStore.isRefreshingHub || isBound(m.model_id)"
            @click="settingsStore.bindHubModel(m.model_id, false)"
          >
            绑定
          </button>
        </div>
      </div>
    </div>

    <!-- Operation progress (plan L993: the UI shows operation progress) -->
    <div v-if="settingsStore.hubProgress !== null" class="progress-card">
      <div class="progress-label">操作进度: {{ settingsStore.hubProgress }}%</div>
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: settingsStore.hubProgress + '%' }"></div>
      </div>
    </div>

    <!-- Conflict: stopping a preexisting model needs explicit confirmation -->
    <div v-if="settingsStore.hubConflict" class="conflict-card">
      <div class="conflict-title">⚠️ 需要确认</div>
      <p class="conflict-body">
        当前已有一个非 LVA 加载的模型在运行。加载新模型不会停止它（两个模型会同时占用显存）。
        如需停止旧模型，请明确确认。
      </p>
      <div class="card-actions">
        <button class="action-btn" @click="confirmPreexistingStop">确认停止旧模型并绑定</button>
        <button class="action-btn warn-btn" @click="settingsStore.hubConflict = null">保留旧模型</button>
      </div>
    </div>

    <!-- Errors are visible and retryable -->
    <div v-if="settingsStore.hubError" class="error-card">
      <div class="error-text">{{ settingsStore.hubError }}</div>
      <button
        v-if="settingsStore.lastBindAttempt"
        class="action-btn"
        :disabled="settingsStore.isRefreshingHub"
        @click="settingsStore.retryBind"
      >
        🔁 重试
      </button>
    </div>

    <div v-if="settingsStore.lastOpMessage" class="op-message">
      {{ settingsStore.lastOpMessage }}
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
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { useRuntimeStore } from '@/stores/runtime';
import { useSettingsStore } from '@/stores/settings';

const runtime = useRuntimeStore();
const settingsStore = useSettingsStore();

const openaiKeyInput = ref('');

/** The bound model is the *binding*, not every loaded model (plan 5.5). */
function isBound(modelId: string): boolean {
  return runtime.state.hub_binding?.active_model_id === modelId;
}

/**
 * The loaded set is rendered separately from the binding so a second loaded
 * model is never mislabelled as the current one (PR-026 acceptance).
 * `null` means the Core could not read the loaded set -- shown as unknown
 * rather than as "nothing is loaded".
 */
function isLoaded(modelId: string): boolean {
  return (settingsStore.hubLoaded || []).includes(modelId);
}

function formatSize(bytes: number): string {
  const gb = bytes / 1024 / 1024 / 1024;
  return `${gb.toFixed(2)} GB`;
}

/** Answering the conflict means sending the explicit confirmation flag. */
async function confirmPreexistingStop() {
  const attempt = settingsStore.lastBindAttempt;
  if (!attempt) return;
  await settingsStore.bindHubModel(attempt.modelId, true);
}

// The Core publishes the conflict on the binding, so the UI mirrors it instead
// of keeping a second copy of the rule.
watch(
  () => runtime.state.hub_binding?.last_error,
  (err) => settingsStore.noteHubBinding(err),
  { immediate: true }
);

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
.action-btn:disabled {
  opacity: 0.5;
  cursor: default;
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
.empty-hint {
  font-size: 12px;
  color: #64748b;
  padding: 8px 0;
}
.model-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-top: 1px solid #334155;
}
.row-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: 2px;
}
.model-name {
  font-size: 13px;
  font-weight: 600;
}
.model-alias,
.model-size {
  font-size: 11px;
  color: #94a3b8;
}
.row-tags {
  display: flex;
  gap: 6px;
}
.tag {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
}
.tag-bound {
  background: #10b981;
  color: #fff;
}
.tag-loaded {
  background: #475569;
  color: #e2e8f0;
}
.progress-card,
.conflict-card,
.error-card {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.conflict-card {
  border-color: #f59e0b;
}
.error-card {
  border-color: #ef4444;
}
.conflict-title {
  font-size: 13px;
  font-weight: 600;
  color: #f59e0b;
}
.conflict-body {
  font-size: 12px;
  color: #cbd5e1;
  line-height: 1.5;
}
.error-text {
  font-size: 12px;
  color: #f87171;
}
.progress-label {
  font-size: 12px;
  color: #cbd5e1;
}
.progress-track {
  height: 6px;
  background: #0f172a;
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: #3b82f6;
  transition: width 0.2s ease;
}
</style>

