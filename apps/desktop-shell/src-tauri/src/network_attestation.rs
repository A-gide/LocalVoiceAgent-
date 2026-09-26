//! Effective-bind attestation for the Hub control face (v1.2.1 PR-008).
//!
//! Frozen plan L1208-1216 asks for a *read-only* proof of where the Hub control
//! port actually listens, so that `PID/port means healthy` stops being treated as
//! proof of a loopback-only bind.  This module owns two things and nothing else:
//!
//! 1. parsing the Windows IPv4/IPv6 listener table (`netstat -ano`), and
//! 2. reducing it to a coarse, redacted verdict that may travel to the WebView.
//!
//! Authority boundary (ADR-010 & Part 3.2): observation never confers process
//! authority.  This module holds no `Child` handle, spawns nothing and performs no
//! process action whatsoever -- it only reads a table the OS already exposes.

use std::net::IpAddr;
use std::str::FromStr;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Why a bind could not be proven loopback-only.  Carries no address, no port and
/// no process identifier: it is a reason code, not evidence.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum HubBindReason {
    ResolvedNonLoopback,
    ListenerNonLoopback,
    ProcessUnmapped,
    HubInfoUnavailable,
    RevalidationRequired,
    ProbeFailed,
}

/// The four listener classes the frozen acceptance list (L1215) requires.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BindClass {
    /// Exactly one loopback address is bound -- the only class that may allow control.
    LoopbackOnly,
    /// Bound to `0.0.0.0`: reachable from every IPv4 interface.
    AllInterfacesV4,
    /// Bound to `[::]`: reachable from every IPv6 interface.
    AllInterfacesV6,
    /// A concrete non-loopback address, a malformed row, or a shape we do not model.
    Unmappable,
}

/// One row of the OS listener table, already reduced to what classification needs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ListenerRow {
    pub address: IpAddr,
    pub port: u16,
    pub owning_process: Option<u32>,
}

/// Redacted summary of the effective-bind attestation.
///
/// This type is the one that crosses into the WebView, so it carries only the
/// verdict and coarse provenance.  The raw evidence stays on the Rust diagnostics
/// surface and is correlated by `attestation_id` only.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HubBindAttestation {
    pub status: AttestationStatus,
    pub reason_code: Option<HubBindReason>,
    pub checked_at: DateTime<Utc>,
    pub attestation_id: String,
    pub revalidate_after: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AttestationStatus {
    VerifiedLoopback,
    VerifiedNonLoopback,
    UnverifiedBind,
}

impl HubBindAttestation {
    /// Only a proven loopback-only bind may allow control (plan L665).
    pub fn control_allowed(&self) -> bool {
        matches!(self.status, AttestationStatus::VerifiedLoopback)
    }
}

/// Parse the `netstat -ano` listener table into rows.
///
/// Only rows whose state is `LISTENING` are kept; the foreign column and every
/// other protocol are ignored.  Malformed rows are skipped rather than guessed at,
/// so a table we cannot read degrades to "no rows" instead of a false verdict.
pub fn parse_listener_table(raw: &str) -> Vec<ListenerRow> {
    let mut rows = Vec::new();
    for line in raw.lines() {
        let fields: Vec<&str> = line.split_whitespace().collect();
        if fields.len() < 5 {
            continue;
        }
        if !fields[0].eq_ignore_ascii_case("tcp") && !fields[0].eq_ignore_ascii_case("tcpv6") {
            continue;
        }
        if !fields[3].eq_ignore_ascii_case("listening") {
            continue;
        }
        let Some((address, port)) = split_host_port(fields[1]) else {
            continue;
        };
        rows.push(ListenerRow {
            address,
            port,
            owning_process: fields[4].parse::<u32>().ok(),
        });
    }
    rows
}

/// Split a netstat local-address field into `(address, port)`.
fn split_host_port(field: &str) -> Option<(IpAddr, u16)> {
    let (host, port) = if let Some(rest) = field.strip_prefix('[') {
        // IPv6 form: [::]:135 or [::1]:135
        let end = rest.find(']')?;
        (&rest[..end], rest[end + 1..].strip_prefix(':')?)
    } else {
        // IPv4 form: 0.0.0.0:135
        let idx = field.rfind(':')?;
        (&field[..idx], &field[idx + 1..])
    };
    Some((IpAddr::from_str(host).ok()?, port.parse::<u16>().ok()?))
}

