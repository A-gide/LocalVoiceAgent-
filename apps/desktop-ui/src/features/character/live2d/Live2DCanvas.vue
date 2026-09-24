<template>
  <div class="live2d-stage" ref="stageRef">
    <canvas
      ref="canvasRef"
      class="live2d-canvas"
      :class="{ interactive: renderer.isReady }"
      @click="handleClick"
    ></canvas>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { useRuntimeStore } from '@/stores/runtime';
import { Live2DRenderer } from './renderer';

const emit = defineEmits<{
  (e: 'ready'): void;
  (e: 'fallback', reason: string): void;
}>();

const runtime = useRuntimeStore();
const stageRef = ref<HTMLDivElement | null>(null);
const canvasRef = ref<HTMLCanvasElement | null>(null);
const renderer = new Live2DRenderer();

let mouthInterval: number | null = null;

function updateMouthAnimation(isSpeaking: boolean) {
  if (mouthInterval !== null) {
    clearInterval(mouthInterval);
    mouthInterval = null;
  }

  if (isSpeaking) {
    let t = 0;
    mouthInterval = window.setInterval(() => {
      t += 0.2;
      const level = (Math.sin(t * 3) + 1) * 0.4 + 0.1;
      renderer.setMouth(level);
    }, 60);
  } else {
    renderer.setMouth(0);
  }
}

watch(
  () => runtime.activity,
  (activity) => {
    if (!renderer.isReady) return;

    if (activity === 'speaking') {
      renderer.setMotion('TapBody');
      renderer.setExpression(2);
      updateMouthAnimation(true);
    } else if (activity === 'listening') {
      renderer.setExpression(1);
      updateMouthAnimation(false);
    } else if (activity === 'thinking') {
      renderer.setExpression(4);
      updateMouthAnimation(false);
    } else {
      renderer.setMotion('Idle');
      renderer.setExpression(0);
      updateMouthAnimation(false);
    }
  }
);

function handleClick() {
  if (!renderer.isReady) return;
  // Trigger a random interactive response motion
  const motions = ['TapBody', 'Idle'];
  const m = motions[Math.floor(Math.random() * motions.length)];
  renderer.setMotion(m);
}

function handleResize() {
  if (stageRef.value && canvasRef.value && renderer.isReady) {
    const rect = stageRef.value.getBoundingClientRect();
    renderer.fit(rect.width, rect.height);
  }
}

onMounted(async () => {
  if (!canvasRef.value) return;

  const ok = await renderer.init(canvasRef.value);
  if (ok) {
    emit('ready');
    window.addEventListener('resize', handleResize);
  } else {
    emit('fallback', renderer.errorMessage);
  }
});

onUnmounted(() => {
  window.removeEventListener('resize', handleResize);
  updateMouthAnimation(false);
  renderer.destroy();
});
</script>

<style scoped>
.live2d-stage {
  width: 100%;
  height: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  position: relative;
  overflow: hidden;
}

.live2d-canvas {
  width: 100%;
  height: 100%;
  display: block;
}

.live2d-canvas.interactive {
  cursor: pointer;
}
</style>
