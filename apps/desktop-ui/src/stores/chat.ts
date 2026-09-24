import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { TurnId } from '@/generated/lva-ipc';
import { TauriBridge } from '@/bridge/tauri-bridge';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  turnId?: TurnId | null;
  isStreaming?: boolean;
}

export interface TurnTrace {
  turnId: TurnId;
  providerEpoch: number;
  startedAt: string;
  completedAt?: string;
  userText?: string;
  replyText?: string;
  cancelled?: boolean;
  cancelReason?: string;
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([]);
  const activeTurn = ref<TurnId | null>(null);
  const isStreaming = ref<boolean>(false);
  const currentStreamContent = ref<string>('');
  const traces = ref<TurnTrace[]>([]);
  const showDiagnostics = ref<boolean>(false);

  async function sendText(text: string) {
    if (!text.trim()) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID ? crypto.randomUUID() : 'msg-' + Date.now(),
      role: 'user',
      content: text,
      timestamp: new Date().toLocaleTimeString(),
    };
    messages.value.push(userMsg);

    isStreaming.value = true;
    currentStreamContent.value = '';

    try {
      const result = await TauriBridge.sendCoreCommand('turn.send_text', {
        type: 'turn.send_text',
        text,
      });

      if (result.status === 'rejected') {
        messages.value.push({
          id: 'err-' + Date.now(),
          role: 'system',
          content: `发送失败: ${result.error?.message || '未知错误'}`,
          timestamp: new Date().toLocaleTimeString(),
        });
        isStreaming.value = false;
      }
    } catch (e: any) {
      messages.value.push({
        id: 'err-' + Date.now(),
        role: 'system',
        content: `发送异常: ${e?.toString() || '网络/IPC 错误'}`,
        timestamp: new Date().toLocaleTimeString(),
      });
      isStreaming.value = false;
    }
  }

  async function cancelTurn(reason = 'user_cancel') {
    try {
      await TauriBridge.sendCoreCommand('turn.cancel', {
        type: 'turn.cancel',
        turn_id: activeTurn.value,
        reason,
      });
      isStreaming.value = false;
    } catch (e) {
      console.error('Failed to cancel turn', e);
    }
  }

  function handleTurnStarted(turnId: TurnId, epoch: number, userText?: string | null) {
    activeTurn.value = turnId;
    isStreaming.value = true;
    currentStreamContent.value = '';

    traces.value.unshift({
      turnId,
      providerEpoch: epoch,
      startedAt: new Date().toISOString(),
      userText: userText ?? undefined,
    });
  }

  function handleTurnCompleted(turnId: TurnId, epoch: number, replyText: string) {
    if (activeTurn.value?.sequence === turnId.sequence) {
      activeTurn.value = null;
      isStreaming.value = false;

      messages.value.push({
        id: 'reply-' + Date.now(),
        role: 'assistant',
        content: replyText,
        timestamp: new Date().toLocaleTimeString(),
        turnId,
      });

      const trace = traces.value.find((t) => t.turnId.sequence === turnId.sequence);
      if (trace) {
        trace.completedAt = new Date().toISOString();
        trace.replyText = replyText;
      }
    }
  }

  function handleTurnCancelled(turnId: TurnId, reason: string) {
    if (activeTurn.value?.sequence === turnId.sequence) {
      activeTurn.value = null;
      isStreaming.value = false;

      messages.value.push({
        id: 'cancel-' + Date.now(),
        role: 'system',
        content: `[已打断 / 取消: ${reason}]`,
        timestamp: new Date().toLocaleTimeString(),
        turnId,
      });

      const trace = traces.value.find((t) => t.turnId.sequence === turnId.sequence);
      if (trace) {
        trace.cancelled = true;
        trace.cancelReason = reason;
        trace.completedAt = new Date().toISOString();
      }
    }
  }

  function clearMessages() {
    messages.value = [];
  }

  return {
    messages,
    activeTurn,
    isStreaming,
    currentStreamContent,
    traces,
    showDiagnostics,
    sendText,
    cancelTurn,
    handleTurnStarted,
    handleTurnCompleted,
    handleTurnCancelled,
    clearMessages,
  };
});