/// Attest one specific port: only the rows bound to that port are evidence.
///
/// Returns the verdict plus the process that owns the listener, so the caller can
/// associate a control port with an identified process without this module ever
/// gaining process authority itself.
pub fn attest_for_port(
    rows: &[ListenerRow],
    port: u16,
    attestation_id: &str,
) -> (HubBindAttestation, Option<u32>) {
    let bound: Vec<ListenerRow> = rows.iter().filter(|row| row.port == port).cloned().collect();
    // The owner is only reported when *every* listener on the port agrees on it.
    // Taking the first non-`None` value (`find_map`) meant a row whose PID could
    // not be read simply did not participate: the correlation looked complete
    // while part of the evidence was missing, and two different processes on the
    // same port were indistinguishable from one.
    let mut owners: Vec<u32> = Vec::new();
    let mut any_unreadable = false;
    for row in &bound {
        match row.owning_process {
            Some(pid) => {
                if !owners.contains(&pid) {
                    owners.push(pid);
                }
            }
            None => any_unreadable = true,
        }
    }
    let owner = if !bound.is_empty() && !any_unreadable && owners.len() == 1 {
        Some(owners[0])
    } else {
        None
    };

    let mut attestation = attest_from_rows(&bound, attestation_id);
    if attestation.status == AttestationStatus::VerifiedLoopback
        && (any_unreadable || owners.len() > 1)
    {
        // Either part of the evidence could not be read or the port is shared by
        // several processes: in both cases the control port is not associated with
        // one identified process, so the bind is not verified (plan L1213/L662).
        attestation.status = AttestationStatus::UnverifiedBind;
        attestation.reason_code = Some(HubBindReason::ProcessUnmapped);
    }
    (attestation, owner)
}

/// Classify a single bound address into one of the four frozen classes.
pub fn classify(address: IpAddr) -> BindClass {
    match address {
        IpAddr::V4(v4) if v4.is_loopback() => BindClass::LoopbackOnly,
        IpAddr::V6(v6) if v6.is_loopback() => BindClass::LoopbackOnly,
        IpAddr::V4(v4) if v4.is_unspecified() => BindClass::AllInterfacesV4,
        IpAddr::V6(v6) if v6.is_unspecified() => BindClass::AllInterfacesV6,
        _ => BindClass::Unmappable,
    }
}

