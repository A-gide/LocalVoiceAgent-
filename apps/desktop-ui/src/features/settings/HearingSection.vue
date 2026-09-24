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
        <label>ASR 引擎架构</label>
        <span>SenseVoice / sherpa-onnx (CPU 本地高速推理)</span>
      </div>
      <div class="card-row">
        <label>VAD (语音活动检测)</label>
        <span>已启用 (Silero VAD / 能量阈值双检)</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRuntimeStore } from '@/stores/runtime';
const runtime = useRuntimeStore();
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
.card-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.card-row label {
  color: #94a3b8;
}
</style>
