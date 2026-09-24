import { defineStore } from 'pinia';
import { ref } from 'vue';
import { TauriBridge } from '@/bridge/tauri-bridge';

export interface MemoryItem {
  event_id: string;
  session_id?: string | null;
  occurred_at_utc: string;
  source: string;
  raw_text: string;
  current_text: string;
  revision: number;
  temporal_expression?: string | null;
  range_start_utc?: string | null;
  range_end_utc?: string | null;
}

export const useMemoryStore = defineStore('memory', () => {
  const items = ref<MemoryItem[]>([]);
  const isSearching = ref<boolean>(false);
  const lastQuery = ref<string>('');
  const statusMessage = ref<string | null>(null);

  async function search(query: string, limit = 20) {
    if (!query.trim()) return;
    isSearching.value = true;
    lastQuery.value = query;
    try {
      const userTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
      const res = await TauriBridge.sendCoreCommand('memory.search', {
        type: 'memory.search',
        query,
        limit,
        user_timezone: userTz,
      });

      if (res.status === 'applied' && res.data) {
        items.value = (res.data as any).results || [];
        statusMessage.value = `找到 ${items.value.length} 条记忆`;
      } else {
        statusMessage.value = res.error?.message || '搜索未返回结果';
      }
    } catch (e: any) {
      statusMessage.value = `搜索异常: ${e?.toString()}`;
    } finally {
      isSearching.value = false;
    }
  }

  async function correct(eventId: string, correctedText: string, reason: string) {
    try {
      const res = await TauriBridge.sendCoreCommand('memory.correct', {
        type: 'memory.correct',
        event_id: eventId,
        corrected_text: correctedText,
        reason,
        actor: 'user',
      },
        {
          aggregate: 'memory_event',
          resource_id: eventId,
          revision: items.value.find((i) => i.event_id === eventId)?.revision ?? 0,
        }
      );

      if (res.status === 'applied') {
        statusMessage.value = '记忆已修正 (新增修订版本)';
        const target = items.value.find((i) => i.event_id === eventId);
        if (target) {
          target.current_text = correctedText;
          target.revision++;
        }
      } else {
        statusMessage.value = `修正失败: ${res.error?.message || '拒绝'}`;
      }
    } catch (e: any) {
      statusMessage.value = `修正异常: ${e?.toString()}`;
    }
  }

  async function hardDelete(eventIds: string[], reasonCode = 'user_request') {
    try {
      const res = await TauriBridge.sendCoreCommand('memory.hard_delete', {
        type: 'memory.hard_delete',
        event_ids: eventIds,
        reason_code: reasonCode,
      },
        {
          aggregate: 'memory_event',
          resource_id: eventIds[0],
          revision: items.value.find((i) => i.event_id === eventIds[0])?.revision ?? 0,
        }
      );

      if (res.status === 'applied') {
        items.value = items.value.filter((i) => !eventIds.includes(i.event_id));
        statusMessage.value = `已审计硬删除 ${eventIds.length} 条记录`;
      } else {
        statusMessage.value = `删除失败: ${res.error?.message || '拒绝'}`;
      }
    } catch (e: any) {
      statusMessage.value = `删除异常: ${e?.toString()}`;
    }
  }

  return {
    items,
    isSearching,
    lastQuery,
    statusMessage,
    search,
    correct,
    hardDelete,
  };
});
