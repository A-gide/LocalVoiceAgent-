use std::collections::HashMap;
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex};
use std::time::{Duration, Instant};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ProcessOwnership {
    Spawned,
    Adopted,
    External,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SingleServiceInfo {
    pub name: String,
    pub port: u16,
    pub is_running: bool,
    pub pid: Option<u32>,
    pub ownership: Option<ProcessOwnership>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FullServicesStatus {
    pub llama_server: SingleServiceInfo,
    pub screenpipe: SingleServiceInfo,
    pub open_llm_vtuber: SingleServiceInfo,
    pub vram_mb_estimated: u64,
    pub is_switching_model: bool,
}

#[derive(Debug, Deserialize, Serialize)]
struct ServiceDef {
    name: String,
    port: u16,
    executable: String,
    args: Vec<String>,
    #[serde(default)]
    env: HashMap<String, String>,
    #[serde(default)]
    env_path_prepend: Vec<String>,
    #[serde(default)]
    cwd: Option<String>,
    #[serde(default)]
    health_url: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
struct ServicesConfigFile {
    services: HashMap<String, ServiceDef>,
}

#[derive(Clone)]
pub struct ProcessManager {
    config_path: PathBuf,
    spawned_children: Arc<Mutex<HashMap<String, Child>>>,
    ownership_map: Arc<Mutex<HashMap<String, ProcessOwnership>>>,
    is_switching_model: Arc<AtomicBool>,
}

impl ProcessManager {
    pub fn new() -> Self {
        let config_path = crate::paths::get_services_json_path();
        log::info!("[ProcessManager] Initialized with config: {:?}", config_path);

        let mut ownership_map = HashMap::new();
        // Probe adopted status without ownership claiming
        if Self::is_port_listening(3030) {
            ownership_map.insert("screenpipe".to_string(), ProcessOwnership::Adopted);
        }
        if Self::is_port_listening(8080) {
            ownership_map.insert("llama_server".to_string(), ProcessOwnership::Adopted);
        }

        Self {
            config_path,
            spawned_children: Arc::new(Mutex::new(HashMap::new())),
            ownership_map: Arc::new(Mutex::new(ownership_map)),
            is_switching_model: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn is_port_listening(port: u16) -> bool {
        let addr = SocketAddr::from(([127, 0, 0, 1], port));
        TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok()
    }

    pub fn get_status(&self) -> FullServicesStatus {
        let llama_up = Self::is_port_listening(8080);
        let screenpipe_up = Self::is_port_listening(3030);
        let vtuber_up = false; // OLV conversation process is removed per PR-036

        let own = self.ownership_map.lock().unwrap();
        let children = self.spawned_children.lock().unwrap();

        let screenpipe_pid = children.get("screenpipe").map(|c| c.id());

        FullServicesStatus {
            llama_server: SingleServiceInfo {
                name: "llama.cpp-hub".to_string(),
                port: 8080,
                is_running: llama_up,
                pid: None, // External/Adopted ownership: never guess PID
                ownership: own.get("llama_server").copied().or(Some(ProcessOwnership::Adopted)),
            },
            screenpipe: SingleServiceInfo {
                name: "screenpipe".to_string(),
                port: 3030,
                is_running: screenpipe_up,
                pid: screenpipe_pid,
                ownership: own.get("screenpipe").copied(),
            },
            open_llm_vtuber: SingleServiceInfo {
                name: "open-llm-vtuber".to_string(),
                port: 12393,
                is_running: vtuber_up,
                pid: None,
                ownership: None,
            },
            vram_mb_estimated: if llama_up { 4900 } else { 1200 },
            is_switching_model: self.is_switching_model.load(Ordering::SeqCst),
        }
    }

    /// Managed VRAM release: Delegates to llama.cpp-hub model stop semantics.
    /// Per Part 3.1 & 3.2 and Invariants I04 / I16:
    /// Never terminates processes by name or port.
    pub fn unload_vram(&self) -> Result<String, String> {
        Ok("Model lifecycle is managed by llama.cpp-hub. Use Hub model controls to stop loaded models.".to_string())
    }

    pub fn ensure_service_running(&self, key: &str) -> Result<f64, String> {
        if key != "screenpipe" {
            return Ok(0.0);
        }

        let port = 3030;
        if Self::is_port_listening(port) {
            return Ok(0.0);
        }

        let t0 = Instant::now();
        let content = std::fs::read_to_string(&self.config_path)
            .map_err(|e| format!("Failed to read services.json: {}", e))?;
        let cfg: ServicesConfigFile = serde_json::from_str(&content)
            .map_err(|e| format!("Failed to parse services.json: {}", e))?;

        let def = cfg.services.get(key)
            .ok_or_else(|| format!("{} not defined in services.json", key))?;

        let mut cmd = Command::new(&def.executable);
        cmd.args(&def.args);

        if let Some(cwd) = &def.cwd {
            cmd.current_dir(cwd);
        }

        for (k, v) in &def.env {
            cmd.env(k, v);
        }

        let mut path_entries = def.env_path_prepend.clone();
        if let Ok(cur_path) = std::env::var("PATH").or_else(|_| std::env::var("Path")) {
            path_entries.push(cur_path);
        }
        let full_path = path_entries.join(";");
        cmd.env("PATH", &full_path);
        cmd.env("Path", &full_path);

        cmd.stdin(std::process::Stdio::null());
        cmd.stdout(std::process::Stdio::null());
        cmd.stderr(std::process::Stdio::null());

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }

        let child = cmd.spawn()
            .map_err(|e| format!("Failed to spawn {}: {}", key, e))?;

        {
            let mut children = self.spawned_children.lock().unwrap();
            children.insert(key.to_string(), child);
            let mut own = self.ownership_map.lock().unwrap();
            own.insert(key.to_string(), ProcessOwnership::Spawned);
        }

        let deadline = Instant::now() + Duration::from_secs(15);
        while Instant::now() < deadline {
            if Self::is_port_listening(port) {
                return Ok(t0.elapsed().as_secs_f64());
            }
            std::thread::sleep(Duration::from_millis(150));
        }

        Err(format!("Service {} failed to respond on port {} within 15s", key, port))
    }

    pub fn cold_start_llm(&self) -> Result<f64, String> {
        Ok(0.0)
    }

    pub fn switch_model(&self, _new_model_path: &str) -> Result<f64, String> {
        Ok(0.0)
    }

    /// Safe shutdown: strictly terminates ONLY child processes spawned by this instance
    /// and held in `spawned_children`.
    /// Per Invariants I04 and I16:
    /// Adopted, External, and Unknown processes (including llama.cpp-hub and its children)
    /// are NEVER killed or guessed by port/name.
    pub fn safe_shutdown_spawned_only(&self) {
        let own = self.ownership_map.lock().unwrap();
        let mut children = self.spawned_children.lock().unwrap();

        for (name, child) in children.iter_mut() {
            if own.get(name) == Some(&ProcessOwnership::Spawned) {
                log::info!("[ProcessManager] Gracefully terminating spawned child handle: {}", name);
                let _ = child.kill();
            }
        }
        children.clear();
    }

    pub fn shutdown_all_services(&self) {
        self.safe_shutdown_spawned_only();
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::process::Stdio;

    /// Long-lived sentinel: cmd.exe reads its command stream from stdin, so with a
    /// piped and never-closed stdin it stays alive until it is explicitly killed. It
    /// stands in for an external process (Hub, Python service, occupied-port process).
    fn spawn_sentinel() -> Child {
        // cmd.exe was rejected as a sentinel: it exits as soon as its stdin pipe
        // reaches EOF, so dropping a Child handle would look like a kill. ping.exe
        // ignores stdin, so it lives until it is killed or its count runs out. The
        // count is bounded on purpose: shutdown paths clear the child registry, which
        // can put a surviving sentinel's handle out of reach, and a bounded ping still
        // goes away on its own instead of leaking for the rest of the session.
        Command::new("ping.exe")
            .args(["-n", "20", "127.0.0.1"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("failed to spawn ping.exe sentinel")
    }

    /// Liveness probe that does not go through a Child handle: the PID must still be
    /// present in the process table.
    fn pid_is_alive(pid: u32) -> bool {
        let pid = sysinfo::Pid::from_u32(pid);
        let mut sys = sysinfo::System::new();
        sys.refresh_processes(sysinfo::ProcessesToUpdate::Some(&[pid]), true);
        sys.process(pid).is_some()
    }

    /// Termination is asynchronous on Windows, so a killed PID may linger briefly.
    fn wait_until_dead(pid: u32, timeout: Duration) -> bool {
        let deadline = Instant::now() + timeout;
        loop {
            if !pid_is_alive(pid) {
                return true;
            }
            if Instant::now() >= deadline {
                return false;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }

    fn reap(child: Option<Child>) {
        if let Some(mut child) = child {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    /// Register a live sentinel as Spawned, exactly as ensure_service_running would.
    fn register_spawned_sentinel(pm: &ProcessManager, name: &str) -> u32 {
        let child = spawn_sentinel();
        let pid = child.id();
        pm.spawned_children.lock().unwrap().insert(name.to_string(), child);
        pm.ownership_map
            .lock()
            .unwrap()
            .insert(name.to_string(), ProcessOwnership::Spawned);
        pid
    }

    /// Downgrade a registry entry to Adopted: the process is now observed, not owned.
    fn mark_adopted(pm: &ProcessManager, name: &str) {
        pm.ownership_map
            .lock()
            .unwrap()
            .insert(name.to_string(), ProcessOwnership::Adopted);
    }

    #[test]
    fn new_never_claims_spawned_ownership() {
        // Port discovery may register Adopted entries; it must never claim a process
        // this instance did not start (I04/I16).
        let pm = ProcessManager::new();
        assert!(pm.spawned_children.lock().unwrap().is_empty());
        for (name, ownership) in pm.ownership_map.lock().unwrap().iter() {
            assert_ne!(
                *ownership,
                ProcessOwnership::Spawned,
                "{} must not be claimed as Spawned",
                name
            );
        }
    }

    #[test]
    fn status_never_guesses_a_pid_for_the_hub() {
        let pm = ProcessManager::new();
        let status = pm.get_status();
        assert_eq!(status.llama_server.port, 8080);
        assert!(status.llama_server.pid.is_none(), "Hub PID must never be guessed");
        assert_eq!(status.llama_server.ownership, Some(ProcessOwnership::Adopted));
        assert!(status.open_llm_vtuber.pid.is_none());
        assert!(!status.open_llm_vtuber.is_running);
    }

    #[test]
    fn ensure_service_running_ignores_keys_it_does_not_own() {
        let pm = ProcessManager::new();
        assert_eq!(pm.ensure_service_running("llama_server"), Ok(0.0));
        assert_eq!(pm.ensure_service_running("open_llm_vtuber"), Ok(0.0));
        assert!(pm.spawned_children.lock().unwrap().is_empty());
    }

    #[test]
    fn shutdown_skips_adopted_and_unregistered_processes() {
        let pm = ProcessManager::new();
        let adopted_pid = register_spawned_sentinel(&pm, "screenpipe");
        mark_adopted(&pm, "screenpipe");
        // A process this instance never started and never registered.
        let external = spawn_sentinel();
        let external_pid = external.id();

        pm.safe_shutdown_spawned_only();

        assert!(pid_is_alive(adopted_pid), "Adopted process must survive shutdown");
        assert!(pid_is_alive(external_pid), "Unregistered process must survive shutdown");
        // Ownership is not rewritten by shutdown: the entry is still known Adopted.
        assert_eq!(
            pm.ownership_map.lock().unwrap().get("screenpipe").copied(),
            Some(ProcessOwnership::Adopted)
        );

        // safe_shutdown_spawned_only clears the whole child registry, so the handle for
        // the adopted sentinel is no longer reachable. It is a self-terminating ping,
        // so it still goes away on its own; only the locally held handle is reaped here.
        reap(Some(external));
        assert!(wait_until_dead(external_pid, Duration::from_secs(10)));
    }

    #[test]
    fn shutdown_kills_only_spawned_entries() {
        let pm = ProcessManager::new();
        let owned_pid = register_spawned_sentinel(&pm, "lva_core");
        let adopted_pid = register_spawned_sentinel(&pm, "screenpipe");
        mark_adopted(&pm, "screenpipe");

        pm.safe_shutdown_spawned_only();

        assert!(
            wait_until_dead(owned_pid, Duration::from_secs(5)),
            "Spawned child must be terminated"
        );
        assert!(pid_is_alive(adopted_pid), "Adopted child must survive shutdown");
        // The registry was cleared, so this sentinel is left to its own bounded exit.
    }
}
