<template>
  <div class="settings-window">
    <div class="settings-sidebar">
      <div class="sidebar-header">
        <h2>⚙️ 系统设置</h2>
      </div>
      <nav class="sidebar-nav">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="nav-item"
          :class="{ active: currentTab === tab.id }"
          @click="currentTab = tab.id"
        >
          <span class="tab-icon">{{ tab.icon }}</span>
          <span class="tab-title">{{ tab.title }}</span>
        </button>
      </nav>
    </div>

    <div class="settings-content">
      <component :is="currentTabComponent" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useSettingsStore } from '@/stores/settings';
import GeneralSection from './GeneralSection.vue';
import ModelSection from './ModelSection.vue';
import HearingSection from './HearingSection.vue';
import SpeechSection from './SpeechSection.vue';
import PrivacySection from './PrivacySection.vue';
import DiagnosticsSection from './DiagnosticsSection.vue';

const settingsStore = useSettingsStore();

const tabs = [
  { id: 'general', title: '通用设置', icon: '🛠️' },
  { id: 'model', title: '对话模型 (Hub)', icon: '🤖' },
  { id: 'hearing', title: '听觉 (ASR)', icon: '🎙️' },
  { id: 'speech', title: '发音 (TTS)', icon: '🔊' },
  { id: 'privacy', title: '隐私防护', icon: '🛡️' },
  { id: 'diagnostics', title: '诊断与导出', icon: '📊' },
];

const currentTab = ref('general');

const currentTabComponent = computed(() => {
  switch (currentTab.value) {
    case 'general':
      return GeneralSection;
    case 'model':
      return ModelSection;
    case 'hearing':
      return HearingSection;
    case 'speech':
      return SpeechSection;
    case 'privacy':
      return PrivacySection;
    case 'diagnostics':
      return DiagnosticsSection;
    default:
      return GeneralSection;
  }
});

onMounted(async () => {
  await settingsStore.loadSettings();
});
</script>

<style scoped>
.settings-window {
  display: flex;
  height: 100vh;
  width: 100vw;
  background: #0f172a;
  color: #f1f5f9;
  overflow: hidden;
}

.settings-sidebar {
  width: 220px;
  background: #1e293b;
  border-right: 1px solid #334155;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid #334155;
}

.sidebar-header h2 {
  font-size: 16px;
  font-weight: 600;
}

.sidebar-nav {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  background: transparent;
  border: none;
  color: #94a3b8;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s;
}

.nav-item:hover {
  background: #334155;
  color: #fff;
}

.nav-item.active {
  background: #2563eb;
  color: #fff;
  font-weight: 500;
}

.tab-icon {
  font-size: 14px;
}

.settings-content {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
}
</style>
