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
        // F-009: the read must not be able to outlive the deadline, and a
        // malformed readiness line is a startup failure too.  The helper owns the
        // blocking read on its own thread, enforces the timeout with
        // `recv_timeout`, and runs the cleanup callback on *every* failure path --
        // including the JSON parse -- so the child handle is never leaked.
        let (ready, rx) = await_ready_payload(stdout, timeout, || {
            let _ = child.kill();
        })?;

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
        // ignore.  The reader thread above owns the stdout pipe for the rest of the
        // session: it forwards every line here, so the monitor drains the same
        // channel rather than reading the pipe a second time (the `BufReader` was
        // moved into the reader thread and cannot be reused).  Draining keeps the
        // child from blocking on a full stdout buffer, and an extra LVA_READY stops
        // the child through the ownership-gated supervisor.
        let supervisor = self.supervisor.clone();
        std::thread::spawn(move || {
            while let Ok(msg) = rx.recv() {
                let Ok(text) = msg else {
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
/// Read the `LVA_READY` line with a *real* deadline (F-009).
/// Read and parse the `LVA_READY` payload with a real deadline (F-009).
///
/// Wraps [`await_ready_line`] with the payload parse so a *malformed* readiness
/// line is treated exactly like the other startup failures: `on_failure` runs and
/// the caller stops the child it owns.  An earlier version parsed with `?` and
/// returned without cleanup, leaking the child.
fn await_ready_payload(
    stdout: std::process::ChildStdout,
    timeout: Duration,
    mut on_failure: impl FnMut(),
) -> Result<(LvaReadyPayload, mpsc::Receiver<Result<String, String>>), String> {
    let (line, rest) = await_ready_line(stdout, timeout, &mut on_failure)?;
    let payload_str = line.strip_prefix("LVA_READY").unwrap_or("").trim();
    match serde_json::from_str::<LvaReadyPayload>(payload_str) {
        Ok(ready) => Ok((ready, rest)),
        Err(e) => {
            on_failure();
            Err(format!("Invalid LVA_READY JSON '{}': {}", payload_str, e))
        }
    }
}

///
/// `read_line` blocks until a newline or EOF, so a timeout checked around it is
/// never enforced: a child that writes nothing, or a partial line, hangs the
/// supervisor forever.  The blocking read therefore runs on its own thread and
/// the caller waits with `recv_timeout`.  `on_failure` runs on *every* failure
/// path so the caller stops the child it owns instead of leaking it.
///
/// On success the returned receiver still carries the rest of the child's
/// stdout, so the caller can keep draining the pipe (a full stdout buffer would
/// block the child) and watch for an extra readiness line.
fn await_ready_line(
    stdout: std::process::ChildStdout,
    timeout: Duration,
    mut on_failure: impl FnMut(),
) -> Result<(String, mpsc::Receiver<Result<String, String>>), String> {
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
                    return;
                }
                Ok(_) => {
                    if tx.send(Ok(line)).is_err() {
                        return;
                    }
                }
                Err(e) => {
                    let _ = tx.send(Err(format!("Error reading core stdout: {}", e)));
                    return;
                }
            }
        }
    });

    let start = Instant::now();
    loop {
        let remaining = match timeout.checked_sub(start.elapsed()) {
            Some(r) if !r.is_zero() => r,
            _ => {
                on_failure();
                return Err("Timeout waiting for LVA_READY from core stdout".to_string());
            }
        };

        match rx.recv_timeout(remaining) {
            Ok(Ok(line)) => {
                let trimmed = line.trim();
                if trimmed.starts_with("LVA_READY") {
                    return Ok((trimmed.to_string(), rx));
                }
                if !trimmed.is_empty() {
                    // §2.3-8: readiness is exactly one line on a clean stdout.
                    // Any other output before it is a startup failure, not noise.
                    on_failure();
                    return Err(format!(
                        "Unexpected core stdout before LVA_READY: {}",
                        trimmed.chars().take(120).collect::<String>()
                    ));
                }
            }
            Ok(Err(e)) => {
                on_failure();
                return Err(e);
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {
                on_failure();
                return Err("Timeout waiting for LVA_READY from core stdout".to_string());
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                on_failure();
                return Err(
                    "Core process stdout closed before emitting LVA_READY".to_string()
                );
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::{Child, Command, Stdio};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;

    fn spawned(command_line: &str) -> Child {
        Command::new("cmd")
            .arg("/C")
            .arg(command_line)
            .stdout(Stdio::piped())
            .spawn()
            .expect("spawn cmd")
    }

    fn flag() -> (Arc<AtomicBool>, Arc<AtomicBool>) {
        let shared = Arc::new(AtomicBool::new(false));
        (shared.clone(), shared)
    }

    #[test]
    fn a_ready_line_is_returned_and_cleanup_is_not_invoked() {
        let mut child = spawned("echo LVA_READY ok");
        let stdout = child.stdout.take().expect("stdout pipe");
        let (hook, shared) = flag();

        let (line, _rest) = await_ready_line(stdout, Duration::from_secs(10), move || {
            hook.store(true, Ordering::SeqCst)
        })
        .expect("a real LVA_READY line must be accepted");

        assert!(line.starts_with("LVA_READY"), "got {line:?}");
        assert!(!shared.load(Ordering::SeqCst));
        let _ = child.wait();
    }

    #[test]
    fn a_child_that_writes_nothing_times_out_and_invokes_cleanup() {
        let mut child = spawned("ping -n 30 127.0.0.1 >nul");
        let stdout = child.stdout.take().expect("stdout pipe");
        let (hook, shared) = flag();

        let err = await_ready_line(stdout, Duration::from_millis(300), move || {
            hook.store(true, Ordering::SeqCst)
        })
        .expect_err("no output must not be treated as ready");

        assert!(err.contains("Timeout"), "unexpected error: {err}");
        assert!(shared.load(Ordering::SeqCst), "cleanup must run on timeout");
        let _ = child.kill();
        let _ = child.wait();
    }

    #[test]
    fn a_partial_line_at_eof_fails_and_invokes_cleanup() {
        let mut child = spawned("echo|set /p=half-a-line");
        let stdout = child.stdout.take().expect("stdout pipe");
        let (hook, shared) = flag();

        let err = await_ready_line(stdout, Duration::from_secs(10), move || {
            hook.store(true, Ordering::SeqCst)
        })
        .expect_err("a partial non-ready line must be rejected");

        assert!(
            err.contains("Unexpected core stdout") || err.contains("closed before emitting"),
            "unexpected error: {err}"
        );
        assert!(shared.load(Ordering::SeqCst), "cleanup must run on failure");
        let _ = child.wait();
    }

    #[test]
    fn stray_output_before_ready_is_a_startup_failure() {
        let mut child = spawned("echo not-a-ready-line");
        let stdout = child.stdout.take().expect("stdout pipe");
        let (hook, shared) = flag();

        let err = await_ready_line(stdout, Duration::from_secs(10), move || {
            hook.store(true, Ordering::SeqCst)
        })
        .expect_err("stray output must be rejected");

        assert!(err.contains("Unexpected core stdout"), "unexpected error: {err}");
        assert!(shared.load(Ordering::SeqCst), "cleanup must run on failure");
        let _ = child.wait();
    }

    #[test]
    fn an_immediate_eof_fails_and_invokes_cleanup() {
        let mut child = spawned("exit 0");
        let stdout = child.stdout.take().expect("stdout pipe");
        let (hook, shared) = flag();

        let err = await_ready_line(stdout, Duration::from_secs(10), move || {
            hook.store(true, Ordering::SeqCst)
        })
        .expect_err("EOF before readiness must fail");

        assert!(err.contains("closed before emitting LVA_READY"), "unexpected error: {err}");
        assert!(shared.load(Ordering::SeqCst), "cleanup must run on failure");
        let _ = child.wait();
    }
    #[test]
    fn a_malformed_ready_payload_fails_and_invokes_cleanup() {
        let mut child = spawned("echo LVA_READY not-json");
        let stdout = child.stdout.take().expect("stdout pipe");
        let (hook, shared) = flag();

        let err = await_ready_payload(stdout, Duration::from_secs(10), move || {
            hook.store(true, Ordering::SeqCst)
        })
        .expect_err("a malformed readiness payload must be rejected");

        assert!(err.contains("Invalid LVA_READY JSON"), "unexpected error: {err}");
        assert!(
            shared.load(Ordering::SeqCst),
            "a parse failure must still run the child cleanup"
        );
        let _ = child.kill();
        let _ = child.wait();
    }
}

