import { ref } from 'vue';
import { TauriBridge, isTauriEnvironment } from '@/bridge/tauri-bridge';
import {
  clampToWorkArea,
  chooseWorkArea,
  parseSavedGeometry,
  resolveRestoredPosition,
} from './geometry.js';

/**
 * Window geometry for the pet window (PR-030).
 *
 * The arithmetic lives in `geometry.js` so Node can execute it; this composable
 * only performs the Tauri calls and keeps the reactive flags.
 *
 * Restoring a saved position goes through `resolveRestoredPosition`: a position
 * saved on a monitor that no longer exists would otherwise place the window
 * off-screen with no way to reach it (plan §8.3 / risk L1704).
 */
export function useWindowGeometry() {
  const isLocked = ref(false);
  const isClickThrough = ref(false);
  const isAlwaysOnTop = ref(true);

  /** A work area to fall back to when Tauri cannot report monitors. */
  const FALLBACK_AREA = { x: 0, y: 0, width: 1920, height: 1080 };
  const FALLBACK_POSITION = { x: 100, y: 100 };

  async function currentWorkAreas(): Promise<{ areas: any[]; primary: any | null }> {
    if (!isTauriEnvironment()) return { areas: [FALLBACK_AREA], primary: FALLBACK_AREA };
    try {
      const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow');
      // The monitor queries are module-level functions on `@tauri-apps/api/window`,
      // not methods on the window object.
      const { availableMonitors, primaryMonitor } = await import('@tauri-apps/api/window');
      const win = getCurrentWebviewWindow();
      const monitors = await availableMonitors();
      const primary = await primaryMonitor();
      const toArea = (m: any) => ({
        x: m.position.x,
        y: m.position.y,
        width: m.size.width,
        height: m.size.height,
      });
      const areas = (monitors ?? []).map(toArea);
      if (!areas.length) return { areas: [FALLBACK_AREA], primary: FALLBACK_AREA };
      return { areas, primary: primary ? toArea(primary) : null };
    } catch (e) {
      // A missing permission or a headless run must not leave the user without a
      // window: fall back to a single assumed monitor.
      console.warn('Could not read monitors; using a fallback area', e);
      return { areas: [FALLBACK_AREA], primary: FALLBACK_AREA };
    }
  }

  /**
   * Move the window to a position, clamped so it stays usable.
   *
   * Clamping happens here rather than at the call site so every path -- restore,
   * reset, and a drag that ended off-screen -- goes through it.
   */
  async function placeClamped(x: number, y: number): Promise<{ x: number; y: number }> {
    if (!isTauriEnvironment()) return { x, y };
    try {
      const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow');
      const { LogicalPosition } = await import('@tauri-apps/api/dpi');
      const win = getCurrentWebviewWindow();
      const size = await win.innerSize();
      const { areas, primary } = await currentWorkAreas();
      const area = chooseWorkArea({ x, y }, size, areas, primary) ?? FALLBACK_AREA;
      const target = clampToWorkArea({ x, y }, size, area);
      await win.setPosition(new LogicalPosition(target.x, target.y));
      return target;
    } catch (e) {
      console.warn('Failed to place window', e);
      return { x, y };
    }
  }

  /**
   * Restore a saved geometry, clamping it onto a monitor that exists.
   *
   * Returns the position actually used, so the caller can persist the corrected
   * value instead of re-saving a position that was already known to be bad.
   */
  async function restoreGeometry(saved: unknown): Promise<{ x: number; y: number }> {
    const parsed = parseSavedGeometry(saved);
    const { areas, primary } = await currentWorkAreas();
    const resolved = resolveRestoredPosition(parsed, areas, primary, FALLBACK_POSITION);
    const used = await placeClamped(resolved.position.x, resolved.position.y);
    if (resolved.clamped) {
      // Persist the corrected position: re-saving the position we just decided was
      // unusable would make the next start repeat the same clamp.
      void persist(used.x, used.y);
    }
    return used;
  }

  /**
   * Restore the saved position on startup, if there is one.
   *
   * Called from the character view rather than from module scope so the window is
   * already created and can be measured.
   */
  async function restoreSavedGeometry(): Promise<void> {
    if (!isTauriEnvironment()) return;
    try {
      const saved = await TauriBridge.getWindowGeometry();
      if (!saved) return;
      await restoreGeometry(saved);
    } catch (e) {
      console.warn('Could not restore window geometry', e);
    }
  }

  /** Remember where the window is now, so a restart can put it back. */
  async function persist(x: number, y: number): Promise<void> {
    if (!isTauriEnvironment()) return;
    try {
      const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow');
      const win = getCurrentWebviewWindow();
      const size = await win.innerSize();
      await TauriBridge.setWindowGeometry({
        x: Math.round(x),
        y: Math.round(y),
        width: Math.round(size.width),
        height: Math.round(size.height),
      });
    } catch (e) {
      console.warn('Could not persist window geometry', e);
    }
  }

  /** Remember the current position, whatever it is. */
  async function persistCurrent(): Promise<void> {
    if (!isTauriEnvironment()) return;
    try {
      const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow');
      const win = getCurrentWebviewWindow();
      const [pos, size] = await Promise.all([win.outerPosition(), win.innerSize()]);
      await persist(pos.x, pos.y);
    } catch (e) {
      console.warn('Could not persist current window geometry', e);
    }
  }

  /**
   * Remember the position, at most once per quiet period.
   *
   * A drag emits a move event per frame, so writing on every event would rewrite
   * the settings file hundreds of times for one gesture.  Debouncing keeps the
   * final position and skips the intermediate ones -- which is also the only one
   * worth keeping.
   */
  let persistTimer: ReturnType<typeof setTimeout> | null = null;
  function persistCurrentDebounced(delayMs = 400): void {
    if (persistTimer !== null) clearTimeout(persistTimer);
    persistTimer = setTimeout(() => {
      persistTimer = null;
      void persistCurrent();
    }, delayMs);
  }

  /**
   * Record moves for as long as this window lives, returning an unlisten.
   *
   * Called once from the character view.  A drag that ends off-screen is clamped
   * back on the next start, which is why the raw position is stored rather than a
   * clamped one: the clamp needs the live monitor list, and that belongs to the
   * next start, not to this one.
   */
  async function watchPosition(): Promise<() => void> {
    if (!isTauriEnvironment()) return () => {};
    try {
      const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow');
      const win = getCurrentWebviewWindow();
      const unlisten = await win.onMoved(() => persistCurrentDebounced());
      const unlistenResized = await win.onResized(() => persistCurrentDebounced());
      return () => {
        if (persistTimer !== null) {
          clearTimeout(persistTimer);
          persistTimer = null;
        }
        unlisten();
        unlistenResized();
      };
    } catch (e) {
      console.warn('Could not watch window position', e);
      return () => {};
    }
  }

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
    // Reset is a clamp, not a fixed coordinate: 100,100 is off-screen on a
    // monitor whose work area starts elsewhere.
    const used = await placeClamped(FALLBACK_POSITION.x, FALLBACK_POSITION.y);
    // Clearing the record is what makes the reset survive a restart; without it
    // the saved position would put the window straight back where it was.
    if (isTauriEnvironment()) {
      try {
        await TauriBridge.clearWindowGeometry();
      } catch (e) {
        console.warn('Could not clear saved window geometry', e);
      }
    }
    void used;
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
    placeClamped,
    restoreGeometry,
    restoreSavedGeometry,
    persistCurrent,
    persistCurrentDebounced,
    watchPosition,
  };
}
