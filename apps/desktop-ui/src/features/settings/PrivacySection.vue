<template>
  <div class="settings-section">
    <h3>隐私与数据防护 (Privacy & Data Protection)</h3>

    <!-- Privacy Scope Status Card -->
    <div class="card">
      <div class="card-header">
        <strong>当前隐私保护范围 (Privacy Scope)</strong>
        <span class="scope-tag" :class="scopeTagClass">
          {{ scopeLabel }}
        </span>
      </div>
      <div class="card-body">
        <p class="scope-detail">{{ scopeExplanation }}</p>

        <div v-if="runtime.privacyScope === 'LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT'" class="warn-box">
          ⚠️ 警告: 检测到外部独立运行的 Screenpipe 进程。LVA 核心已停止自身录音，但无法控制外部 Screenpipe 的录音与屏幕截图。
        </div>

        <div v-if="runtime.privacyScope === 'LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN'" class="warn-box">
          ⚠️ 提示: 外部采集器状态无法确认。
        </div>
      </div>
    </div>

    <!-- Data Principles -->
    <div class="card">
      <div class="card-header">
        <strong>核心隐私承诺</strong>
      </div>
      <div class="card-body">
        <ul class="principles-list">
          <li><strong>零凭证入前端:</strong> 核心 Token、API Key 严格保存在本地系统加密层，WebView 无法读取。</li>
          <li><strong>事实不可变:</strong> ASR 原始录音事实写入后只读不可修改；所有修正均以带审计原因的修订版本追加。</li>
          <li><strong>可审计硬删除:</strong> 物理删除操作会留下哈希指纹审计日志，杜绝静默残留。</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRuntimeStore } from '@/stores/runtime';

const runtime = useRuntimeStore();

const scopeLabel = computed(() => {
  switch (runtime.privacyScope) {
    case 'VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF':
      return '已完全暂停 (已验证)';
    case 'LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT':
      return '核心已停 (外部仍录制)';
    case 'LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN':
      return '核心已停 (外部状态未知)';
    default:
      return '采集运行中';
  }
});

const scopeTagClass = computed(() => {
  switch (runtime.privacyScope) {
    case 'VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF':
      return 'tag-green';
    case 'LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT':
    case 'LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN':
      return 'tag-yellow';
    default:
      return 'tag-gray';
  }
});

const scopeExplanation = computed(() => {
  switch (runtime.privacyScope) {
    case 'VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF':
      return 'LVA 核心麦克风采集已切断，且已确认受控 Screenpipe 录音已停止。';
    case 'LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT':
      return 'LVA 核心麦克风已切断，但外部系统存在独立 Screenpipe 捕获源。';
    case 'LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN':
      return 'LVA 核心麦克风已切断，外部采集状态未确认。';
    default:
      return '系统处于正常工作状态，按需进行麦克风监听或被动记忆。';
  }
});
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
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.scope-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
}
.tag-green {
  background: #059669;
  color: #fff;
}
.tag-yellow {
  background: #d97706;
  color: #fff;
}
.tag-gray {
  background: #475569;
  color: #cbd5e1;
}
.scope-detail {
  font-size: 13px;
  color: #cbd5e1;
  line-height: 1.5;
}
.warn-box {
  margin-top: 8px;
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.3);
  color: #fbbf24;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
}
.principles-list {
  padding-left: 18px;
  font-size: 13px;
  color: #cbd5e1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>
