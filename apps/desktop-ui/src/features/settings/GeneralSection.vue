<template>
  <div class="settings-section">
    <h3>通用设置 (General)</h3>
    <div class="setting-row">
      <div class="setting-info">
        <label>开机自启动</label>
        <span class="setting-desc">Windows 登录后自动在后台托盘启动</span>
      </div>
      <input
        type="checkbox"
        :checked="settingsStore.autostart"
        @change="e => settingsStore.toggleAutostart((e.target as HTMLInputElement).checked)"
      />
    </div>

    <div class="setting-row">
      <div class="setting-info">
        <label>休眠释放显存策略</label>
        <span class="setting-desc">无交互超时后自动卸载模型释放约 4.9GB 显存</span>
      </div>
      <select class="setting-select" v-model="idleMins">
        <option :value="0">从不释放</option>
        <option :value="5">5 分钟</option>
        <option :value="15">15 分钟 (推荐)</option>
        <option :value="30">30 分钟</option>
      </select>
    </div>

    <div class="setting-row">
      <div class="setting-info">
        <label>深度休眠模式 (Dormancy)</label>
        <span class="setting-desc">隐藏宠物时彻底销毁 WebView 进程，节约 ~440MB 内存</span>
      </div>
      <input type="checkbox" checked disabled />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useSettingsStore } from '@/stores/settings';

const settingsStore = useSettingsStore();
const idleMins = ref(15);
</script>

<style scoped>
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.setting-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
}
.setting-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.setting-info label {
  font-weight: 500;
  font-size: 14px;
}
.setting-desc {
  font-size: 12px;
  color: #94a3b8;
}
.setting-select {
  background: #0f172a;
  border: 1px solid #334155;
  color: #fff;
  padding: 6px 10px;
  border-radius: 6px;
}
</style>
