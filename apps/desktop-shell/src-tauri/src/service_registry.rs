use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use crate::supervisor::ProcessOwnership;

/// Identity and readiness for one LVA-managed service (v1.2.1 PR-008).
///
/// The frozen plan replaces "a PID/port is visible, therefore the service is
/// healthy" with an explicit identity + capability + readiness state.  `pid` and
/// `port` are still reported for diagnostics, but they are observations: they
/// never imply the right to stop anything.  That right is expressed only by
/// [`ServiceIdentity::can_stop`], which is derived from ownership.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Readiness {
    /// Not observed yet.
    Unknown,
    /// A process exists but has not proven its identity/readiness handshake.
    Starting,
    /// Identity confirmed and the readiness handshake succeeded.
    Ready,
    /// Identity confirmed, but the service reported a degraded state.
    Degraded,
    /// Identity confirmed and the service is known to have exited.
    Exited,
}

/// Why a service stopped.  A restart that changes the PID must not be misread as
/// the same instance still running (frozen acceptance L1215).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CrashReason {
    /// No failure recorded.
    None,
    /// The identity handshake failed or timed out.
    HandshakeFailed,
    /// The process exited on its own with a non-zero status.
    ExitedNonZero,
    /// The process disappeared without us observing an exit status.
    Vanished,
    /// The owner stopped it deliberately.
    Requested,
}

/// The typed service identity/readiness record published to UI and Core.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceIdentity {
    pub name: String,
    pub readiness: Readiness,
    pub ownership: ProcessOwnership,
    pub crash_reason: CrashReason,
    /// Opaque per-instance token.  A new token means a *different* process, even
    /// if the PID or port happens to be reused.
    pub instance_token: String,
    pub pid: Option<u32>,
    pub port: Option<u16>,
    pub last_error: Option<String>,
}

