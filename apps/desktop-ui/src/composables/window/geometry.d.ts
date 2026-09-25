import type { WorkArea } from './geometry.js';

export interface WindowPosition {
  x: number;
  y: number;
}

export interface WindowSize {
  width: number;
  height: number;
}

export interface SavedGeometry {
  position: WindowPosition;
  size: WindowSize;
}

export interface ResolvedPosition {
  position: WindowPosition;
  clamped: boolean;
  reason: string;
}

export function clampToWorkArea(
  position: WindowPosition,
  size: WindowSize,
  area: WorkArea
): WindowPosition;

export function isInsideWorkArea(
  position: WindowPosition,
  size: WindowSize,
  area: WorkArea
): boolean;

export function overlaps(
  position: WindowPosition,
  size: WindowSize,
  area: WorkArea
): boolean;

export function chooseWorkArea(
  position: WindowPosition,
  size: WindowSize,
  areas: WorkArea[],
  primary?: WorkArea | null
): WorkArea | null;

export function resolveRestoredPosition(
  saved: SavedGeometry | null,
  areas: WorkArea[],
  primary: WorkArea | null,
  fallback: WindowPosition
): ResolvedPosition;

export function parseSavedGeometry(raw: unknown): SavedGeometry | null;

export type { WorkArea };

