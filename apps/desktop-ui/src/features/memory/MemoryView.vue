<template>
  <div class="memory-window">
    <div class="memory-header">
      <h2>🧠 长期记忆管理 (Journal v2)</h2>
      <p class="subtitle">支持中文时间自然语言检索，可追溯修订版本与审计物理删除</p>
    </div>

    <!-- Search Bar -->
    <div class="search-bar">
      <input
        v-model="queryText"
        type="text"
        placeholder="例如: 我昨天说了什么 / 关于项目的讨论..."
        class="search-input"
        @keyup.enter="handleSearch"
      />
      <button class="search-btn" :disabled="memory.isSearching" @click="handleSearch">
        {{ memory.isSearching ? '检索中...' : '搜索' }}
      </button>
    </div>

    <div v-if="memory.statusMessage" class="status-msg">
      {{ memory.statusMessage }}
    </div>

    <!-- Timeline / Item List -->
    <div class="timeline-list">
      <div v-if="memory.items.length === 0 && !memory.isSearching" class="empty-hint">
        暂无搜索结果，请输入检索关键词
      </div>

      <div v-for="item in memory.items" :key="item.event_id" class="memory-card">
        <div class="card-meta">
          <span class="meta-time">{{ item.occurred_at_utc }}</span>
          <span class="meta-source">来源: {{ item.source }}</span>
          <span v-if="item.revision > 0" class="revision-badge">
            修订版 v{{ item.revision }}
          </span>
        </div>

        <div class="card-text">
          <div class="current-text">
            <strong>当前内容:</strong> {{ item.current_text }}
          </div>
          <div v-if="item.revision > 0" class="raw-text">
            <span class="raw-tag">原始事实 (只读):</span> {{ item.raw_text }}
          </div>
        </div>

        <!--
          Temporal parse provenance (PR-029 / L1424 "provenance/timezone").
          A relative expression the parser could not resolve is shown as a
          degraded state instead of being silently dropped: the user needs to
          know the search anchor is approximate, not absent.
        -->
        <div class="card-meta-extra">
          <span v-if="item.temporal_expression" class="temporal-tag">
            时间表达: {{ item.temporal_expression }}
          </span>
          <span
            v-if="isParseDegraded(item)"
            class="degraded-tag"
            title="该时间表达无法完全解析，检索按降级范围进行"
          >
            ⚠️ 时间解析降级 (parse degraded)
          </span>
          <span v-if="item.range_start_utc" class="range-tag">
            检索范围: {{ formatRange(item.range_start_utc, item.range_end_utc) }}
          </span>
        </div>

        <div class="card-actions">
          <button class="btn-correct" @click="openCorrectModal(item)">
            ✏️ 修正
          </button>
          <button class="btn-delete" @click="confirmDelete(item.event_id)">
            🗑️ 审计删除
          </button>
        </div>
      </div>
    </div>

    <!-- Correction Modal -->
    <div v-if="correctingItem" class="modal-overlay">
      <div class="modal-box">
        <h3>修正记忆内容</h3>
        <p class="modal-hint">原始数据保持不可变，修正将新增一条追溯修订版本。</p>
        <textarea
          v-model="correctText"
          class="modal-textarea"
          rows="4"
          placeholder="输入修正后的内容..."
        ></textarea>
        <input
          v-model="correctReason"
          type="text"
          class="modal-input"
          placeholder="修正原因 (如: ASR 识别错别字 / 补充信息)"
        />
        <div class="modal-buttons">
          <button class="btn-secondary" @click="correctingItem = null">取消</button>
          <button class="btn-primary" @click="submitCorrect">提交修正</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useMemoryStore, type MemoryItem } from '@/stores/memory';

const memory = useMemoryStore();
const queryText = ref('');

const correctingItem = ref<MemoryItem | null>(null);
const correctText = ref('');
const correctReason = ref('');