impl ServiceIdentity {
    /// Only a process this Tauri instance spawned may be stopped.
    ///
    /// Adopted, External and Unknown are observed only: they are never killed
    /// (ADR-010, Part 3.2, invariant I04).  This is the single place the desktop
    /// shell is allowed to answer "may I stop this?".
    pub fn can_stop(&self) -> bool {
        match self.ownership {
            ProcessOwnership::Spawned => true,
            ProcessOwnership::Adopted => false,
            ProcessOwnership::External => false,
            ProcessOwnership::Unknown => false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PublicServiceInfo {
    pub name: String,
    pub is_healthy: bool,
    pub status_text: String,
    pub ownership: ProcessOwnership,
}

#[derive(Clone)]
pub struct ServiceRegistry {
    services: Arc<Mutex<HashMap<String, ServiceIdentity>>>,
}

impl ServiceRegistry {
    pub fn new() -> Self {
        Self {
            services: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Observe one service and publish its typed identity/readiness state.
    ///
    /// `instance_token` is supplied by the caller (normally generated when the
    /// service is spawned) so that a restarted process gets a new token even when
    /// the OS recycles its PID.
    pub fn observe(
        &self,
        name: &str,
        readiness: Readiness,
        ownership: ProcessOwnership,
        instance_token: &str,
        pid: Option<u32>,
        port: Option<u16>,
    ) -> ServiceIdentity {
        let identity = ServiceIdentity {
            name: name.to_string(),
            readiness,
            ownership,
            crash_reason: CrashReason::None,
            instance_token: instance_token.to_string(),
            pid,
            port,
            last_error: None,
        };
        let mut map = self.services.lock().unwrap();
        map.insert(name.to_string(), identity.clone());
        identity
    }

    /// Record a crash reason without changing the observed identity.
    pub fn record_crash(&self, name: &str, reason: CrashReason) {
        let mut map = self.services.lock().unwrap();
        if let Some(entry) = map.get_mut(name) {
            entry.crash_reason = reason;
            if reason != CrashReason::None {
                entry.readiness = Readiness::Exited;
            }
        }
    }

    /// The typed identity/readiness record for one service.
    pub fn get_identity(&self, name: &str) -> Option<ServiceIdentity> {
        self.services.lock().unwrap().get(name).cloned()
    }

    /// Every observed service identity, ordered by name for stable output.
    pub fn get_all_identities(&self) -> Vec<ServiceIdentity> {
        let map = self.services.lock().unwrap();
        let mut out: Vec<ServiceIdentity> = map.values().cloned().collect();
        out.sort_by(|a, b| a.name.cmp(&b.name));
        out
    }

    /// Re-observe a service after a restart.  Returns true when the token changed,
    /// which is the signal that the previous instance is gone.
    pub fn reobserve_after_restart(
        &self,
        name: &str,
        instance_token: &str,
        pid: Option<u32>,
    ) -> bool {
        let previous = self.get_identity(name);
        let changed = previous
            .as_ref()
            .map(|prev| prev.instance_token != instance_token)
            .unwrap_or(true);
        self.observe(
            name,
            Readiness::Starting,
            previous.map(|p| p.ownership).unwrap_or(ProcessOwnership::Unknown),
            instance_token,
            pid,
            None,
        );
        changed
    }

    pub fn update_status(
        &self,
        name: &str,
        is_healthy: bool,
        status_text: &str,
        ownership: ProcessOwnership,
    ) -> ServiceIdentity {
        let readiness = if is_healthy {
            Readiness::Ready
        } else {
            Readiness::Degraded
        };
        let token = self
            .get_identity(name)
            .map(|prev| prev.instance_token)
            .unwrap_or_else(|| format!("{}:legacy", name));
        let mut identity = self.observe(name, readiness, ownership, &token, None, None);
        identity.last_error = if is_healthy {
            None
        } else {
            Some(status_text.to_string())
        };
        let mut map = self.services.lock().unwrap();
        map.insert(name.to_string(), identity.clone());
        identity
    }

    /// Compatibility projection for the pre-PR-008 status surface.
    ///
    /// Kept until PR-038 deletes the legacy display (frozen rollback note L1216).
    pub fn get_all_services(&self) -> Vec<PublicServiceInfo> {
        let map = self.services.lock().unwrap();
        map.values()
            .map(|identity| PublicServiceInfo {
                name: identity.name.clone(),
                is_healthy: matches!(identity.readiness, Readiness::Ready),
                status_text: format!("{:?}", identity.readiness),
                ownership: identity.ownership,
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn registry_with(name: &str, ownership: ProcessOwnership) -> ServiceRegistry {
        let reg = ServiceRegistry::new();
        reg.observe(name, Readiness::Ready, ownership, "tok-1", Some(100), Some(8089));
        reg
    }

    #[test]
    fn only_a_spawned_service_can_be_stopped() {
        assert!(registry_with("core", ProcessOwnership::Spawned)
            .get_identity("core")
            .unwrap()
            .can_stop());
    }

    #[test]
    fn unknown_offers_no_stop() {
        let identity = registry_with("hub", ProcessOwnership::Unknown)
            .get_identity("hub")
            .unwrap();
        assert!(!identity.can_stop(), "Unknown must not offer stop");
    }

    #[test]
    fn adopted_and_external_offer_no_stop() {
        for ownership in [ProcessOwnership::Adopted, ProcessOwnership::External] {
            let identity = registry_with("screenpipe", ownership)
                .get_identity("screenpipe")
                .unwrap();
            assert!(!identity.can_stop(), "{:?} must not offer stop", ownership);
        }
    }

    #[test]
    fn observing_a_pid_and_port_confers_no_authority() {
        // The record carries a PID and a port, yet still refuses stop.
        let reg = ServiceRegistry::new();
        let identity = reg.observe(
            "hub",
            Readiness::Ready,
            ProcessOwnership::Unknown,
            "tok-hub",
            Some(4242),
            Some(8089),
        );
        assert_eq!(identity.pid, Some(4242));
        assert_eq!(identity.port, Some(8089));
        assert!(
            !identity.can_stop(),
            "seeing a PID/port must not create kill authority"
        );
    }

    #[test]
    fn a_restart_with_a_new_token_is_detected_even_when_the_pid_repeats() {
        let reg = ServiceRegistry::new();
        reg.observe("core", Readiness::Ready, ProcessOwnership::Spawned, "tok-1", Some(100), Some(7000));
        // The OS recycled the PID: same number, different process.
        let changed = reg.reobserve_after_restart("core", "tok-2", Some(100));
        assert!(changed, "a new instance token means a different process");
        let identity = reg.get_identity("core").unwrap();
        assert_eq!(identity.instance_token, "tok-2");
        assert_eq!(identity.readiness, Readiness::Starting);
    }

    #[test]
    fn reobserving_the_same_token_is_not_a_restart() {
        let reg = ServiceRegistry::new();
        reg.observe("core", Readiness::Ready, ProcessOwnership::Spawned, "tok-1", Some(100), None);
        assert!(!reg.reobserve_after_restart("core", "tok-1", Some(100)));
    }

    #[test]
    fn a_crash_reason_moves_the_service_to_exited() {
        let reg = registry_with("core", ProcessOwnership::Spawned);
        reg.record_crash("core", CrashReason::ExitedNonZero);
        let identity = reg.get_identity("core").unwrap();
        assert_eq!(identity.crash_reason, CrashReason::ExitedNonZero);
        assert_eq!(identity.readiness, Readiness::Exited);
    }

    #[test]
    fn identities_are_returned_in_stable_name_order() {
        let reg = ServiceRegistry::new();
        reg.observe("zebra", Readiness::Ready, ProcessOwnership::Unknown, "t", None, None);
        reg.observe("alpha", Readiness::Ready, ProcessOwnership::Unknown, "t", None, None);
        let names: Vec<String> = reg.get_all_identities().into_iter().map(|i| i.name).collect();
        assert_eq!(names, vec!["alpha".to_string(), "zebra".to_string()]);
    }

    #[test]
    fn the_legacy_projection_still_reports_health_and_ownership() {
        let reg = registry_with("core", ProcessOwnership::Spawned);
        let legacy = reg.get_all_services();
        assert_eq!(legacy.len(), 1);
        assert!(legacy[0].is_healthy);
        assert_eq!(legacy[0].ownership, ProcessOwnership::Spawned);
    }

    #[test]
    fn an_unknown_service_has_no_identity_record() {
        assert!(ServiceRegistry::new().get_identity("nobody").is_none());
    }
}
