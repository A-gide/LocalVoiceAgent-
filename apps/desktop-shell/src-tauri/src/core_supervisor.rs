use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::supervisor::Supervisor;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LvaReadyPayload {
    pub protocol_version: u32,
    pub port: u16,
    pub nonce: String,
    pub runtime_instance_id: String,
}

#[derive(Debug)]
pub struct CoreInstance {
    pub port: u16,
    pub token: String,
    pub nonce: String,
    pub runtime_instance_id: String,
    // Owns the bootstrap write side for the life of the session. Part 2.3 asks
    // for the pipe to be closed right after the single JSON line, but Core reads
    // stdin EOF as "the parent is gone" and exits (src/lva/__main__.py), so the
    // handle stays open here. Dropping it is what ends the child.
    pub bootstrap_stdin: Option<std::process::ChildStdin>,
}

pub struct CoreSupervisor {
    supervisor: Supervisor,
    python_path: PathBuf,
    workspace_root: PathBuf,
}

impl CoreSupervisor {
    pub fn new(supervisor: Supervisor, python_path: PathBuf, workspace_root: PathBuf) -> Self {
        Self {
            supervisor,
            python_path,
            workspace_root,
        }
    }

    /// Spawn LVA Core with pipe handshake bootstrap.
    pub fn spawn_core(&self, timeout: Duration) -> Result<CoreInstance, String> {
        let token = Uuid::new_v4().to_string() + &Uuid::new_v4().to_string();
        let nonce = Uuid::new_v4().to_string();
        let parent_pid = std::process::id();

        log::info!("[CoreSupervisor] Spawning LVA Core with bootstrap pipe handshake...");

        // The write side is kept alive (not dropped after the JSON line) because
        // Core treats stdin EOF as an orphan signal: see the field comment on
        // CoreInstance::bootstrap_stdin.
        let bootstrap_stdin: Option<std::process::ChildStdin>;

        let mut child = Command::new(&self.python_path)
            .args(&["-m", "lva", "serve", "--bootstrap"])
            .current_dir(&self.workspace_root)
            .env("PYTHONPATH", self.workspace_root.join("src"))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| format!("Failed to spawn python core: {}", e))?;

        // Write bootstrap JSON to stdin
        let bootstrap_json = serde_json::json!({
            "protocol_version": 1,
            "token": token,
            "nonce": nonce,
            "parent_pid": parent_pid,
        });

        if let Some(mut stdin) = child.stdin.take() {
            let line = bootstrap_json.to_string() + "\n";
            stdin
                .write_all(line.as_bytes())
                .map_err(|e| format!("Failed to write bootstrap to core stdin: {}", e))?;
            stdin.flush().ok();
            bootstrap_stdin = Some(stdin);
        } else {
            return Err("Failed to capture core stdin pipe".to_string());
        }

        // Read LVA_READY line from stdout
        let stdout = child.stdout.take().ok_or("Failed to capture core stdout pipe")?;
        // F-009: `read_line` blocks until a newline or EOF, so checking the
        // clock *around* it never enforced the deadline -- a core that wrote a
        // partial line (or nothing) hung the supervisor forever.  The read runs
        // on its own thread and the main thread waits on a channel with
        // `recv_timeout`, so the deadline is real rather than decorative.
        let (tx, rx) = mpsc::channel::<Result<String, String>>();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) => {
                        let _ = tx.send(Err(
                            "Core process stdout closed before emitting LVA_READY".to_string(),
                        ));
                        break;
                    }
                    Ok(_) => {
                        if tx.send(Ok(line)).is_err() {
                            break;
                        }
                    }
                    Err(e) => {
                        let _ = tx.send(Err(format!("Error reading core stdout: {}", e)));
                        break;
                    }
                }
            }
        });

        let start = Instant::now();
        let ready_line: String;
        loop {
            let remaining = match timeout.checked_sub(start.elapsed()) {
                Some(r) if !r.is_zero() => r,
                _ => {
                    let _ = child.kill();
                    return Err("Timeout waiting for LVA_READY from core stdout".to_string());
                }
            };

            match rx.recv_timeout(remaining) {
                Ok(Ok(line)) => {
                    let trimmed = line.trim();
                    if trimmed.starts_with("LVA_READY") {
                        ready_line = trimmed.to_string();
                        break;
                    }
                    if !trimmed.is_empty() {
                        // §2.3-8: readiness is exactly one line on a clean stdout.
                        // Any other output before it is a startup failure, not noise.
                        let _ = child.kill();
                        return Err(format!(
                            "Unexpected core stdout before LVA_READY: {}",
                            trimmed.chars().take(120).collect::<String>()
                        ));
                    }
                }
                Ok(Err(e)) => {
                    let _ = child.kill();
                    return Err(e);
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    let _ = child.kill();
                    return Err("Timeout waiting for LVA_READY from core stdout".to_string());
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    let _ = child.kill();
                    return Err(
                        "Core process stdout closed before emitting LVA_READY".to_string()
                    );
                }
            }
        }

        // Parse LVA_READY payload
        let payload_str = ready_line
            .strip_prefix("LVA_READY")
            .unwrap_or("")
            .trim();
        let ready: LvaReadyPayload = serde_json::from_str(payload_str)
            .map_err(|e| format!("Invalid LVA_READY JSON '{}': {}", payload_str, e))?;

        if ready.protocol_version != 1 {
            let _ = child.kill();
            return Err(format!("Unsupported core protocol_version: {}", ready.protocol_version));
        }

        if ready.nonce != nonce {
            let _ = child.kill();
            return Err("Core nonce mismatch: potential spoofing rejected".to_string());
        }

        log::info!(
            "[CoreSupervisor] Core is READY on port {}, runtime_id={}",
            ready.port,
            ready.runtime_instance_id
        );

       // Register child with Spawned-only supervisor
       self.supervisor.register_spawned("lva_core", child);

        // §2.3-8: a second readiness line is a startup failure, not a log line to
        // ignore. The monitor owns stdout for the rest of the session: it drains the
        // pipe (so the child can never block on a full stdout buffer) and kills the
        // child handle through the ownership-gated supervisor when an extra
        // LVA_READY arrives.
        let supervisor = self.supervisor.clone();
        std::thread::spawn(move || {
            for line in reader.lines() {
                let Ok(text) = line else {
                    return; // pipe closed together with the child
                };
                let trimmed = text.trim();
                if trimmed.is_empty() {
                    continue;
                }
                if trimmed.starts_with("LVA_READY") {
                    log::error!(
                        "[CoreSupervisor] Core emitted a second LVA_READY line; extra readiness lines are a startup failure. Stopping the child handle."
                    );
                    let _ = supervisor.stop_spawned("lva_core", Duration::from_secs(3));
                    return;
                }
                log::debug!("[CoreSupervisor] core stdout: {}", trimmed);
            }
        });

        Ok(CoreInstance {
            port: ready.port,
            token,
            nonce: ready.nonce,
            runtime_instance_id: ready.runtime_instance_id,
            bootstrap_stdin,
        })
    }
}