/**
 * A temporal expression that produced no usable range is a *degraded* parse:
 * the Core still answered, but it could not anchor the query in time, so the
 * user must be told rather than left believing the range was exact.
 */
function isParseDegraded(item: MemoryItem): boolean {
  const expression = (item.temporal_expression || '').trim();
  if (!expression) return false;
  return !item.range_start_utc || !item.range_end_utc;
}

function formatRange(start: string, end?: string | null): string {
  const from = start.replace('T', ' ').replace('Z', ' UTC');
  if (!end) return `${from} → 至今`;
  return `${from} → ${end.replace('T', ' ').replace('Z', ' UTC')}`;
}

async function handleSearch() {
  await memory.search(queryText.value);
}

function openCorrectModal(item: MemoryItem) {
  correctingItem.value = item;
  correctText.value = item.current_text;
  correctReason.value = '用户手动修正';
}

async function submitCorrect() {
  if (!correctingItem.value || !correctText.value.trim()) return;
  await memory.correct(
    correctingItem.value.event_id,
    correctText.value.trim(),
    correctReason.value.trim()
  );
  correctingItem.value = null;
}

async function confirmDelete(eventId: string) {
  if (confirm('确定物理硬删除此条记忆记录？该操作将留下安全审计日志且不可恢复。')) {
    await memory.hardDelete([eventId], 'user_explicit_delete');
  }
}
</script>

<style scoped>
.memory-window {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  background: #0b0f19;
  color: #f1f5f9;
  padding: 16px;
  overflow: hidden;
}

.memory-header h2 {
  font-size: 18px;
  margin-bottom: 4px;
}

.subtitle {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 12px;
}

.search-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.search-input {
  flex: 1;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 8px 12px;
  color: #fff;
  font-size: 14px;
  outline: none;
}

.search-input:focus {
  border-color: #3b82f6;
}

.search-btn {
  background: #3b82f6;
  border: none;
  border-radius: 8px;
  padding: 0 16px;
  color: #fff;
  font-weight: 500;
  cursor: pointer;
}

.status-msg {
  font-size: 12px;
  color: #38bdf8;
  margin-bottom: 8px;
}

.timeline-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.empty-hint {
  text-align: center;
  color: #64748b;
  margin-top: 40px;
  font-size: 13px;
}

.memory-card {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #94a3b8;
}

.revision-badge {
  background: #0284c7;
  color: #fff;
  padding: 1px 6px;
  border-radius: 4px;
}

.card-text {
  font-size: 13px;
  line-height: 1.5;
}

.raw-text {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

.raw-tag {
  color: #f59e0b;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.card-meta-extra {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11px;
  color: #94a3b8;
}

.temporal-tag {
  background: #1e3a5f;
  color: #93c5fd;
  padding: 1px 6px;
  border-radius: 4px;
}

.degraded-tag {
  background: rgba(245, 158, 11, 0.2);
  color: #f59e0b;
  padding: 1px 6px;
  border-radius: 4px;
}

.range-tag {
  color: #64748b;
}

.btn-correct, .btn-delete {
  background: transparent;
  border: 1px solid #475569;
  color: #cbd5e1;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}

.btn-correct:hover {
  background: #334155;
}

.btn-delete:hover {
  background: rgba(239, 68, 68, 0.2);
  border-color: #ef4444;
  color: #f87171;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-box {
  background: #1e293b;
  border: 1px solid #475569;
  border-radius: 12px;
  padding: 20px;
  width: 90%;
  max-width: 480px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.modal-hint {
  font-size: 12px;
  color: #94a3b8;
}

.modal-textarea, .modal-input {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 6px;
  padding: 8px;
  color: #fff;
  font-size: 13px;
  outline: none;
}

.modal-buttons {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}

.btn-primary {
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 6px 14px;
  cursor: pointer;
}

.btn-secondary {
  background: #475569;
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 6px 14px;
  cursor: pointer;
}
</style>