/// Reduce the listener rows for one port into a coarse verdict.
///
/// The rule is deliberately narrow: a port is loopback-only only when every row
/// bound to it is a loopback address.  Anything else -- including "no rows at
/// all" -- is not proof, so it must not be reported as verified.
pub fn attest_from_rows(rows: &[ListenerRow], attestation_id: &str) -> HubBindAttestation {
    let mut status = AttestationStatus::UnverifiedBind;
    let mut reason = Some(HubBindReason::HubInfoUnavailable);

    if !rows.is_empty() {
        let classes: Vec<BindClass> = rows.iter().map(|row| classify(row.address)).collect();
        let all_loopback = classes.iter().all(|c| *c == BindClass::LoopbackOnly);
        let any_unmappable = classes.iter().any(|c| *c == BindClass::Unmappable);

        if all_loopback {
            status = AttestationStatus::VerifiedLoopback;
            reason = None;
        } else {
            status = AttestationStatus::VerifiedNonLoopback;
            reason = Some(if any_unmappable {
                HubBindReason::ProcessUnmapped
            } else {
                HubBindReason::ListenerNonLoopback
            });
        }
    }

    HubBindAttestation {
        status,
        reason_code: reason,
        checked_at: Utc::now(),
        attestation_id: attestation_id.to_string(),
        revalidate_after: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TABLE: &str = "\
  Proto  Local Address          Foreign Address        State           PID\n\
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       2040\n\
  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       4411\n\
  TCP    192.168.1.20:8080      0.0.0.0:0              LISTENING       4411\n\
  TCP    [::]:135               [::]:0                 LISTENING       2040\n\
  TCP    [::1]:9000             [::]:0                 LISTENING       5510\n\
  TCP    127.0.0.1:7000         0.0.0.0:0              ESTABLISHED     1234\n";

    #[test]
    fn listener_table_parses_only_listening_tcp_rows() {
        let rows = parse_listener_table(TABLE);
        // 6 rows in the fixture, one of which is ESTABLISHED.
        assert_eq!(rows.len(), 5, "only LISTENING rows are listeners");
        assert_eq!(rows[0].owning_process, Some(2040));
    }

    #[test]
    fn four_fixture_classes_classify_correctly() {
        let rows = parse_listener_table(TABLE);
        let loopback = rows.iter().find(|r| r.address.to_string() == "127.0.0.1").unwrap();
        assert_eq!(classify(loopback.address), BindClass::LoopbackOnly);

        let v4_any = rows.iter().find(|r| r.address.to_string() == "0.0.0.0").unwrap();
        assert_eq!(classify(v4_any.address), BindClass::AllInterfacesV4);

        let v6_any = rows.iter().find(|r| r.address.to_string() == "::").unwrap();
        assert_eq!(classify(v6_any.address), BindClass::AllInterfacesV6);

        let concrete = rows
            .iter()
            .find(|r| r.address.to_string() == "192.168.1.20")
            .unwrap();
        assert_eq!(classify(concrete.address), BindClass::Unmappable);
    }

    #[test]
    fn ipv6_loopback_is_recognised_as_loopback() {
        let rows = parse_listener_table(TABLE);
        let v6_loop = rows.iter().find(|r| r.address.to_string() == "::1").unwrap();
        assert_eq!(classify(v6_loop.address), BindClass::LoopbackOnly);
    }

    #[test]
    fn a_loopback_only_port_verifies_and_allows_control() {
        let rows = vec![ListenerRow {
            address: IpAddr::from_str("127.0.0.1").unwrap(),
            port: 8080,
            owning_process: Some(4411),
        }];
        let (att, owner) = attest_for_port(&rows, 8080, "att-1");
        assert_eq!(att.status, AttestationStatus::VerifiedLoopback);
        assert!(att.reason_code.is_none());
        assert!(att.control_allowed());
        assert_eq!(owner, Some(4411), "the owning process is identified, not controlled");
    }

    #[test]
    fn an_all_interfaces_port_never_verifies() {
        let rows = vec![ListenerRow {
            address: IpAddr::from_str("0.0.0.0").unwrap(),
            port: 8080,
            owning_process: Some(4411),
        }];
        let (att, _) = attest_for_port(&rows, 8080, "att-2");
        assert_eq!(att.status, AttestationStatus::VerifiedNonLoopback);
        assert!(!att.control_allowed(), "only a proven loopback bind may allow control");
    }

    #[test]
    fn mixed_loopback_and_wildcard_never_verifies() {
        let rows = vec![
            ListenerRow { address: IpAddr::from_str("127.0.0.1").unwrap(), port: 8080, owning_process: Some(1) },
            ListenerRow { address: IpAddr::from_str("0.0.0.0").unwrap(), port: 8080, owning_process: Some(1) },
        ];
        let (att, _) = attest_for_port(&rows, 8080, "att-3");
        assert!(!att.control_allowed(), "one wildcard row is enough to deny control");
    }

    #[test]
    fn an_empty_table_is_unverified_rather_than_verified() {
        let (att, owner) = attest_for_port(&[], 8080, "att-4");
        assert_eq!(att.status, AttestationStatus::UnverifiedBind);
        assert!(!att.control_allowed(), "absence of evidence is not proof of a loopback bind");
        assert_eq!(att.reason_code, Some(HubBindReason::HubInfoUnavailable));
        assert_eq!(owner, None, "an unmapped control port yields no process association");
    }

    #[test]
    fn garbage_input_yields_no_rows_and_no_verified_verdict() {
        let rows = parse_listener_table("not a table at all\n\n   \n");
        assert!(rows.is_empty());
        assert!(!attest_for_port(&rows, 8080, "att-5").0.control_allowed());
    }

    #[test]
    fn malformed_rows_are_skipped_not_guessed() {
        let rows = parse_listener_table("  TCP    :0       0.0.0.0:0   LISTENING   abc\n");
        assert!(rows.is_empty());
    }

    #[test]
    fn only_rows_for_the_requested_port_are_evidence() {
        let rows = parse_listener_table(TABLE);
        // 8080 has one loopback and one concrete address in the fixture.
        let (att, owner) = attest_for_port(&rows, 8080, "att-6");
        assert_eq!(owner, Some(4411));
        assert!(!att.control_allowed(), "a concrete non-loopback row denies control");

        // 135 is wildcard on both stacks.
        let (att135, _) = attest_for_port(&rows, 135, "att-7");
        assert!(!att135.control_allowed());
    }

    #[test]
    fn a_loopback_port_whose_owner_cannot_be_read_does_not_verify() {
        // The review's finding: a row whose PID cannot be parsed used to be kept
        // but ignored by `find_map`, so the correlation looked complete while part
        // of the evidence was missing.  Plan L1213/L662 require the control port to
        // be associated with an *identified* process.
        let rows = vec![ListenerRow {
            address: IpAddr::from_str("127.0.0.1").unwrap(),
            port: 8080,
            owning_process: None,
        }];
        let (att, owner) = attest_for_port(&rows, 8080, "att-owner-missing");
        assert_eq!(att.status, AttestationStatus::UnverifiedBind);
        assert!(!att.control_allowed(), "an unreadable owner is not an identification");
        assert_eq!(att.reason_code, Some(HubBindReason::ProcessUnmapped));
        assert_eq!(owner, None, "no owner may be reported when one is unknown");
    }

    #[test]
    fn a_loopback_port_shared_by_two_processes_does_not_verify() {
        // Two different owners on the same port means the port is not associated
        // with one identified process, so the verdict must not pass even though
        // every row is loopback and every PID is readable.
        let rows = vec![
            ListenerRow {
                address: IpAddr::from_str("127.0.0.1").unwrap(),
                port: 8080,
                owning_process: Some(11),
            },
            ListenerRow {
                address: IpAddr::from_str("::1").unwrap(),
                port: 8080,
                owning_process: Some(22),
            },
        ];
        let (att, owner) = attest_for_port(&rows, 8080, "att-two-owners");
        assert_eq!(att.status, AttestationStatus::UnverifiedBind);
        assert!(!att.control_allowed(), "a shared port has no single identified owner");
        assert_eq!(att.reason_code, Some(HubBindReason::ProcessUnmapped));
        assert_eq!(owner, None);
    }

    #[test]
    fn a_loopback_port_with_one_process_on_both_stacks_still_verifies() {
        // The counterpart of the test above: the same process listening on IPv4
        // and IPv6 loopback is a normal Hub and must keep verifying.
        let rows = vec![
            ListenerRow {
                address: IpAddr::from_str("127.0.0.1").unwrap(),
                port: 8080,
                owning_process: Some(77),
            },
            ListenerRow {
                address: IpAddr::from_str("::1").unwrap(),
                port: 8080,
                owning_process: Some(77),
            },
        ];
        let (att, owner) = attest_for_port(&rows, 8080, "att-one-owner");
        assert_eq!(att.status, AttestationStatus::VerifiedLoopback);
        assert!(att.control_allowed());
        assert_eq!(owner, Some(77));
    }

    #[test]
    fn an_unreadable_pid_is_kept_as_a_row_but_a_malformed_row_is_dropped() {
        // Two different discards: the negative tests above depend on telling them
        // apart, because only the first leaves the owner set incomplete.
        let unreadable_pid = parse_listener_table(
            "  TCP    127.0.0.1:8080      0.0.0.0:0   LISTENING   notanumber\\n",
        );
        assert_eq!(unreadable_pid.len(), 1, "an unreadable PID must keep the row");
        assert_eq!(unreadable_pid[0].owning_process, None);

        let malformed = parse_listener_table(
            "  TCP    :0       0.0.0.0:0   LISTENING   4411\\n",
        );
        assert!(malformed.is_empty(), "a malformed row has no address to trust");
    }
}
