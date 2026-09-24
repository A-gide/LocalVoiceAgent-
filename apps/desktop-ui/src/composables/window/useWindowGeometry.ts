import { ref } from 'vue';
import { isTauriEnvironment } from '@/bridge/tauri-bridge';

export function useWindowGeometry() {
  const isLocked = ref(false);
  const isClickThrough = ref(false);
  const isAlwaysOnTop = ref(true);

  async function toggleClickThrough() {
    isClickThrough.value = !isClickThrough.value;
    if (isTauriEnvironment()) {
      try {
        const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow');
        const win = getCurrentWebviewWindow();
        await win.setIgnoreCursorEvents(isClickThrough.value);
      } catch (e) {
        console.warn('Failed to set click through', e);
      }
    }
  }

  async function toggleLock() {
    isLocked.value = !isLocked.value;
  }

  async function resetPosition() {
    if (isTauriEnvironment()) {
      try {
        const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow');
        const { LogicalPosition } = await import('@tauri-apps/api/dpi');
        const win = getCurrentWebviewWindow();
        await win.setPosition(new LogicalPosition(100, 100));
      } catch (e) {
        console.warn('Failed to reset position', e);
      }
    }
  }

  async function startDrag() {
    if (isLocked.value) return;
    if (isTauriEnvironment()) {
      try {
        const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow');
        const win = getCurrentWebviewWindow();
        await win.startDragging();
      } catch (e) {
        console.warn('Failed to start drag', e);
      }
    }
  }

  return {
    isLocked,
    isClickThrough,
    isAlwaysOnTop,
    toggleClickThrough,
    toggleLock,
    resetPosition,
    startDrag,
  };
}
