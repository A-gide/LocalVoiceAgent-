<template>
  <div class="app-root">
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue';
import { useRouter } from 'vue-router';
import { useRuntimeStore } from '@/stores/runtime';
import { useChatStore } from '@/stores/chat';
import { TauriBridge, isTauriEnvironment } from '@/bridge/tauri-bridge';

const router = useRouter();
const runtime = useRuntimeStore();
const chat = useChatStore();

let unlisten: (() => void) | null = null;

onMounted(async () => {
  // If running inside Tauri, check the window label or query param to auto-route
  if (isTauriEnvironment()) {
    try {
      const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow');
      const win = getCurrentWebviewWindow();
      const label = win.label;
      if (label === 'settings') {
        router.replace('/settings');
      } else if (label === 'chat') {
        router.replace('/chat');
      } else if (label === 'memory') {
        router.replace('/memory');
      } else if (label === 'services') {
        router.replace('/services');
      }
    } catch (e) {
      console.warn('Failed to detect window label', e);
    }
  }

  // Subscribe to core events
  unlisten = await TauriBridge.listenEvent((event) => {
    runtime.handleEvent(event);

    // Chat turn events
    if (event.payload.type === 'turn.started') {
      chat.handleTurnStarted(
        event.payload.turn_id,
        event.payload.provider_epoch,
        event.payload.user_text
      );
    } else if (event.payload.type === 'turn.completed') {
      chat.handleTurnCompleted(
        event.payload.turn_id,
        event.payload.provider_epoch,
        event.payload.reply_text
      );
    } else if (event.payload.type === 'turn.cancelled') {
      chat.handleTurnCancelled(event.payload.turn_id, event.payload.reason);
    }
  });

  // Initial snapshot fetch
  await runtime.fetchSnapshot();
});

onUnmounted(() => {
  if (unlisten) unlisten();
});
</script>

<style>
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body, html, #app, .app-root {
  width: 100%;
  height: 100%;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
</style>
