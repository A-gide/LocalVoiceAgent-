<template>
  <div class="settings-section">
    <h3>发音与语音合成 (Speech & TTS)</h3>

    <div class="card">
      <div class="card-row">
        <label>当前输出状态</label>
        <span :class="runtime.isPlaybackActive ? 'text-green' : 'text-gray'">
          {{ runtime.isPlaybackActive ? '● 正在播放音频' : '○ 静音/空闲' }}
        </span>
      </div>
      <div class="card-row">
        <label>输出静音 (Output Mute)</label>
        <span>{{ runtime.isPlaybackMuted ? '已静音 (麦克风与录制不受影响)' : '未静音' }}</span>
      </div>
      <div class="card-row">
        <label>打断响应级别 (Barge-in)</label>
        <span>硬件低延迟优先 (P95 &lt; 20ms)</span>
      </div>
    </div>

    <!-- Voice preview with an explicit cancel: a preview that cannot be
         stopped is the acceptance failure L1408 names. -->
    <div class="card">
      <div class="card-header">
        <strong>试听 (Voice preview)</strong>
      </div>
      <p class="hint">
        试听通过 Core 的真实播放路径发声，因此「停止试听」会真正让扬声器安静。
      </p>
      <div class="card-actions">
        <button class="action-btn" :disabled="isPreviewing" @click="startPreview">
          ▶️ 试听当前音色
        </button>
        <button class="action-btn warn-btn" :disabled="!isPreviewing" @click="cancelPreview">
          ⏹ 取消试听
        </button>
      </div>
      <div v-if="previewMessage" class="hint">{{ previewMessage }}</div>
    </div>

    <!-- Capability-driven engine list (L1408: 不支持能力不显示). -->
    <div class="card">
      <div class="card-header">
        <strong>合成引擎能力</strong>
      </div>
      <div v-if="ttsProviders.length === 0" class="hint">
        Core 尚未报告 TTS provider 能力，因此不显示引擎参数。
      </div>
      <div v-for="p in ttsProviders" :key="p.provider_id" class="card-row">
        <label>{{ p.provider_id }}</label>
        <span :class="p.state === 'ready' ? 'text-green' : 'text-gray'">
          {{ p.state }}<template v-if="p.current_model"> · {{ p.current_model }}</template>
        </span>
      </div>
    </div>

    <details class="card advanced">
      <summary>高级设置 (advanced)</summary>
      <p class="hint">
        音色、采样率与流式参数由 Core 的 TTS provider 配置决定；此处只读展示，不写入，避免改变默认 TTS engine (L1408)。
      </p>
      <div class="card-row">
        <label>当前音色</label>
        <span>{{ currentVoice }}</span>
      </div>
      <div class="card-row">
        <label>采样率</label>
        <span>44100 Hz (zh_en 原生)</span>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRuntimeStore } from '@/stores/runtime';

const runtime = useRuntimeStore();
const isPreviewing = ref(false);
const previewMessage = ref<string | null>(null);

const ttsProviders = computed(() =>
  Object.values(runtime.state.providers || {}).filter((p: any) => p.kind === 'tts')
);

const currentVoice = computed(() => {
  const p = ttsProviders.value[0] as any;
  return p?.current_model || 'MeloTTS (zh_en)';
});

/**
 * The preview goes through the Core turn path so that what the user hears is
 * what the assistant would actually say; a UI-local sound would prove nothing
 * about the TTS path (the Output Mute defect had exactly that shape).
 */
async function startPreview() {
  isPreviewing.value = true;
  previewMessage.value = '正在通过 Core 试听...';
  try {
    const res = await runtime.previewVoice();
    previewMessage.value = res
      ? '试听已开始。若不满意可随时取消。'
      : '试听请求被拒绝 (可能不在 Live 模式)';
    if (!res) isPreviewing.value = false;
  } catch (e: any) {
    previewMessage.value = `试听失败: ${e?.toString()}`;
    isPreviewing.value = false;
  }
}

/** Cancelling must silence the speaker, so it goes through the interrupt path. */
async function cancelPreview() {
  await runtime.cancelPlayback('preview_cancelled');
  isPreviewing.value = false;
  previewMessage.value = '试听已取消 (播放已停止)';
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
.action-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.warn-btn {
  background: #475569;
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

