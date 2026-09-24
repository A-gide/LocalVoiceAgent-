export type Revisions = Record<string, number>;

export interface ReconcilableState {
  mode?: string;
  snapshot_version?: number;
  runtime_control_revision?: number;
  hub_binding_revision?: number;
}

export interface CommandLike {
  status: string;
  snapshot_version?: number;
  revisions?: Revisions;
  error?: { code?: string; message?: string } | null;
}

export interface ReconcileResult {
  mode: string;
  snapshot_version: number;
  runtime_control_revision: number;
  hub_binding_revision: number;
  rolledBack: boolean;
  source: 'applied' | 'refreshed' | 'rollback';
}

export function foldRevisions<T extends ReconcilableState>(state: T, result: CommandLike): T;

export function reconcileSetMode(args: {
  state: ReconcilableState;
  prevMode: string;
  result: CommandLike;
  refreshed?: ReconcilableState | null;
}): ReconcileResult;