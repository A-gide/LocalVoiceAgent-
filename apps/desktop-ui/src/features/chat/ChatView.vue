<template>
  <div class="chat-window">
    <!-- Header -->
    <div class="chat-header">
      <div class="header-title">
        <span>💬 对话记录</span>
        <span class="active-badge" v-if="chat.isStreaming">⚡ 生成中</span>
      </div>
      <div class="header-actions">
        <button
          class="subtle-btn"
          :class="{ active: chat.showDiagnostics }"
          title="切换诊断面板"
          @click="chat.showDiagnostics = !chat.showDiagnostics"
        >
          🔍 诊断
        </button>
        <button class="subtle-btn" title="清空对话" @click="chat.clearMessages">
          🗑️ 清空
        </button>
      </div>
    </div>

    <!-- Main Message List -->
    <div class="message-list" ref="messageContainer">
      <div v-if="chat.messages.length === 0" class="empty-state">
        <p>暂无对话记录</p>
        <p class="subtitle">在下方输入文字，或通过语音唤醒对话</p>
      </div>

      <div
        v-for="msg in chat.messages"
        :key="msg.id"
        class="message-bubble"
        :class="'role-' + msg.role"
      >
        <div class="bubble-header">
          <span class="role-name">{{ roleLabel(msg.role) }}</span>
          <span class="msg-time">{{ msg.timestamp }}</span>
          <span v-if="msg.turnId" class="turn-tag">Turn #{{ msg.turnId.sequence }}</span>
        </div>
        <div class="bubble-content">{{ msg.content }}</div>
      </div>

      <!-- Live streaming preview -->
      <div v-if="chat.isStreaming && chat.currentStreamContent" class="message-bubble role-assistant streaming">
        <div class="bubble-header">
          <span class="role-name">AI 助手</span>
          <span class="streaming-indicator">生成中...</span>
        </div>
        <div class="bubble-content">{{ chat.currentStreamContent }}</div>
      </div>
    </div>

    <!-- Advanced Turn Diagnostics Drawer (collapsible) -->
    <div v-if="chat.showDiagnostics" class="diagnostics-panel">
      <div class="diag-header">
        <strong>最近 Turns 诊断追踪 (Turn Diagnostics)</strong>
      </div>
      <div v-if="chat.traces.length === 0" class="diag-empty">暂无 Turn 追踪数据</div>
      <div v-for="trace in chat.traces" :key="trace.turnId.sequence" class="trace-item">
        <div class="trace-row">
          <span class="trace-id">Turn #{{ trace.turnId.sequence }}</span>
          <span class="trace-epoch">Epoch: {{ trace.providerEpoch }}</span>
          <span v-if="trace.cancelled" class="trace-cancelled">已打断 ({{ trace.cancelReason }})</span>
        </div>
        <div v-if="trace.userText" class="trace-text">用户: {{ trace.userText }}</div>
        <div v-if="trace.replyText" class="trace-text">回答: {{ trace.replyText }}</div>
      </div>
    </div>

    <!-- Input Footer -->
    <div class="chat-footer">
      <input
        v-model="inputQuery"
        type="text"
        placeholder="输入消息向助手提问..."
        class="chat-input"
        :disabled="chat.isStreaming"
        @keyup.enter="handleSend"
      />
      <button v-if="!chat.isStreaming" class="send-btn" @click="handleSend">
        发送
      </button>
      <button v-else class="cancel-btn" @click="handleCancel">
        打断 / 取消
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch } from 'vue';
import { useChatStore } from '@/stores/chat';

const chat = useChatStore();
const inputQuery = ref('');
const messageContainer = ref<HTMLElement | null>(null);

function roleLabel(role: string) {
  switch (role) {
    case 'user':
      return '我';
    case 'assistant':
      return 'AI 助手';
    default:
      return '系统';
  }
}

async function handleSend() {
  const text = inputQuery.value.trim();
  if (!text) return;
  inputQuery.value = '';
  await chat.sendText(text);
  scrollToBottom();
}

async function handleCancel() {
  await chat.cancelTurn('user_manual_cancel');
}

function scrollToBottom() {
  nextTick(() => {
    if (messageContainer.value) {
      messageContainer.value.scrollTop = messageContainer.value.scrollHeight;
    }
  });
}

watch(() => chat.messages.length, scrollToBottom);
</script>

<style scoped>
.chat-window {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  background: #0f172a;
  color: #e2e8f0;
  font-family: inherit;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
}

.active-badge {
  font-size: 11px;
  background: #2563eb;
  padding: 2px 6px;
  border-radius: 6px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.subtle-btn {
  background: transparent;
  border: 1px solid #475569;
  color: #cbd5e1;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.subtle-btn:hover {
  background: #334155;
}

.subtle-btn.active {
  background: #3b82f6;
  border-color: #60a5fa;
  color: #fff;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #64748b;
  gap: 6px;
}

.subtitle {
  font-size: 13px;
}

.message-bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}

.role-user {
  align-self: flex-end;
  background: #2563eb;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.role-assistant {
  align-self: flex-start;
  background: #1e293b;
  border: 1px solid #334155;
  color: #f1f5f9;
  border-bottom-left-radius: 4px;
}

.role-system {
  align-self: center;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #f87171;
  font-size: 12px;
  padding: 4px 10px;
}

.bubble-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  font-size: 11px;
  opacity: 0.8;
}

.turn-tag {
  background: rgba(255, 255, 255, 0.15);
  padding: 1px 4px;
  border-radius: 4px;
}

.diagnostics-panel {
  background: #111827;
  border-top: 1px solid #374151;
  padding: 10px 16px;
  max-height: 150px;
  overflow-y: auto;
  font-size: 12px;
}

.diag-header {
  margin-bottom: 6px;
  color: #94a3b8;
}

.trace-item {
  padding: 4px 0;
  border-bottom: 1px solid #1f2937;
}

.trace-row {
  display: flex;
  gap: 8px;
  color: #38bdf8;
}

.trace-cancelled {
  color: #f87171;
}

.chat-footer {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  background: #1e293b;
  border-top: 1px solid #334155;
}

.chat-input {
  flex: 1;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 8px 12px;
  color: #f1f5f9;
  font-size: 14px;
  outline: none;
}

.chat-input:focus {
  border-color: #3b82f6;
}

.send-btn {
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0 16px;
  font-weight: 500;
  cursor: pointer;
}

.cancel-btn {
  background: #dc2626;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0 16px;
  font-weight: 500;
  cursor: pointer;
}
</style>
