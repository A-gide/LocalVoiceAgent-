<template>
  <div class="services-view">
    <div class="view-header">
      <h2>🖥️ 服务组件状态</h2>
      <p class="subtitle">实时监控本地服务组件运行健康度</p>
    </div>

    <div class="services-list">
      <div
        v-for="(svc, name) in runtime.state.services"
        :key="name"
        class="service-card"
        :class="'card-' + svc.state"
      >
        <div class="card-top">
          <div class="service-title">
            <span class="service-icon">{{ getServiceIcon(String(name)) }}</span>
            <span class="service-name">{{ formatServiceName(String(name)) }}</span>
          </div>
          <span class="status-pill" :class="'pill-' + svc.state">
            {{ formatState(svc.state ?? 'unknown') }}
          </span>
        </div>

        <div class="card-desc">
          {{ getServiceDesc(String(name)) }}
        </div>

        <div v-if="svc.last_error" class="error-msg">
          错误: {{ svc.last_error }}
        </div>

        <div class="card-bottom">
          <button
            class="retry-btn"
            :disabled="retryingService === name"
            @click="handleRetry(String(name))"
          >
            {{ retryingService === name ? '正在重试...' : '🔄 重启 / 重试' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRuntimeStore } from '@/stores/runtime';
import { TauriBridge } from '@/bridge/tauri-bridge';

const runtime = useRuntimeStore();
const retryingService = ref<string | null>(null);

function getServiceIcon(name: string): string {
  switch (name) {
    case 'lva_core':
      return '🧠';
    case 'screenpipe':
      return '📹';
    case 'llama_hub':
      return '🤖';
    default:
      return '⚙️';
  }
}

function formatServiceName(name: string): string {
  switch (name) {
    case 'lva_core':
      return 'LVA 核心调度器 (Core)';
    case 'screenpipe':
      return '被动记忆采集源 (Screenpipe)';
    case 'llama_hub':
      return '本地模型运行时 (llama.cpp-hub)';
    default:
      return name;
  }
}

function getServiceDesc(name: string): string {
  switch (name) {
    case 'lva_core':
      return '负责语音对话、VAD/ASR/TTS 调度与中断管理的唯一会话权威。';
    case 'screenpipe':
      return '提供屏幕与系统音频的被动记忆捕获源。';
    case 'llama_hub':
      return '提供统一的 GGUF 模型加载与高速推理服务。';
    default:
      return '系统后台辅助服务。';
  }
}

function formatState(state: string): string {
  switch (state) {
    case 'healthy':
      return '运行正常';
    case 'starting':
      return '正在启动';
    case 'degraded':
      return '降级运行';
    case 'failed':
      return '异常失败';
    case 'stopped':
      return '已停止';
    default:
      return state;
  }
}

async function handleRetry(serviceName: string) {
  retryingService.value = serviceName;
  try {
    await TauriBridge.sendCoreCommand('service.retry', {
      type: 'service.retry',
      service_name: serviceName,
    });
  } catch (e) {
    console.error('Failed to retry service', e);
  } finally {
    retryingService.value = null;
  }
}
</script>

<style scoped>
.services-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  background: #0b0f19;
  color: #f1f5f9;
  padding: 20px;
  overflow-y: auto;
}

.view-header h2 {
  font-size: 18px;
  margin-bottom: 4px;
}

.subtitle {
  font-size: 13px;
  color: #94a3b8;
  margin-bottom: 16px;
}

.services-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.service-card {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.service-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 14px;
}

.status-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
}

.pill-healthy {
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
}

.pill-starting {
  background: rgba(56, 189, 248, 0.2);
  color: #38bdf8;
}

.pill-degraded {
  background: rgba(245, 158, 11, 0.2);
  color: #f59e0b;
}

.pill-failed, .pill-stopped {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

.card-desc {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.4;
}

.error-msg {
  font-size: 12px;
  color: #f87171;
  background: rgba(239, 68, 68, 0.1);
  padding: 6px 10px;
  border-radius: 4px;
}

.card-bottom {
  display: flex;
  justify-content: flex-end;
}

.retry-btn {
  background: #334155;
  border: 1px solid #475569;
  color: #e2e8f0;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.retry-btn:hover {
  background: #475569;
}
</style>
