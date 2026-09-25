use std::collections::HashMap;
use std::process::Child;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessOwnership {
    Spawned,
    Adopted,
    External,
    Unknown,
}

/// Spawned-only process supervisor.
///
/// Tenet (ADR-010 & Part 3.2):
/// - Spawned: Current Tauri instance holds Child handle. Graceful stop -> bounded wait -> kill that handle.
/// - Adopted / External: Observed only. Never killed by LVA.
/// - Unknown: Never killed.
/// - Absolutely NO taskkill by process name or port guessing.
#[derive(Clone)]
pub struct Supervisor {
    children: Arc<Mutex<HashMap<String, Child>>>,
    ownership: Arc<Mutex<HashMap<String, ProcessOwnership>>>,
}

impl Supervisor {
    pub fn new() -> Self {
        Self {
            children: Arc::new(Mutex::new(HashMap::new())),
            ownership: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub fn register_spawned(&self, name: &str, child: Child) {
        let mut children = self.children.lock().unwrap();
        let mut ownership = self.ownership.lock().unwrap();
        children.insert(name.to_string(), child);
        ownership.insert(name.to_string(), ProcessOwnership::Spawned);
        log::info!("[Supervisor] Registered SPAWNED child: {}", name);
    }

    pub fn register_adopted(&self, name: &str) {
        let mut ownership = self.ownership.lock().unwrap();
        ownership.insert(name.to_string(), ProcessOwnership::Adopted);
        log::info!("[Supervisor] Registered ADOPTED process: {}", name);
    }

    pub fn register_external(&self, name: &str) {
        let mut ownership = self.ownership.lock().unwrap();
        ownership.insert(name.to_string(), ProcessOwnership::External);
        log::info!("[Supervisor] Registered EXTERNAL process: {}", name);
    }

    pub fn get_ownership(&self, name: &str) -> ProcessOwnership {
        let ownership = self.ownership.lock().unwrap();
        ownership.get(name).copied().unwrap_or(ProcessOwnership::Unknown)
    }

    /// Stop only a Spawned child whose handle is held by this supervisor.
    /// External, Adopted, and Unknown processes are strictly ignored and never killed.
    pub fn stop_spawned(&self, name: &str, timeout: Duration) -> Result<bool, String> {
        let mut children = self.children.lock().unwrap();
        let mut ownership = self.ownership.lock().unwrap();

        // Ownership is authoritative. A handle may be held for a process that this
        // instance merely discovered (Adopted/External); those are never terminated.
        if ownership.get(name) != Some(&ProcessOwnership::Spawned) {
            log::debug!("[Supervisor] '{}' is not owned as Spawned; skipping stop", name);
            return Ok(false);
        }

        if let Some(mut child) = children.remove(name) {
            log::info!("[Supervisor] Stopping spawned child handle: {}", name);
            // On Windows, child.kill() terminates the specific process handle
            let _ = child.kill();
            let start = Instant::now();
            while start.elapsed() < timeout {
                match child.try_wait() {
                    Ok(Some(_)) => {
                        ownership.remove(name);
                        log::info!("[Supervisor] Successfully terminated spawned child: {}", name);
                        return Ok(true);
                    }
                    Ok(None) => std::thread::sleep(Duration::from_millis(50)),
                    Err(e) => {
                        ownership.remove(name);
                        return Err(format!("Error waiting for child {}: {}", name, e));
                    }
                }
            }
            ownership.remove(name);
            Ok(true)
        } else {
            log::debug!("[Supervisor] '{}' is not a spawned child; skipping stop", name);
            Ok(false)
        }
    }

    /// Stop all Spawned child processes upon desktop shutdown.
    pub fn stop_all_spawned(&self, timeout: Duration) {
        let names: Vec<String> = {
            let children = self.children.lock().unwrap();
            children.keys().cloned().collect()
        };

        for name in names {
            let _ = self.stop_spawned(&name, timeout);
        }
    }

    /// Reclaim a held child handle without killing through it.
    ///
    /// Test-only: the managed-capture suite must be able to register a live
    /// sentinel as Spawned, exercise a real stop, and then clean up the sentinels
    /// whose handles the stop path deliberately consumed.  Production code never
    /// needs to take a handle back -- ownership is the only thing it consults.
    #[cfg(test)]
    pub fn take_child_for_test(&self, name: &str) -> Option<Child> {
        self.children.lock().unwrap().remove(name)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::process::{Child, Command, Stdio};

    /// Long-lived sentinel: cmd.exe reads its command stream from stdin, so with a
    /// piped and never-closed stdin it stays alive until it is explicitly killed. It
    /// stands in for an external process (Hub, Python service, occupied-port process).
    fn spawn_sentinel() -> Child {
        // cmd.exe was rejected as a sentinel: it exits as soon as its stdin pipe
        // reaches EOF, so dropping a Child handle would look like a kill. ping.exe
        // ignores stdin, so it lives until it is killed or its count runs out. The
        // count is bounded so a sentinel left in place by a failing assertion still
        // exits on its own rather than leaking for the rest of the session.
        Command::new("ping.exe")
            .args(["-n", "20", "127.0.0.1"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("failed to spawn ping.exe sentinel")
    }

    /// Liveness probe that does not go through the supervisor handle: the PID must
    /// still be present in the process table.
    fn pid_is_alive(pid: u32) -> bool {
        let pid = sysinfo::Pid::from_u32(pid);
        let mut sys = sysinfo::System::new();
        sys.refresh_processes(sysinfo::ProcessesToUpdate::Some(&[pid]), true);
        sys.process(pid).is_some()
    }

    /// Reclaim a handle the supervisor holds without killing through it, so that a
    /// deliberately surviving sentinel can be cleaned up at the end of a test.
    fn take_handle(sup: &Supervisor, name: &str) -> Option<Child> {
        sup.children.lock().unwrap().remove(name)
    }

    fn reap(child: Option<Child>) {
        if let Some(mut child) = child {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    #[test]
    fn unknown_names_are_never_owned() {
        let sup = Supervisor::new();
        assert_eq!(sup.get_ownership("screenpipe"), ProcessOwnership::Unknown);
        assert_eq!(sup.get_ownership("llama.cpp-hub"), ProcessOwnership::Unknown);
        // An unknown name holds no child handle, so stopping it is a no-op success.
        assert_eq!(
            sup.stop_spawned("screenpipe", Duration::from_millis(50)),
            Ok(false)
        );
    }

    #[test]
    fn registration_records_ownership() {
        let sup = Supervisor::new();
        sup.register_adopted("screenpipe");
        sup.register_external("llama.cpp-hub");
        assert_eq!(sup.get_ownership("screenpipe"), ProcessOwnership::Adopted);
        assert_eq!(sup.get_ownership("llama.cpp-hub"), ProcessOwnership::External);
    }

    #[test]
    fn stop_spawned_terminates_the_owned_child_only() {
        let sup = Supervisor::new();
        let child = spawn_sentinel();
        let pid = child.id();
        sup.register_spawned("lva_core", child);

        assert!(pid_is_alive(pid), "sentinel must be alive before stop");
        assert_eq!(
            sup.stop_spawned("lva_core", Duration::from_secs(5)),
            Ok(true)
        );
        assert!(!pid_is_alive(pid), "a Spawned child must be terminated");
        assert_eq!(sup.get_ownership("lva_core"), ProcessOwnership::Unknown);
        // The handle was consumed by the stop, so a repeat stop kills nothing.
        assert_eq!(
            sup.stop_spawned("lva_core", Duration::from_millis(50)),
            Ok(false)
        );
    }

    #[test]
    fn adopted_and_external_handles_survive_every_stop_path() {
        let sup = Supervisor::new();
        let adopted = spawn_sentinel();
        let external = spawn_sentinel();
        let (adopted_pid, external_pid) = (adopted.id(), external.id());

        // A handle may be held while ownership stays Adopted/External: the process was
        // discovered rather than started by this instance. Both must be left alone.
        sup.register_spawned("adopted_proc", adopted);
        sup.register_adopted("adopted_proc");
        sup.register_spawned("external_proc", external);
        sup.register_external("external_proc");

        assert_eq!(
            sup.stop_spawned("adopted_proc", Duration::from_millis(100)),
            Ok(false)
        );
        assert_eq!(
            sup.stop_spawned("external_proc", Duration::from_millis(100)),
            Ok(false)
        );
        assert!(pid_is_alive(adopted_pid), "Adopted process must never be killed");
        assert!(pid_is_alive(external_pid), "External process must never be killed");

        sup.stop_all_spawned(Duration::from_millis(100));
        assert!(pid_is_alive(adopted_pid), "stop_all_spawned must skip Adopted");
        assert!(pid_is_alive(external_pid), "stop_all_spawned must skip External");
        assert_eq!(sup.get_ownership("adopted_proc"), ProcessOwnership::Adopted);
        assert_eq!(sup.get_ownership("external_proc"), ProcessOwnership::External);

        // The supervisor never killed them, so the test reclaims both handles.
        reap(take_handle(&sup, "adopted_proc"));
        reap(take_handle(&sup, "external_proc"));
    }

    #[test]
    fn stop_all_spawned_kills_only_spawned_entries() {
        let sup = Supervisor::new();
        let owned = spawn_sentinel();
        let owned_pid = owned.id();
        let adopted = spawn_sentinel();
        let adopted_pid = adopted.id();

        sup.register_spawned("lva_core", owned);
        sup.register_spawned("adopted_proc", adopted);
        sup.register_adopted("adopted_proc");

        sup.stop_all_spawned(Duration::from_secs(5));

        assert!(!pid_is_alive(owned_pid), "Spawned child must be terminated");
        assert!(pid_is_alive(adopted_pid), "Adopted child must survive shutdown");
        reap(take_handle(&sup, "adopted_proc"));
    }
}
