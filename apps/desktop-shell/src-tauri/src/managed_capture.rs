//! LVA-managed Screenpipe capture executor (v1.2.1 PR-021).
//!
//! Frozen plan L1340-1348.  This is the *Tauri side* of the privacy
//! coordinator: Core decides (PR-020) that LVA-managed reality capture must be
//! off or on, and this module carries that out against the Screenpipe instance
//! and reports what actually happened.
//!
//! Two rules decide everything here:
//!
//! * **Ownership, not observation, grants control.**  Only a process this
//!   instance spawned may be stopped (ADR-010, I04).  An Adopted instance is
//!   controllable only when a capability probe proves a cooperative control
//!   channel; External and Unknown are reported, never killed (L1345, L1348).
//! * **Never report a state the instance did not reach.**  A failed stop is
//!   `Failed`, an uncontrollable instance is `Uncontrollable`, and neither is
//!   dressed up as "capture is off" -- that is the false-success mode the
//!   frozen plan forbids (L1338, L1348).
//!
//! The executor is deliberately *operation-driven*: it takes an operation id
//! and an intent rather than reading the current mode itself.  Mirroring the
//! mode here would create a second authority for a decision Core already owns,
//! and the two could drift -- the same defect class as the duplicated Hub port.
use std::time::Duration;
use serde::{Deserialize, Serialize};

use crate::supervisor::{ProcessOwnership, Supervisor};

/// The service name the supervisor and the registry both use.
pub const SCREENPIPE_SERVICE: &str = "screenpipe";

/// Local Screenpipe REST surface (plan L286/L156).
pub const SCREENPIPE_REST: &str = "http://127.0.0.1:3030";

/// How long a managed pause may take before it is reported as failed.
pub const STOP_TIMEOUT: Duration = Duration::from_secs(3);

/// Whether LVA may drive this Screenpipe instance at all.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureCapability {
    /// A probe proved a cooperative control channel (Adopted instances only).
    Controllable,
    /// The instance exists, but no control channel was proven.
    Uncontrollable,
    /// No probe result: reachability/identity could not be established.
    Unknown,
}

/// What Core asked the executor to do (plan L1345: pause / stop / resume).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureIntent {
    /// LVA-managed reality capture must be off.
    Stop,
    /// LVA-managed reality capture must be running.
    Resume,
}

/// The outcome of one operation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureExecutionStatus {
    /// The requested state was reached.
    Applied,
    /// The instance exists but LVA may not control it (External / Unknown /
    /// unproven Adopted).  Reported, never forced.
    Uncontrollable,
    /// LVA does control the instance, but the attempt did not succeed.
    Failed,
}

/// The executor's answer to one operation (plan L1345: operation id ack).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptureExecutionResult {
    /// Correlates this result with the request Core issued.
    pub operation_id: String,
    pub intent: CaptureIntent,
    pub status: CaptureExecutionStatus,
    /// `Some(true)` stopped, `Some(false)` still recording, `None` unknown.
    /// `None` is the fail-closed answer: Core must not read it as success.
    pub managed_screenpipe_stopped: Option<bool>,
    /// A capture source that exists and that LVA does not control.
    pub external_screenpipe_detected: bool,
    pub error: Option<String>,
}

impl CaptureExecutionResult {
    fn uncontrollable(operation_id: &str, intent: CaptureIntent, external: bool, reason: &str) -> Self {
        Self {
            operation_id: operation_id.to_string(),
            intent,
            status: CaptureExecutionStatus::Uncontrollable,
            managed_screenpipe_stopped: None,
            external_screenpipe_detected: external,
            error: Some(reason.to_string()),
        }
    }

    fn failed(operation_id: &str, intent: CaptureIntent, reason: String) -> Self {
        Self {
            operation_id: operation_id.to_string(),
            intent,
            status: CaptureExecutionStatus::Failed,
            // A failed stop leaves the recorder running; that is not a claim of
            // success, and Core still refuses to verify the scope from it.
            managed_screenpipe_stopped: Some(false),
            external_screenpipe_detected: false,
            error: Some(reason),
        }
    }
}
/// A capability probe result for one instance.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CaptureProbe {
    pub reachable: bool,
    pub version_known: bool,
}

