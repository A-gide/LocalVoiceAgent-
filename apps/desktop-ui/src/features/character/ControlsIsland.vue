<template>
  <div class="controls-island" :class="{ 'privacy-active': runtime.isPrivacyPause }">
    <!-- Privacy Scope / Recording Status Badge (1-second recognizable, text + icon + color) -->
    <div
      class="status-indicator"
      :class="statusClass"
      :title="privacyStatusTooltip"
      @click="togglePrivacyPause"
    >
      <span class="status-icon">{{ statusIcon }}</span>
      <span class="status-text">{{ statusText }}</span>
    </div>

    <div class="island-buttons">
      <!-- 1. Open Chat Button -->
      <button class="island-btn" title="打开对话窗口 (Chat)" @click="openChat">
        💬
      </button>

      <!-- 2. Mode Toggle (One-action switch between Live and Standby/Passive) -->
      <button
        class="island-btn"
        :class="{ active: runtime.isLive }"
        :title="runtime.isLive ? '当前: Live (点击转为 Standby)' : '当前: Standby (点击进入 Live)'"
        @click="toggleLiveMode"
      >
        {{ runtime.isLive ? '🔴 实时' : '⚪ 待机' }}
      </button>

      <!-- 3. Output Mute Button -->
      <button
        class="island-btn"
        :class="{ muted: runtime.isPlaybackMuted }"
        :title="runtime.isPlaybackMuted ? '恢复播放 (麦克风和录制保持当前模式)' : '静音播放 / Output Mute (麦克风和录制保持当前模式)'"
        aria-label="Output Mute / 静音播放"
        @click="toggleMute"
      >
        {{ runtime.isPlaybackMuted ? '🔇' : '🔊' }}
      </button>

      <!-- 4. Privacy Pause Button (One-action toggle) -->
      <button
        class="island-btn privacy-btn"
        :class="{ active: runtime.isPrivacyPause }"
        :title="runtime.isPrivacyPause ? '恢复采集 (Resume)' : '隐私暂停 (一键停止所有采集)'"
        @click="togglePrivacyPause"
      >
        🛡️ {{ runtime.isPrivacyPause ? '恢复' : '暂停' }}
      </button>

      <!-- 5. Settings / More Button -->
      <button class="island-btn" title="设置与控制面板" @click="openSettings">
        ⚙️
      </button>
    </div>

    <!-- Warning banner if external capture is present/unknown during privacy pause -->
    <div v-if="runtime.isPrivacyPause && !runtime.isPrivacyVerified" class="unverified-banner">
      ⚠️ 外部录音未验证停止 (仅本地核心已停)
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { useRuntimeStore } from '@/stores/runtime';
import { TauriBridge, isTauriEnvironment } from '@/bridge/tauri-bridge';

const router = useRouter();
const runtime = useRuntimeStore();

const statusClass = computed(() => {
  if (runtime.isPrivacyPause) {
    return runtime.isPrivacyVerified ? 'status-privacy-verified' : 'status-privacy-unverified';
  }
  if (runtime.isLive) {
    return 'status-live';
  }
  if (runtime.isPassive) {
    return 'status-passive';
  }
  return 'status-standby';
});

const statusIcon = computed(() => {
  if (runtime.isPrivacyPause) {
    return runtime.isPrivacyVerified ? '🛡️' : '⚠️';
  }
  if (runtime.isLive) return '🔴';
  if (runtime.isPassive) return '🟡';
  return '⚪';
});

const statusText = computed(() => {
  if (runtime.isPrivacyPause) {
    return runtime.isPrivacyVerified ? '已安全暂停' : '核心已暂停 (外部未确认)';
  }
  if (runtime.isLive) return '实时对话中';
  if (runtime.isPassive) return '被动记忆中';
  return '待命中';
});

const privacyStatusTooltip = computed(() => {
  switch (runtime.privacyScope) {
    case 'VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF':
      return '所有受控麦克风及屏幕采集已完全暂停。';
    case 'LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT':
      return 'LVA 核心已停止音频，但检测到外部 Screenpipe 实例仍运行。';
    case 'LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN':
      return 'LVA 核心已停止音频，外部录音状态未知。';
    default:
      return '系统正常运行中。';
  }
});

async function toggleLiveMode() {
  if (runtime.isLive) {
    await runtime.setMode('standby');
  } else {
    await runtime.setMode('live');
  }
}

async function togglePrivacyPause() {
  if (runtime.isPrivacyPause) {
    await runtime.restoreMode();
  } else {
    await runtime.setMode('privacy_pause');
  }
}

function toggleMute() {
  runtime.setMuted(!runtime.isPlaybackMuted);
}

async function openChat() {
  if (isTauriEnvironment()) {
    await TauriBridge.openChat();
  } else {
    router.push('/chat');
  }
}

async function openSettings() {
  if (isTauriEnvironment()) {
    await TauriBridge.openSettings();
  } else {
    router.push('/settings');
  }
}
</script>

<style scoped>
.controls-island {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  background: rgba(20, 24, 33, 0.85);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 16px;
  padding: 8px 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  color: #fff;
  transition: all 0.2s ease;
}

.controls-island.privacy-active {
  border-color: rgba(66, 184, 131, 0.6);
  background: rgba(15, 30, 25, 0.9);
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 10px;
  cursor: pointer;
  user-select: none;
}

.status-live {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

.status-passive {
  background: rgba(245, 158, 11, 0.2);
  color: #f59e0b;
}

.status-standby {
  background: rgba(156, 163, 175, 0.2);
  color: #9ca3af;
}

.status-privacy-verified {
  background: rgba(16, 185, 129, 0.25);
  color: #10b981;
}

.status-privacy-unverified {
  background: rgba(245, 158, 11, 0.25);
  color: #fbbf24;
}

.island-buttons {
  display: flex;
  align-items: center;
  gap: 6px;
}

.island-btn {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #e5e7eb;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: background 0.15s, transform 0.1s;
}

.island-btn:hover {
  background: rgba(255, 255, 255, 0.16);
  transform: translateY(-1px);
}

.island-btn.active {
  background: #3b82f6;
  border-color: #60a5fa;
  color: #fff;
}

.island-btn.privacy-btn.active {
  background: #10b981;
  border-color: #34d399;
}

.island-btn.muted {
  background: rgba(239, 68, 68, 0.2);
  border-color: rgba(239, 68, 68, 0.4);
}

.unverified-banner {
  font-size: 10px;
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.15);
  padding: 2px 6px;
  border-radius: 4px;
  text-align: center;
}
</style>
