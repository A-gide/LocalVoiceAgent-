<template>
  <div class="settings-section">
    <h3>听觉与语音识别 (Hearing & ASR)</h3>

    <div class="card">
      <div class="card-row">
        <label>当前音频输入设备</label>
        <span>{{ runtime.state.mic_capture.device_name || '默认系统麦克风' }}</span>
      </div>
      <div class="card-row">
        <label>采样率</label>
        <span>{{ runtime.state.mic_capture.sample_rate }} Hz</span>
      </div>
      <div class="card-row">
        <label>VAD (语音活动检测)</label>
        <span>已启用 (Silero VAD / 能量阈值双检)</span>
      </div>
    </div>

    <!-- Microphone test: a value display cannot tell the user whether the mic
         actually reaches the Core, so the test is an explicit action. -->
    <div class="card">
      <div class="card-header">
        <strong>麦克风测试</strong>
      </div>
      <p class="hint">
        进入 Live 模式后对着麦克风说话，下方会显示 Core 是否真的收到了音频帧。
      </p>
      <div class="card-row">
        <label>采集状态</label>
        <span :class="runtime.isMicActive ? 'text-green' : 'text-gray'">
          {{ runtime.isMicActive ? '● 正在采集 (已收到音频帧)' : '○ 未采集' }}
        </span>
      </div>
      <div class="card-row">
        <label>已采集帧数</label>
        <span>{{ runtime.state.mic_capture.frames_captured }}</span>
      </div>
      <div class="card-actions">
        <button class="action-btn" @click="toggleMicTest">
          {{ runtime.isMicActive ? '⏹ 结束测试' : '🎤 开始测试 (进入 Live)' }}
        </button>
      </div>
    </div>

    <!-- Capability-driven engine display: only what the Core actually reports
         is rendered (L1408: 不支持能力不显示). -->
    <div class="card">
      <div class="card-header">
        <strong>识别引擎能力</strong>
      </div>
      <div v-if="asrProviders.length === 0" class="hint">
        Core 尚未报告 ASR provider 能力，因此不显示引擎参数。
      </div>
      <div v-for="p in asrProviders" :key="p.provider_id" class="card-row">
        <label>{{ p.provider_id }}</label>
        <span :class="p.state === 'ready' ? 'text-green' : 'text-gray'">
          {{ p.state }}<template v-if="p.current_model"> · {{ p.current_model }}</template>
        </span>
      </div>
    </div>

    <!-- Advanced: collapsed by default (L1404 advanced collapse). -->
    <details class="card advanced">
      <summary>高级设置 (advanced)</summary>
      <p class="hint">
        ASR 模型、语言与领域由 Core 的 provider 配置决定；此处只读展示，避免与 Core 的权威配置漂移。
      </p>
      <div class="card-row">
        <label>语言</label>
        <span>{{ asrLanguage }}</span>
      </div>
      <div class="card-row">
        <label>领域</label>
        <span>{{ asrDomain }}</span>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRuntimeStore } from '@/stores/runtime';

const runtime = useRuntimeStore();

/**
 * Capability-driven: the section renders the ASR providers the Core reports and
 * nothing else, so an engine this build does not support cannot be offered.
 */
const asrProviders = computed(() =>
  Object.values(runtime.state.providers || {}).filter((p: any) => p.kind === 'asr')
);

const asrLanguage = computed(() => {
  const p = asrProviders.value[0] as any;
  return p?.language || 'zh (中文)';
});

const asrDomain = computed(() => {
  const p = asrProviders.value[0] as any;
  return p?.domain || '通用 (general)';
});

/**
 * The microphone test drives the real capture path rather than a local flag:
 * entering Live is what starts Core capture (I22 -- no side path).
 */
async function toggleMicTest() {
  await runtime.setMode(runtime.isMicActive ? 'standby' : 'live');
}
</script>

<style scoped>
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.card {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.card-row label {
  color: #94a3b8;
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
.hint {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}
.text-green {
  color: #10b981;
}
.text-gray {
  color: #94a3b8;
}
.advanced summary {
  cursor: pointer;
  font-weight: 600;
  font-size: 13px;
}
</style>