impl CaptureProbe {
    pub fn unknown() -> Self {
        Self { reachable: false, version_known: false }
    }

    /// A proven control channel needs a reachable REST surface *and* a version
    /// the executor was written against (plan L1709: a schema change must stop
    /// the adapter rather than let it guess).
    pub fn controllable(&self) -> bool {
        self.reachable && self.version_known
    }
}

/// Starts the managed instance again.  Injected by the owner (lib.rs) because
/// spawning is a `ProcessManager` capability and the executor must not grow a
/// second spawn path of its own -- that duplication is what R25 removed for the
/// Hub port.
pub type CaptureSpawner = std::sync::Arc<dyn Fn() -> Result<(), String> + Send + Sync>;

pub struct ManagedCaptureExecutor {
    supervisor: Supervisor,
    spawner: Option<CaptureSpawner>,
    /// Whether *this* executor terminated the managed instance.  `stop_spawned`
    /// drops the ownership entry once the handle is consumed, so afterwards the
    /// supervisor reports `Unknown` -- which is also what a never-seen instance
    /// reports.  Without this flag a resume could not tell "we stopped it, bring
    /// it back" from "no such instance, do not invent one".
    stopped_by_us: std::sync::Mutex<bool>,
    /// The most recent result, kept so the shell can show what actually happened
    /// without polling.  `None` until an operation has run.
    last_result: std::sync::Mutex<Option<CaptureExecutionResult>>,
}

impl ManagedCaptureExecutor {
    pub fn new(supervisor: Supervisor) -> Self {
        Self {
            supervisor,
            spawner: None,
            stopped_by_us: std::sync::Mutex::new(false),
            last_result: std::sync::Mutex::new(None),
        }
    }

    /// Same, with the owner-supplied way to start the instance again.
    pub fn with_spawner(supervisor: Supervisor, spawner: CaptureSpawner) -> Self {
        Self {
            supervisor,
            spawner: Some(spawner),
            stopped_by_us: std::sync::Mutex::new(false),
            last_result: std::sync::Mutex::new(None),
        }
    }

    /// The last operation result, if any.
    pub fn last_result(&self) -> Option<CaptureExecutionResult> {
        self.last_result.lock().unwrap().clone()
    }

    /// Can LVA drive the current instance, and may it kill it?
    ///
    /// Spawned is controllable by construction (LVA started it).  Adopted needs
    /// a proven control channel.  External and Unknown never become controllable:
    /// LVA reports them instead (L1343, L1345).
    pub fn capability(&self, probe: &CaptureProbe) -> CaptureCapability {
        // An instance *this executor terminated* stays LVA's own: `stop_spawned`
        // drops the ownership entry once the handle is consumed, so without this
        // the supervisor would report `Unknown` and LVA could never bring back a
        // recorder it stopped itself.
        if *self.stopped_by_us.lock().unwrap() {
            return CaptureCapability::Controllable;
        }
        match self.supervisor.get_ownership(SCREENPIPE_SERVICE) {
            ProcessOwnership::Spawned => CaptureCapability::Controllable,
            ProcessOwnership::Adopted => {
                if probe.controllable() {
                    CaptureCapability::Controllable
                } else {
                    CaptureCapability::Uncontrollable
                }
            }
            ProcessOwnership::External => CaptureCapability::Uncontrollable,
            ProcessOwnership::Unknown => CaptureCapability::Unknown,
        }
    }

    /// Execute one operation.  `operation_id` comes from Core and is echoed back
    /// unchanged so the ack can be correlated (L1345).
    pub fn execute(&self, operation_id: &str, intent: CaptureIntent, probe: &CaptureProbe) -> CaptureExecutionResult {
        let result = self.execute_inner(operation_id, intent, probe);
        *self.last_result.lock().unwrap() = Some(result.clone());
        result
    }

