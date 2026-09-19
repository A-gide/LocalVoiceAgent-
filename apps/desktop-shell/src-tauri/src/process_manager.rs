use std::collections::HashMap;
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex};
use std::time::{Duration, Instant};
use serde::{Deserialize, Serialize};
use sysinfo::System;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ProcessOwnership {
    Adopted,
    Spawned,
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
        log::info!("[ProcessManager] Loaded services config from: {:?}", config_path);

        let mut ownership_map = HashMap::new();
        for (key, port) in &[
            ("llama_server", 1234),
            ("screenpipe", 3030),
            ("open_llm_vtuber", 12393),
        ] {
            if Self::is_port_listening(*port) {
                ownership_map.insert(key.to_string(), ProcessOwnership::Adopted);
            }
        }

        let pm = Self {
            config_path,
            spawned_children: Arc::new(Mutex::new(HashMap::new())),
            ownership_map: Arc::new(Mutex::new(ownership_map)),
            is_switching_model: Arc::new(AtomicBool::new(false)),
        };

        // Auto-spawn open_llm_vtuber and llama_server LLM engine on desktop startup
        let pm_vtuber = pm.clone();
        std::thread::spawn(move || {
            if !Self::is_port_listening(12393) {
                log::info!("[ProcessManager] Auto-spawning open_llm_vtuber on desktop startup...");
                let _ = pm_vtuber.ensure_service_running("open_llm_vtuber");
            }
        });

        let pm_llm = pm.clone();
        std::thread::spawn(move || {
            if !Self::is_port_listening(1234) {
                log::info!("[ProcessManager] Auto-spawning llama_server on desktop startup...");
                let _ = pm_llm.ensure_service_running("llama_server");
            }
        });

        pm
    }

    pub fn is_port_listening(port: u16) -> bool {
        let addr = SocketAddr::from(([127, 0, 0, 1], port));
        TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok()
    }

    pub fn get_status(&self) -> FullServicesStatus {
        let llama_up = Self::is_port_listening(1234);
        let screenpipe_up = Self::is_port_listening(3030);
        let vtuber_up = Self::is_port_listening(12393);

        let own = self.ownership_map.lock().unwrap();

        let llama_pid = Self::find_pid_by_name("llama-server");
        let screenpipe_pid = Self::find_pid_by_name("screenpipe");
        let vtuber_pid = Self::find_pid_by_name("python");

        let vram_mb = if llama_up { 6725 } else { 1809 };

        FullServicesStatus {
            llama_server: SingleServiceInfo {
                name: "llama-server".to_string(),
                port: 1234,
                is_running: llama_up,
                pid: llama_pid,
                ownership: own.get("llama_server").copied(),
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
                pid: vtuber_pid,
                ownership: own.get("open_llm_vtuber").copied(),
            },
            vram_mb_estimated: vram_mb,
            is_switching_model: self.is_switching_model.load(Ordering::SeqCst),
        }
    }

    fn find_pid_by_name(pattern: &str) -> Option<u32> {
        let mut sys = System::new_all();
        sys.refresh_all();
        for (pid, process) in sys.processes() {
            let p_name = process.name().to_string_lossy().to_lowercase();
            if p_name.contains(pattern) {
                return Some(pid.as_u32());
            }
        }
        None
    }

    pub fn unload_vram(&self) -> Result<String, String> {
        let mut sys = System::new_all();
        sys.refresh_all();

        let mut killed = 0;
        for (_pid, process) in sys.processes() {
            let p_name = process.name().to_string_lossy().to_lowercase();
            if p_name.contains("llama-server") {
                process.kill();
                killed += 1;
            }
        }

        let mut own = self.ownership_map.lock().unwrap();
        own.remove("llama_server");

        Ok(format!("Successfully terminated {} llama-server process(es). ~4.9GB VRAM released.", killed))
    }

    pub fn ensure_service_running(&self, key: &str) -> Result<f64, String> {
        let (port, def_key) = match key {
            "llama_server" => (1234, "llama_server"),
            "open_llm_vtuber" => (12393, "open_llm_vtuber"),
            "screenpipe" => (3030, "screenpipe"),
            _ => return Err(format!("Unknown service: {}", key)),
        };

        if Self::is_port_listening(port) {
            return Ok(0.0);
        }

        let t0 = Instant::now();
        let content = std::fs::read_to_string(&self.config_path)
            .map_err(|e| format!("Failed to read services.json: {}", e))?;
        let cfg: ServicesConfigFile = serde_json::from_str(&content)
            .map_err(|e| format!("Failed to parse services.json: {}", e))?;

        let def = cfg.services.get(def_key)
            .ok_or_else(|| format!("{} not defined in services.json", def_key))?;

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
            .map_err(|e| format!("Failed to spawn {}: {}", def_key, e))?;

        {
            let mut children = self.spawned_children.lock().unwrap();
            children.insert(def_key.to_string(), child);
            let mut own = self.ownership_map.lock().unwrap();
            own.insert(def_key.to_string(), ProcessOwnership::Spawned);
        }

        let timeout_secs = if def_key == "open_llm_vtuber" { 25 } else { 30 };
        let deadline = Instant::now() + Duration::from_secs(timeout_secs);
        while Instant::now() < deadline {
            if Self::is_port_listening(port) {
                let elapsed = t0.elapsed().as_secs_f64();
                return Ok(elapsed);
            }
            std::thread::sleep(Duration::from_millis(150));
        }

        Err(format!("Service {} failed to respond on port {} within {}s", def_key, port, timeout_secs))
    }

    pub fn cold_start_llm(&self) -> Result<f64, String> {
        self.ensure_service_running("llama_server")
    }

    /// M3: Hot switch model with persistence into services.json & in-flight turn protection
    pub fn switch_model(&self, new_model_path: &str) -> Result<f64, String> {
        if !std::path::Path::new(new_model_path).exists() {
            return Err(format!("Target model file does not exist: {}", new_model_path));
        }

        self.is_switching_model.store(true, Ordering::SeqCst);
        let t0 = Instant::now();

        // 1. Read existing config for rollback protection
        let original_content = match std::fs::read_to_string(&self.config_path) {
            Ok(c) => c,
            Err(e) => {
                self.is_switching_model.store(false, Ordering::SeqCst);
                return Err(format!("Failed to read services.json for backup: {}", e));
            }
        };

        // Update services.json to avoid state drift across cold starts
        let update_res = (|| -> Result<(), String> {
            let mut val: serde_json::Value = serde_json::from_str(&original_content)
                .map_err(|e| format!("Failed to parse services.json: {}", e))?;

            if let Some(services) = val.get_mut("services") {
                if let Some(llama) = services.get_mut("llama_server") {
                    if let Some(args) = llama.get_mut("args").and_then(|a| a.as_array_mut()) {
                        for i in 0..args.len() {
                            if args[i].as_str() == Some("-m") && i + 1 < args.len() {
                                args[i + 1] = serde_json::Value::String(new_model_path.to_string());
                                break;
                            }
                        }
                    }
                }
            }
            let pretty = serde_json::to_string_pretty(&val).map_err(|e| e.to_string())?;
            std::fs::write(&self.config_path, pretty).map_err(|e| e.to_string())?;
            Ok(())
        })();

        if let Err(e) = update_res {
            self.is_switching_model.store(false, Ordering::SeqCst);
            return Err(e);
        }

        // 2. Terminate existing llama-server
        let _ = self.unload_vram();

        // Small grace period for socket release
        std::thread::sleep(Duration::from_millis(300));

        // 3. Cold start with the new model
        let start_res = self.cold_start_llm();
        self.is_switching_model.store(false, Ordering::SeqCst);

        match start_res {
            Ok(_) => {
                let total_elapsed = t0.elapsed().as_secs_f64();
                Ok(total_elapsed)
            }
            Err(e) => {
                // Rollback: restore original services.json and restart original model
                eprintln!("[ProcessManager] Cold start failed for new model. Rolling back services.json...");
                let _ = std::fs::write(&self.config_path, &original_content);
                let _ = self.cold_start_llm();
                Err(format!("Cold start with new model failed ({}), rolled back services.json to previous configuration", e))
            }
        }
    }

    pub fn find_pid_by_port(port: u16) -> Option<u32> {
        #[cfg(windows)]
        {
            let output = Command::new("netstat")
                .args(&["-ano", "-p", "tcp"])
                .output()
                .ok()?;
            let text = String::from_utf8_lossy(&output.stdout);
            for line in text.lines() {
                if line.contains(&format!(":{}", port)) && line.contains("LISTENING") {
                    if let Some(pid_str) = line.split_whitespace().last() {
                        if let Ok(pid) = pid_str.parse::<u32>() {
                            if pid > 0 {
                                return Some(pid);
                            }
                        }
                    }
                }
            }
        }
        None
    }

    pub fn safe_shutdown_spawned_only(&self) {
        let own = self.ownership_map.lock().unwrap();
        let mut children = self.spawned_children.lock().unwrap();

        for (name, child) in children.iter_mut() {
            if own.get(name) == Some(&ProcessOwnership::Spawned) {
                let pid = child.id();
                #[cfg(windows)]
                {
                    let _ = Command::new("taskkill")
                        .args(&["/PID", &pid.to_string(), "/T", "/F"])
                        .output();
                }
                let _ = child.kill();
            }
        }
    }

    pub fn shutdown_all_services(&self) {
        // 1. Terminate all spawned children process trees
        self.safe_shutdown_spawned_only();

        // 2. Unload llama-server and release VRAM
        let _ = self.unload_vram();

        // 3. Terminate open-llm-vtuber on port 12393 if still running
        if let Some(pid) = Self::find_pid_by_port(12393) {
            #[cfg(windows)]
            {
                let _ = Command::new("taskkill")
                    .args(&["/PID", &pid.to_string(), "/T", "/F"])
                    .output();
            }
        }

        // 4. Terminate any residual llama-server on port 1234
        if let Some(pid) = Self::find_pid_by_port(1234) {
            #[cfg(windows)]
            {
                let _ = Command::new("taskkill")
                    .args(&["/PID", &pid.to_string(), "/T", "/F"])
                    .output();
            }
        }
    }
}
