<template>
  <div class="settings-section">
    <h3>系统诊断与导出 (Diagnostics)</h3>
    <p class="section-desc">
      查看脱敏运行时指标并导出安全支持诊断包（不包含密钥、Token、个人绝对路径或音频数据）。
    </p>

    <!-- Services Overview Card -->
    <div class="card">
      <div class="card-header">
        <strong>服务运行拓扑</strong>
      </div>
      <div class="services-grid">
        <div v-for="(svc, name) in runtime.state.services" :key="name" class="service-item">
          <div class="svc-name">{{ name }}</div>
          <div class="svc-status" :class="'state-' + svc.state">
            {{ svc.state }}
          </div>
        </div>
      </div>
    </div>

    <!-- Export Redacted Diagnostics Bundle -->
    <div class="card">
      <div class="card-header">
        <strong>脱敏诊断支持包</strong>
      </div>
      <div class="card-body">
        <p class="bundle-desc">
          导出当前架构组件状态、最近脱敏事件序列及延迟统计，用于排查故障。
        </p>
        <button class="export-btn" :disabled="isExporting" @click="handleExport">
          {{ isExporting ? '正在生成...' : '📦 导出脱敏诊断包' }}
        </button>
        <div v-if="exportResult" class="export-result">
          {{ exportResult }}
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
const isExporting = ref(false);
const exportResult = ref<string | null>(null);

async function handleExport() {
  isExporting.value = true;
  exportResult.value = null;
  try {
    const res = await TauriBridge.sendCoreCommand('diagnostics.export_redacted', {
      type: 'diagnostics.export_redacted',
    });
    if (res.status === 'applied') {
      exportResult.value = '诊断包已成功生成 (已脱敏)';
    } else {
      exportResult.value = `导出失败: ${res.error?.message || '拒绝'}`;
    }
  } catch (e: any) {
    exportResult.value = `导出异常: ${e?.toString()}`;
  } finally {
    isExporting.value = false;
  }
}
</script>

<style scoped>
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.section-desc {
  font-size: 13px;
  color: #94a3b8;
}
.card {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-header {
  font-size: 14px;
  font-weight: 600;
}
.services-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}
.service-item {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 6px;
  padding: 8px 10px;
}
.svc-name {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 4px;
}
.svc-status {
  font-size: 13px;
  font-weight: 600;
}
.state-healthy {
  color: #10b981;
}
.state-starting {
  color: #38bdf8;
}
.state-degraded {
  color: #f59e0b;
}
.state-failed, .state-stopped {
  color: #94a3b8;
}
.bundle-desc {
  font-size: 13px;
  color: #cbd5e1;
  margin-bottom: 10px;
}
.export-btn {
  background: #2563eb;
  border: none;
  color: #fff;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}
.export-result {
  margin-top: 8px;
  font-size: 12px;
  color: #38bdf8;
}
</style>
