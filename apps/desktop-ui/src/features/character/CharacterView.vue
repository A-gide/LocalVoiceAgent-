<template>
  <div class="character-container" @mousedown="handleMouseDown">
    <!-- Top toolbar for window geometry / locking -->
    <div class="window-bar" :class="{ 'bar-locked': geometry.isLocked.value }">
      <div class="drag-handle" title="按住拖动窗口">⋮⋮</div>
      <div class="window-actions">
        <button
          class="icon-btn"
          :title="geometry.isLocked.value ? '已锁定位置' : '锁定位置'"
          @click="geometry.toggleLock"
        >
          {{ geometry.isLocked.value ? '🔒' : '🔓' }}
        </button>
        <button
          class="icon-btn"
          :title="geometry.isClickThrough.value ? '已开启鼠标穿透' : '开启鼠标穿透'"
          @click="geometry.toggleClickThrough"
        >
          🖱️
        </button>
        <button class="icon-btn" title="重置窗口位置" @click="geometry.resetPosition">
          🔄
        </button>
      </div>
    </div>

    <!-- Avatar Canvas / Live2D with speech animation -->
    <div class="avatar-area">
      <div class="avatar-bubble" v-if="runtime.activity === 'speaking'">
        💬 说话中...
      </div>
      <div class="avatar-bubble listening" v-else-if="runtime.activity === 'listening'">
        👂 正在倾听...
      </div>
      <div class="avatar-bubble thinking" v-else-if="runtime.activity === 'thinking'">
        🤔 思考中...
      </div>

      <!-- Live2D WebGL Renderer -->
      <div class="live2d-wrapper" :class="{ hidden: !live2dReady }">
        <Live2DCanvas
          @ready="handleLive2DReady"
          @fallback="handleLive2DFallback"
        />
      </div>

      <!-- Fallback Avatar Graphic (shown when Live2D is loading or unavailable) -->
      <div
        v-if="!live2dReady"
        class="avatar-figure"
        :class="{
          speaking: runtime.activity === 'speaking',
          listening: runtime.activity === 'listening',
        }"
      >
        <div class="avatar-face">
          <div class="eye left"></div>
          <div class="eye right"></div>
          <div class="mouth" :class="{ open: runtime.activity === 'speaking' }"></div>
        </div>
        <div class="avatar-body"></div>
      </div>
    </div>

    <!-- Controls Island pinned at bottom -->
    <div class="island-container">
      <ControlsIsland />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRuntimeStore } from '@/stores/runtime';
import { useWindowGeometry } from '@/composables/window/useWindowGeometry';
import ControlsIsland from './ControlsIsland.vue';
import Live2DCanvas from './live2d/Live2DCanvas.vue';

const runtime = useRuntimeStore();
const geometry = useWindowGeometry();

const live2dReady = ref(false);
const live2dError = ref(false);

function handleLive2DReady() {
  live2dReady.value = true;
  live2dError.value = false;
}

function handleLive2DFallback(reason: string) {
  console.warn('[CharacterView] Live2D fallback active:', reason);
  live2dReady.value = false;
  live2dError.value = true;
}

function handleMouseDown(e: MouseEvent) {
  // Start drag if clicking background and not locked
  const target = e.target as HTMLElement;
  if (!target.closest('button') && !target.closest('.controls-island')) {
    geometry.startDrag();
  }
}

onMounted(async () => {
  // PR-031: put the window back where the user left it, clamped onto a monitor
  // that still exists.  This runs before the snapshot fetch so a stale position
  // is corrected even if the Core is slow to answer.
  await geometry.restoreSavedGeometry();
  await runtime.fetchSnapshot();
});
</script>

<style scoped>
.character-container {
  width: 100vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  align-items: center;
  padding: 8px;
  background: transparent;
  position: relative;
  overflow: hidden;
}

.window-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 2px 6px;
  opacity: 0.3;
  transition: opacity 0.2s;
  cursor: grab;
  z-index: 10;
}

.window-bar:hover {
  opacity: 1;
}

.drag-handle {
  color: #fff;
  font-size: 14px;
  letter-spacing: 2px;
}

.window-actions {
  display: flex;
  gap: 4px;
}

.icon-btn {
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #fff;
  border-radius: 4px;
  padding: 2px 4px;
  font-size: 11px;
  cursor: pointer;
}

.avatar-area {
  flex: 1;
  width: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  position: relative;
  min-height: 0;
}

.live2d-wrapper {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  transition: opacity 0.3s ease;
}

.live2d-wrapper.hidden {
  opacity: 0;
  pointer-events: none;
}

.avatar-bubble {
  position: absolute;
  top: 10px;
  background: rgba(255, 255, 255, 0.9);
  color: #111;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  animation: bounce 1.5s infinite;
  z-index: 10;
}

.avatar-bubble.listening {
  background: #fef08a;
}

.avatar-bubble.thinking {
  background: #bfdbfe;
}

.avatar-figure {
  width: 140px;
  height: 180px;
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  transition: transform 0.2s;
}

.avatar-figure.speaking {
  animation: bob 0.6s infinite alternate ease-in-out;
}

.avatar-face {
  width: 90px;
  height: 90px;
  background: #ffe4e6;
  border-radius: 50%;
  border: 3px solid #fda4af;
  position: relative;
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.2);
}

.eye {
  width: 10px;
  height: 14px;
  background: #334155;
  border-radius: 50%;
  position: absolute;
  top: 32px;
}

.eye.left {
  left: 22px;
}

.eye.right {
  right: 22px;
}

.mouth {
  width: 12px;
  height: 6px;
  background: #e11d48;
  border-radius: 0 0 10px 10px;
  position: absolute;
  bottom: 22px;
  left: 50%;
  transform: translateX(-50%);
  transition: height 0.1s;
}

.mouth.open {
  height: 16px;
  border-radius: 50%;
}

.avatar-body {
  width: 110px;
  height: 80px;
  background: #38bdf8;
  border-radius: 40px 40px 16px 16px;
  margin-top: -8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.island-container {
  width: 100%;
  max-width: 320px;
  margin-bottom: 6px;
  z-index: 10;
}

@keyframes bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}

@keyframes bob {
  0% { transform: translateY(0); }
  100% { transform: translateY(-6px); }
}
</style>
