use std::time::Duration;
use serde::{Deserialize, Serialize};

use crate::supervisor::{ProcessOwnership, Supervisor};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptureExecutionResult {
    pub managed_screenpipe_stopped: Option<bool>,
    pub external_screenpipe_detected: bool,
    pub error: Option<String>,
}

pub struct ManagedCaptureExecutor {
    supervisor: Supervisor,
}

impl ManagedCaptureExecutor {
    pub fn new(supervisor: Supervisor) -> Self {
        Self { supervisor }
    }

    /// Pause capture on LVA-managed components.
    /// If Screenpipe is Spawned by LVA, stops it gracefully.
    /// If Screenpipe is External, does NOT kill it, but flags external_screenpipe_detected.
    pub fn pause_managed_capture(&self) -> CaptureExecutionResult {
        let ownership = self.supervisor.get_ownership("screenpipe");
        match ownership {
            ProcessOwnership::Spawned => {
                match self.supervisor.stop_spawned("screenpipe", Duration::from_secs(3)) {
                    Ok(stopped) => CaptureExecutionResult {
                        managed_screenpipe_stopped: Some(stopped),
                        external_screenpipe_detected: false,
                        error: None,
                    },
                    Err(e) => CaptureExecutionResult {
                        managed_screenpipe_stopped: Some(false),
                        external_screenpipe_detected: false,
                        error: Some(e),
                    },
                }
            }
            ProcessOwnership::Adopted | ProcessOwnership::External => {
                // External Screenpipe exists and cannot be stopped by LVA
                CaptureExecutionResult {
                    managed_screenpipe_stopped: None,
                    external_screenpipe_detected: true,
                    error: None,
                }
            }
            ProcessOwnership::Unknown => CaptureExecutionResult {
                managed_screenpipe_stopped: None,
                external_screenpipe_detected: false,
                error: None,
            },
        }
    }
}
