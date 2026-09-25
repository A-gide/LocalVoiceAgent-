/**
 * Window geometry: clamp, persistence and reset (PR-030 / PR-031).
 *
 * Plain ESM with JSDoc types so the exact arithmetic runs under Node in a test,
 * not merely string-matched in the component.  The composable imports this
 * module and so does the test.
 *
 * Why this exists (plan §8.3, L1704): a window restored from a stale position can
 * land off-screen when a monitor is unplugged, the resolution changes or the DPI
 * differs.  The frozen fallback strategy is: keep Tauri v2, clamp to the current
 * monitor work area before restoring, and offer Reset Position.  It is explicitly
 * not "switch frameworks".
 */

/**
 * A monitor work area, in the coordinate space the window position uses.
 * @typedef {{ x: number, y: number, width: number, height: number }} WorkArea
 */

/**
 * Clamp a window position so the whole window stays inside a work area.
 *
 * The window is kept *fully* inside rather than merely intersecting: a pet window
 * with only a few pixels on screen is reachable but not usable, and the plan asks
 * for a usable fallback.
 *
 * A window larger than the work area is pinned to the area's origin instead of
 * producing a negative offset -- clamping both ends would otherwise oscillate
 * between the two bounds and land somewhere arbitrary.
 *
 * @param {{ x: number, y: number }} position
 * @param {{ width: number, height: number }} size
 * @param {WorkArea} area
 * @returns {{ x: number, y: number }}
 */
export function clampToWorkArea(position, size, area) {
  const maxX = area.x + area.width - size.width;
  const maxY = area.y + area.height - size.height;

  // min > max means the window does not fit: pin to the top-left of the area.
  const x = maxX < area.x ? area.x : Math.min(Math.max(position.x, area.x), maxX);
  const y = maxY < area.y ? area.y : Math.min(Math.max(position.y, area.y), maxY);
  return { x, y };
}

/**
 * Is the window already fully inside the area?
 *
 * Used to decide whether a restore needs clamping at all, so a healthy saved
 * position is restored byte-for-byte rather than nudged by rounding.
 *
 * @param {{ x: number, y: number }} position
 * @param {{ width: number, height: number }} size
 * @param {WorkArea} area
 * @returns {boolean}
 */
export function isInsideWorkArea(position, size, area) {
  return (
    position.x >= area.x &&
    position.y >= area.y &&
    position.x + size.width <= area.x + area.width &&
    position.y + size.height <= area.y + area.height
  );
}

/**
 * Pick the work area that should receive the window.
 *
 * Preference order: the monitor the window is already on, then the primary
 * monitor, then the first available.  A window whose monitor disappeared must
 * come back on a monitor that exists.
 *
 * @param {{ x: number, y: number }} position
 * @param {{ width: number, height: number }} size
 * @param {WorkArea[]} areas
 * @param {WorkArea|null} primary
 * @returns {WorkArea|null}
 */
export function chooseWorkArea(position, size, areas, primary = null) {
  if (!areas || areas.length === 0) return null;

  const containing = areas.find((area) => isInsideWorkArea(position, size, area));
  if (containing) return containing;

  // Overlapping counts when the window is larger than any monitor: the user can
  // still see it, so prefer that monitor over an unrelated one.
  const overlapping = areas.find((area) => overlaps(position, size, area));
  if (overlapping) return overlapping;

  if (primary) return primary;
  return areas[0];
}

/**
 * @param {{ x: number, y: number }} position
 * @param {{ width: number, height: number }} size
 * @param {WorkArea} area
 * @returns {boolean}
 */
export function overlaps(position, size, area) {
  return (
    position.x < area.x + area.width &&
    position.x + size.width > area.x &&
    position.y < area.y + area.height &&
    position.y + size.height > area.y
  );
}

/**
 * Decide where a window should be placed on restore, and whether that needed
 * adjustment.
 *
 * @param {{ position: {x: number, y: number}, size: {width: number, height: number} }} saved
 * @param {WorkArea[]} areas
 * @param {WorkArea|null} primary
 * @param {{ x: number, y: number }} fallback
 * @returns {{ position: {x: number, y: number}, clamped: boolean, reason: string }}
 */
export function resolveRestoredPosition(saved, areas, primary, fallback) {
  if (!saved || !saved.position || !saved.size) {
    return { position: fallback, clamped: true, reason: "no-saved-position" };
  }
  const area = chooseWorkArea(saved.position, saved.size, areas, primary);
  if (!area) {
    return { position: fallback, clamped: true, reason: "no-monitor" };
  }
  if (isInsideWorkArea(saved.position, saved.size, area)) {
    return { position: saved.position, clamped: false, reason: "restored" };
  }
  const clamped = clampToWorkArea(saved.position, saved.size, area);
  return { position: clamped, clamped: true, reason: "clamped-to-work-area" };
}

/**
 * Parse a persisted geometry record defensively.
 *
 * A settings file is user data that a previous version, a hand edit or a crash
 * may have left malformed.  A bad record must degrade to "no saved position"
 * rather than throw during startup and leave the user without a window.
 *
 * @param {unknown} raw
 * @returns {{ position: {x: number, y: number}, size: {width: number, height: number} }|null}
 */
export function parseSavedGeometry(raw) {
  if (!raw || typeof raw !== "object") return null;
  const value = /** @type {any} */ (raw);
  const { x, y, width, height } = value;
  const nums = [x, y, width, height];
  if (!nums.every((n) => typeof n === "number" && Number.isFinite(n))) return null;
  if (width <= 0 || height <= 0) return null;
  return { position: { x, y }, size: { width, height } };
}

