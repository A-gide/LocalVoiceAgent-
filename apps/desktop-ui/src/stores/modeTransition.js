/**
 * Mode-transition reconciliation for the runtime store.
 *
 * Plain ESM with JSDoc types so the exact logic can be executed by Node in a
 * test, not merely string-matched in the store source.  The store imports this
 * module; the test imports the same module.
 */

/** @typedef {{ [aggregate: string]: number }} Revisions */

/**
 * Fold a command result's revision vector into the store state.
 * @param {{runtime_control_revision?: number, hub_binding_revision?: number}} state
 * @param {{revisions?: Revisions}} result
 */
export function foldRevisions(state, result) {
  const revisions = result.revisions ?? {};
  if (typeof revisions.runtime_control === 'number') {
    state.runtime_control_revision = revisions.runtime_control;
  }
  if (typeof revisions.hub_binding === 'number') {
    state.hub_binding_revision = revisions.hub_binding;
  }
  return state;
}

/**
 * Decide the store's next mode and revisions after a `setMode` attempt.
 *
 * The subtle case is a STALE_REVISION rejection followed by a snapshot
 * refresh: once the authoritative snapshot has been read, the store must keep
 * the *snapshot's* mode and revision.  Rolling back to the pre-attempt mode
 * there would silently undo a recovery that already happened.
 *
 * @param {object} args
 * @param {{mode?: string, runtime_control_revision?: number, hub_binding_revision?: number}} args.state
 * @param {string} args.prevMode
 * @param {{status: string, snapshot_version?: number, revisions?: Revisions, error?: {code?: string}}} args.result
 * @param {{mode?: string, runtime_control_revision?: number, hub_binding_revision?: number}|null} [args.refreshed]
 *        The flat RuntimeState returned by a snapshot refresh, or null when the
 *        refresh did not happen / failed.
 * @returns {{mode: string, runtime_control_revision: number, hub_binding_revision: number, rolledBack: boolean, source: string}}
 */
export function reconcileSetMode({ state, prevMode, result, refreshed = null }) {
  const snapshotVersion = state.snapshot_version ?? 0;
  const runtimeControl = state.runtime_control_revision ?? 0;
  const hubBinding = state.hub_binding_revision ?? 0;

  if (result.status === 'applied') {
    const next = { runtime_control_revision: runtimeControl, hub_binding_revision: hubBinding };
    foldRevisions(next, result);
    return {
      mode: state.mode ?? prevMode,
      snapshot_version: result.snapshot_version ?? snapshotVersion,
      runtime_control_revision: next.runtime_control_revision,
      hub_binding_revision: next.hub_binding_revision,
      rolledBack: false,
      source: 'applied',
    };
  }

  if (result.error?.code === 'STALE_REVISION' && refreshed) {
    // The authoritative snapshot wins.  Keep its mode and revision; do NOT
    // roll back to prevMode.
    return {
      mode: refreshed.mode ?? prevMode,
      snapshot_version: refreshed.snapshot_version ?? snapshotVersion,
      runtime_control_revision: refreshed.runtime_control_revision ?? runtimeControl,
      hub_binding_revision: refreshed.hub_binding_revision ?? hubBinding,
      rolledBack: false,
      source: 'refreshed',
    };
  }

  return {
    mode: prevMode,
    snapshot_version: snapshotVersion,
    runtime_control_revision: runtimeControl,
    hub_binding_revision: hubBinding,
    rolledBack: true,
    source: 'rollback',
  };
}