    fn execute_inner(&self, operation_id: &str, intent: CaptureIntent, probe: &CaptureProbe) -> CaptureExecutionResult {
        let ownership = self.supervisor.get_ownership(SCREENPIPE_SERVICE);
        match self.capability(probe) {
            CaptureCapability::Controllable => self.execute_controlled(operation_id, intent, ownership),
            CaptureCapability::Uncontrollable => CaptureExecutionResult::uncontrollable(
                operation_id,
                intent,
                true,
                "the Screenpipe instance is not LVA-controlled; it is reported, never forced",
            ),
            CaptureCapability::Unknown => CaptureExecutionResult::uncontrollable(
                operation_id,
                intent,
                false,
                "no Screenpipe instance was identified; capture state is unknown",
            ),
        }
    }

    fn execute_controlled(
        &self,
        operation_id: &str,
        intent: CaptureIntent,
        ownership: ProcessOwnership,
    ) -> CaptureExecutionResult {
        match intent {
            CaptureIntent::Stop => match self.supervisor.stop_spawned(SCREENPIPE_SERVICE, STOP_TIMEOUT) {
                Ok(true) => {
                    *self.stopped_by_us.lock().unwrap() = true;
                    CaptureExecutionResult {
                        operation_id: operation_id.to_string(),
                        intent,
                        status: CaptureExecutionStatus::Applied,
                        managed_screenpipe_stopped: Some(true),
                        external_screenpipe_detected: false,
                        error: None,
                    }
                }
                Ok(false) => {
                    // Nothing was stopped.  An Adopted instance reached this branch
                    // only with a proven control channel, so the honest report is a
                    // failure -- never "capture is off".
                    if ownership == ProcessOwnership::Spawned {
                        CaptureExecutionResult::failed(
                            operation_id,
                            intent,
                            "the spawned Screenpipe handle could not be terminated".to_string(),
                        )
                    } else {
                        CaptureExecutionResult::uncontrollable(
                            operation_id,
                            intent,
                            false,
                            "the Adopted Screenpipe instance did not accept a stop request",
                        )
                    }
                }
                Err(e) => CaptureExecutionResult::failed(operation_id, intent, e),
            },
            CaptureIntent::Resume => {
                // Resuming is only ever *our* instance coming back.  An instance
                // LVA never stopped is left alone (L1348: never take over, never
                // auto-start someone else's recorder).
                let we_stopped_it = *self.stopped_by_us.lock().unwrap();
                if !we_stopped_it {
                    // Nothing was stopped by LVA, so either it is already running or
                    // it was never ours.  Both are "no action needed", not a restart.
                    return CaptureExecutionResult {
                        operation_id: operation_id.to_string(),
                        intent,
                        status: CaptureExecutionStatus::Applied,
                        managed_screenpipe_stopped: Some(false),
                        external_screenpipe_detected: false,
                        error: None,
                    };
                }
                let Some(spawner) = self.spawner.as_ref() else {
                    // We stopped it and cannot start it again.  Reporting success
                    // here would claim a running recorder that does not exist.
                    return CaptureExecutionResult::failed(
                        operation_id,
                        intent,
                        "the managed instance was stopped by LVA but no spawner is wired"
                            .to_string(),
                    );
                };
                match spawner() {
                    Ok(()) => {
                        *self.stopped_by_us.lock().unwrap() = false;
                        CaptureExecutionResult {
                            operation_id: operation_id.to_string(),
                            intent,
                            status: CaptureExecutionStatus::Applied,
                            managed_screenpipe_stopped: Some(false),
                            external_screenpipe_detected: false,
                            error: None,
                        }
                    }
                    Err(e) => CaptureExecutionResult::failed(operation_id, intent, e),
                }
            }
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::process::{Child, Command, Stdio};

    fn spawn_sentinel() -> Child {
        Command::new("ping.exe")
            .args(["-n", "20", "127.0.0.1"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("failed to spawn ping.exe sentinel")
    }

    fn pid_is_alive(pid: u32) -> bool {
        let pid = sysinfo::Pid::from_u32(pid);
        let mut sys = sysinfo::System::new();
        sys.refresh_processes(sysinfo::ProcessesToUpdate::Some(&[pid]), true);
        sys.process(pid).is_some()
    }

    fn reap(child: Option<Child>) {
        if let Some(mut child) = child {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    fn take_handle(sup: &Supervisor, name: &str) -> Option<Child> {
        sup.take_child_for_test(name)
    }

    fn proven() -> CaptureProbe {
        CaptureProbe { reachable: true, version_known: true }
    }

    // ------------------------------------------------------------ capability
    #[test]
    fn an_unknown_instance_is_never_controllable() {
        let sup = Supervisor::new();
        let exec = ManagedCaptureExecutor::new(sup);
        assert_eq!(exec.capability(&proven()), CaptureCapability::Unknown);
    }

    #[test]
    fn an_external_instance_is_never_controllable_even_when_reachable() {
        let sup = Supervisor::new();
        sup.register_external(SCREENPIPE_SERVICE);
        let exec = ManagedCaptureExecutor::new(sup);
        assert_eq!(exec.capability(&proven()), CaptureCapability::Uncontrollable);
    }

    #[test]
    fn an_adopted_instance_needs_a_proven_control_channel() {
        let sup = Supervisor::new();
        sup.register_adopted(SCREENPIPE_SERVICE);
        let exec = ManagedCaptureExecutor::new(sup);
        assert_eq!(exec.capability(&CaptureProbe::unknown()), CaptureCapability::Uncontrollable);
        assert_eq!(
            exec.capability(&CaptureProbe { reachable: true, version_known: false }),
            CaptureCapability::Uncontrollable,
            "an unknown version must stop the adapter rather than let it guess"
        );
        assert_eq!(exec.capability(&proven()), CaptureCapability::Controllable);
    }

    #[test]
    fn a_spawned_instance_is_controllable_without_a_probe() {
        let sup = Supervisor::new();
        let child = spawn_sentinel();
        sup.register_spawned(SCREENPIPE_SERVICE, child);
        let exec = ManagedCaptureExecutor::new(sup.clone());
        assert_eq!(exec.capability(&CaptureProbe::unknown()), CaptureCapability::Controllable);
        reap(take_handle(&sup, SCREENPIPE_SERVICE));
    }

    // ------------------------------------------------------------- execution
    #[test]
    fn a_spawned_instance_is_actually_stopped_and_acknowledged() {
        let sup = Supervisor::new();
        let child = spawn_sentinel();
        let pid = child.id();
        sup.register_spawned(SCREENPIPE_SERVICE, child);
        let exec = ManagedCaptureExecutor::new(sup);

        let result = exec.execute("cap-1", CaptureIntent::Stop, &CaptureProbe::unknown());

        assert_eq!(result.operation_id, "cap-1", "the ack must echo Core's operation id");
        assert_eq!(result.status, CaptureExecutionStatus::Applied);
        assert_eq!(result.managed_screenpipe_stopped, Some(true));
        assert!(!pid_is_alive(pid), "a Spawned instance must really be stopped");
        assert!(result.error.is_none());
    }

    #[test]
    fn an_external_instance_is_reported_never_stopped() {
        let sup = Supervisor::new();
        sup.register_external(SCREENPIPE_SERVICE);
        let exec = ManagedCaptureExecutor::new(sup);

        let result = exec.execute("cap-2", CaptureIntent::Stop, &proven());

        assert_eq!(result.status, CaptureExecutionStatus::Uncontrollable);
        assert!(result.external_screenpipe_detected, "the external source must be surfaced");
        assert_eq!(
            result.managed_screenpipe_stopped, None,
            "an uncontrollable source must not be reported as stopped"
        );
        assert!(result.error.is_some(), "the reason must be visible to the caller");
    }

    #[test]
    fn an_unknown_instance_reports_unknown_rather_than_success() {
        let sup = Supervisor::new();
        let exec = ManagedCaptureExecutor::new(sup);

        let result = exec.execute("cap-3", CaptureIntent::Stop, &CaptureProbe::unknown());

        assert_eq!(result.status, CaptureExecutionStatus::Uncontrollable);
        assert!(
            !result.external_screenpipe_detected,
            "no instance was identified, so there is nothing to report as external"
        );
        assert_eq!(result.managed_screenpipe_stopped, None, "unknown is not success");
    }

    #[test]
    fn an_unproven_adopted_instance_is_not_reported_as_stopped() {
        let sup = Supervisor::new();
        sup.register_adopted(SCREENPIPE_SERVICE);
        let exec = ManagedCaptureExecutor::new(sup);

        let result = exec.execute("cap-4", CaptureIntent::Stop, &CaptureProbe::unknown());

        assert_eq!(result.status, CaptureExecutionStatus::Uncontrollable);
        assert_eq!(result.managed_screenpipe_stopped, None);
    }

    #[test]
    fn a_stopped_spawned_instance_can_be_resumed_without_spawning() {
        let sup = Supervisor::new();
        let child = spawn_sentinel();
        sup.register_spawned(SCREENPIPE_SERVICE, child);
        let started = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let counter = started.clone();
        let exec = ManagedCaptureExecutor::with_spawner(
            sup,
            std::sync::Arc::new(move || {
                counter.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                Ok(())
            }),
        );

        assert_eq!(
            exec.execute("cap-5", CaptureIntent::Stop, &CaptureProbe::unknown()).status,
            CaptureExecutionStatus::Applied
        );
        let resumed = exec.execute("cap-6", CaptureIntent::Resume, &CaptureProbe::unknown());

        assert_eq!(resumed.status, CaptureExecutionStatus::Applied);
        assert_eq!(resumed.managed_screenpipe_stopped, Some(false));
        assert_eq!(
            started.load(std::sync::atomic::Ordering::SeqCst),
            1,
            "resuming an instance LVA stopped must actually start it again"
        );
    }

    #[test]
    fn resuming_an_instance_lva_never_stopped_starts_nothing() {
        // A running recorder must not be re-spawned, and an instance that was never
        // ours must not be taken over (L1348).
        let sup = Supervisor::new();
        sup.register_adopted(SCREENPIPE_SERVICE);
        let started = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let counter = started.clone();
        let exec = ManagedCaptureExecutor::with_spawner(
            sup,
            std::sync::Arc::new(move || {
                counter.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                Ok(())
            }),
        );

        let result = exec.execute("cap-7", CaptureIntent::Resume, &proven());

        assert_eq!(result.status, CaptureExecutionStatus::Applied);
        assert_eq!(
            started.load(std::sync::atomic::Ordering::SeqCst),
            0,
            "LVA must not start a recorder it does not manage"
        );
    }

    #[test]
    fn a_resume_without_a_spawner_is_a_failure_not_a_false_success() {
        let sup = Supervisor::new();
        let child = spawn_sentinel();
        sup.register_spawned(SCREENPIPE_SERVICE, child);
        let exec = ManagedCaptureExecutor::new(sup);

        assert_eq!(
            exec.execute("cap-8", CaptureIntent::Stop, &CaptureProbe::unknown()).status,
            CaptureExecutionStatus::Applied
        );
        let resumed = exec.execute("cap-9", CaptureIntent::Resume, &CaptureProbe::unknown());

        assert_eq!(resumed.status, CaptureExecutionStatus::Failed);
        assert!(
            resumed.error.is_some(),
            "the caller must learn that the recorder was not brought back"
        );
    }

    #[test]
    fn an_operation_id_is_never_invented_by_the_executor() {
        // Core owns operation identity; the executor only echoes it back.  If the
        // executor minted ids, an ack could be correlated to the wrong request.
        let sup = Supervisor::new();
        let exec = ManagedCaptureExecutor::new(sup);
        for id in ["", "cap-abc", "opaque-id-42"] {
            let result = exec.execute(id, CaptureIntent::Stop, &CaptureProbe::unknown());
            assert_eq!(result.operation_id, id);
        }
    }
}
