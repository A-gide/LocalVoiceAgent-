<template>
  <div class="settings-section">
    <h3>发音与语音合成 (Speech & TTS)</h3>

    <div class="card">
      <div class="card-row">
        <label>TTS 引擎架构</label>
        <span>sherpa-onnx / MeloTTS (中文流式合成)</span>
      </div>
      <div class="card-row">
        <label>当前输出状态</label>
        <span>{{ runtime.isPlaybackActive ? '正在播放音频...' : '静音/空闲' }}</span>
      </div>
      <div class="card-row">
        <label>打断响应级别 (Barge-in)</label>
        <span>硬件低延迟优先 (P95 &lt; 20ms)</span>
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
