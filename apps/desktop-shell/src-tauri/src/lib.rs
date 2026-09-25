pub mod autostart;
pub mod bridge;
pub mod core_supervisor;
pub mod crypto;
pub mod generated;
pub mod hotkey;
pub mod managed_capture;
pub mod network_attestation;
pub mod paths;
pub mod process_manager;
pub mod service_registry;
pub mod settings;
pub mod supervisor;
pub mod tray;
pub mod ws;

use std::sync::{atomic::{AtomicU64, Ordering}, Arc};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use serde::Serialize;
use tauri::{AppHandle, Manager, State};
use bridge::CoreBridge;
use core_supervisor::CoreSupervisor;
use process_manager::{FullServicesStatus, ProcessManager};
use service_registry::ServiceRegistry;
use settings::{AppSettings, PublicAppSettings, SettingsManager};
use supervisor::Supervisor;
use managed_capture::{
    CaptureExecutionResult, CaptureIntent, CaptureProbe, ManagedCaptureExecutor,
    SCREENPIPE_SERVICE,
};


// Global activity timestamp for idle VRAM timer
static LAST_ACTIVITY_EPOCH: AtomicU64 = AtomicU64::new(0);

fn mark_user_activity() {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs();
    LAST_ACTIVITY_EPOCH.store(now, Ordering::SeqCst);
}

#[tauri::command]
fn get_autostart_status() -> bool {
    autostart::is_autostart_enabled()
}

#[tauri::command]
fn set_autostart_status(enabled: bool) -> Result<bool, String> {
    autostart::set_autostart_enabled(enabled)?;
    Ok(autostart::is_autostart_enabled())
}

#[tauri::command]
fn get_services_status(state: State<Arc<ProcessManager>>) -> FullServicesStatus {
    state.get_status()
}

/// Typed service identity/readiness + effective-bind attestation (PR-008).
///
/// This is the reader that keeps `service_registry` from being dead code, and it
/// is the surface UI/Core consume instead of inferring health from a PID or port.
#[tauri::command]
fn get_service_identity_status(
    registry: State<'_, Arc<ServiceRegistry>>,
) -> ServiceIdentityReport {
    let identities = registry.get_all_identities();
    ServiceIdentityReport {
        services: identities,
        hub_bind: observe_hub_bind_attestation(),
    }
}

/// The typed payload returned to the WebView.
#[derive(Debug, Clone, Serialize)]
pub struct ServiceIdentityReport {
    pub services: Vec<service_registry::ServiceIdentity>,
    pub hub_bind: network_attestation::HubBindAttestation,
}

/// Probe the Screenpipe REST surface (plan L286/L156).
///
/// Read-only: a reachability check plus a version read.  A version the executor
/// was not written against makes the instance *uncontrollable* rather than
/// guessed at (plan L1709).
fn probe_screenpipe_capability() -> CaptureProbe {
    use std::net::{SocketAddr, TcpStream};
    let addr = SocketAddr::from(([127, 0, 0, 1], 3030));
    let reachable = TcpStream::connect_timeout(&addr, std::time::Duration::from_millis(200)).is_ok();
    if !reachable {
        return CaptureProbe::unknown();
    }
    // The REST surface answers but the executor has no pinned Screenpipe version
    // contract yet, so the control channel stays unproven.  Reporting it as
    // controllable would be the false-confidence the plan forbids.
    CaptureProbe { reachable: true, version_known: false }
}

/// The capture executor's view of the LVA-managed Screenpipe instance (PR-021).
///
/// The WebView needs to show whether LVA can actually control the recorder, and
/// the answer is a capability, not a boolean: "reachable" is not "controllable",
/// and an uncontrollable instance must be surfaced rather than implied away
/// (plan L1345/L1347).
#[derive(Debug, Clone, Serialize)]
pub struct CaptureCapabilityReport {
    pub service: String,
    pub capability: managed_capture::CaptureCapability,
    pub last_result: Option<CaptureExecutionResult>,
}

/// Report whether LVA can control the managed recorder (PR-021).
#[tauri::command]
fn get_capture_capability(
    executor: State<'_, Arc<ManagedCaptureExecutor>>,
) -> CaptureCapabilityReport {
    CaptureCapabilityReport {
        service: SCREENPIPE_SERVICE.to_string(),
        capability: executor.capability(&probe_screenpipe_capability()),
        last_result: executor.last_result(),
    }
}

/// Run one managed-capture operation and report what actually happened.
///
/// `operation_id` is supplied by the caller (Core, once the ack command face is
/// authorised) so the result can be correlated with the request.  When it is
/// empty the executor still refuses to invent an id: it echoes back what it got,
/// and the caller must treat that as an uncorrelated result.
#[tauri::command]
fn execute_capture_operation(
    operation_id: String,
    intent: String,
    executor: State<'_, Arc<ManagedCaptureExecutor>>,
) -> Result<CaptureExecutionResult, String> {
    let intent = match intent.as_str() {
        "stop" => CaptureIntent::Stop,
        "resume" => CaptureIntent::Resume,
        other => return Err(format!("unknown capture intent: {}", other)),
    };
    Ok(executor.execute(&operation_id, intent, &probe_screenpipe_capability()))
}

/// Read the OS listener table and reduce it to a redacted bind verdict.
///
/// Read-only by construction: this function runs `netstat` (a query), parses the
/// output and returns a verdict.  It never touches a process handle, so observing
/// a listener can never become kill authority (frozen acceptance L1215).
fn observe_hub_bind_attestation() -> network_attestation::HubBindAttestation {
    use network_attestation::{attest_for_port, parse_listener_table, HubBindReason};

    let attestation_id = uuid::Uuid::new_v4().to_string();
    let table = match std::process::Command::new("netstat").args(["-ano", "-p", "tcp"]).output() {
        Ok(output) if output.status.success() => {
            String::from_utf8_lossy(&output.stdout).to_string()
        }
        _ => {
            // Cannot read the table -> cannot prove anything -> fail closed.
            let mut att = attest_for_port(&[], 0, &attestation_id).0;
            att.reason_code = Some(HubBindReason::ProbeFailed);
            return att;
        }
    };

    let rows = parse_listener_table(&table);
    attest_for_port(&rows, HUB_CONTROL_PORT, &attestation_id).0
}

/// The Hub control port whose effective bind must be attested.
///
/// Plan L527: the Hub's default entry is **8080** and its child backends get
/// 8081+; LVA does not depend on a child port.  This must match the Hub's own
/// configured `webPort` (and Core's `HUB_PORT`), because probing a port with no
/// listener yields `UNVERIFIED_BIND` and would close the control gate permanently
/// even against a healthy Hub.
const HUB_CONTROL_PORT: u16 = 8080;

/// How often the effective bind is re-attested.
///
/// Plan L665 is a *continuing* condition, not a one-time ticket: Core expires a
/// verdict through its `revalidate_after` deadline, so Rust must keep reporting or
/// the gate would close on its own and stay closed.  The interval is comfortably
/// shorter than the deadline Core is given, so a single missed cycle does not
/// immediately close the gate.
const REATTEST_INTERVAL: Duration = Duration::from_secs(30);

/// Report the current effective-bind verdict to LVA Core (PR-012).
///
/// Transport: the **existing authenticated WS**.  Rust is the WS client and Core
/// is the server, so the verdict goes straight to Core; the Tauri event channel is
/// not involved (that channel reaches the WebView, not Core).
///
/// `send_command` blocks until the correlated result arrives, so the caller must
/// already be off the UI/IPC thread -- this function is called from the periodic
/// thread below, not from a Tauri command handler.
fn send_bind_attestation(bridge: &CoreBridge) -> Result<serde_json::Value, String> {
    let attestation = observe_hub_bind_attestation();
    // The contract's HubAttestBindPayload nests the verdict under `attestation`.
    // `attestation_id` is what Core correlates against; the rest of the verdict is
    // already redacted by construction (no PID, port or address).
    let cmd = serde_json::json!({
        "type": "hub.attest_bind",
        "payload": {
            "type": "hub.attest_bind",
            "attestation": {
                "status": match attestation.status {
                    network_attestation::AttestationStatus::VerifiedLoopback => "VERIFIED_LOOPBACK",
                    network_attestation::AttestationStatus::VerifiedNonLoopback => "VERIFIED_NON_LOOPBACK",
                    network_attestation::AttestationStatus::UnverifiedBind => "UNVERIFIED_BIND",
                },
                "reason_code": attestation.reason_code.map(|reason| {
                    // Core's HubBindReason uses SCREAMING_SNAKE_CASE names.
                    match reason {
                        network_attestation::HubBindReason::ResolvedNonLoopback => "RESOLVED_NON_LOOPBACK",
                        network_attestation::HubBindReason::ListenerNonLoopback => "LISTENER_NON_LOOPBACK",
                        network_attestation::HubBindReason::ProcessUnmapped => "PROCESS_UNMAPPED",
                        network_attestation::HubBindReason::HubInfoUnavailable => "HUB_INFO_UNAVAILABLE",
                        network_attestation::HubBindReason::RevalidationRequired => "REVALIDATION_REQUIRED",
                        network_attestation::HubBindReason::ProbeFailed => "PROBE_FAILED",
                    }
                }),
                "checked_at": attestation.checked_at.to_rfc3339(),
                "attestation_id": attestation.attestation_id,
                // The deadline Core enforces.  A verified verdict is given the
                // full interval plus slack; anything unverified is given no grace
                // at all, because a verdict that cannot prove loopback must not be
                // allowed to authorise control even briefly.
                "revalidate_after": match attestation.status {
                    network_attestation::AttestationStatus::VerifiedLoopback => Some(
                        (chrono::Utc::now()
                            + chrono::Duration::seconds(
                                REATTEST_INTERVAL.as_secs() as i64 * 3,
                            ))
                        .to_rfc3339(),
                    ),
                    _ => None,
                },
            },
        },
    });

    match bridge.send_command(cmd) {
        Ok(result) => {
            log::info!(
                "[Core] Reported bind attestation {} (control_allowed={})",
                attestation.attestation_id,
                result
                    .get("data")
                    .and_then(|data| data.get("control_allowed"))
                    .and_then(|allowed| allowed.as_bool())
                    .unwrap_or(false),
            );
            Ok(result)
        }
        Err(e) => {
            // Logged rather than swallowed: a dropped attestation is
            // indistinguishable from a legitimately closed gate at the Core end,
            // which would make this very hard to diagnose.
            log::warn!("[Core] Failed to report bind attestation: {}", e);
            Err(e)
        }
    }
}

/// Periodic re-attestation thread (PR-012).
fn start_attestation_reporter(bridge: Arc<CoreBridge>) {
    std::thread::Builder::new()
        .name("lva-attestation-reporter".into())
        .spawn(move || loop {
            std::thread::sleep(REATTEST_INTERVAL);
            let _ = send_bind_attestation(&bridge);
        })
        .ok();
}

#[tauri::command]
fn toggle_pet(app: AppHandle, sm: State<Arc<SettingsManager>>) {
    mark_user_activity();
    tray::toggle_pet_window(&app, &sm);
}

#[tauri::command]
fn open_settings(app: AppHandle) {
    tray::open_settings_window(&app);
}

#[tauri::command]
fn open_chat(app: AppHandle) {
    tray::open_chat_window(&app);
}

#[tauri::command]
fn open_memory(app: AppHandle) {
    tray::open_memory_window(&app);
}

#[tauri::command]
fn get_settings(sm: State<Arc<SettingsManager>>) -> PublicAppSettings {
    sm.get_public_settings()
}

#[tauri::command]
fn get_public_settings(sm: State<Arc<SettingsManager>>) -> PublicAppSettings {
    sm.get_public_settings()
}

#[tauri::command]
fn set_secret(secret_type: String, secret_value: String, sm: State<Arc<SettingsManager>>) -> Result<(), String> {
    sm.set_secret(&secret_type, &secret_value)
}

#[tauri::command]
fn clear_secret(secret_type: String, sm: State<Arc<SettingsManager>>) -> Result<(), String> {
    sm.clear_secret(&secret_type)
}

#[tauri::command]
async fn send_core_command(
    cmd: serde_json::Value,
    bridge: State<'_, Arc<CoreBridge>>,
) -> Result<serde_json::Value, String> {
    // Part 8.1: the WebView never reaches Core itself; it only invokes this
    // command. send_command blocks until the correlated command_result arrives,
    // so it runs on a blocking worker: a non-async command would execute on the
    // WebView IPC thread and stall the whole UI for up to the command timeout.
    let bridge = Arc::clone(&bridge);
    tauri::async_runtime::spawn_blocking(move || bridge.send_command(cmd))
        .await
        .map_err(|e| format!("Core command task failed: {}", e))?
}

#[tauri::command]
fn update_settings(new_settings: AppSettings, sm: State<Arc<SettingsManager>>) -> Result<(), String> {
    sm.update_settings(new_settings)
}

#[tauri::command]
fn rebuild_pet_benchmark(app: AppHandle) -> Result<f64, String> {
    mark_user_activity();
    // If window exists, destroy first
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.destroy();
        std::thread::sleep(Duration::from_millis(500));
    }
    let elapsed_ms = tray::show_or_create_pet_window(&app);
    Ok(elapsed_ms)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    mark_user_activity();

    let process_mgr = Arc::new(ProcessManager::new());
    let settings_mgr = Arc::new(SettingsManager::new());
    settings_mgr.start_background_scanner();

    // M2: Defense-in-depth panic hook to guarantee spawned child processes are killed on abnormal termination
    let pm_panic = process_mgr.clone();
    let default_panic_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        eprintln!("[FATAL PANIC] lva-pet panicked: {:?}. Emergency shutdown of spawned child processes...", info);
        pm_panic.safe_shutdown_spawned_only();
        default_panic_hook(info);
    }));

    let pm_clone = process_mgr.clone();
    let sm_clone = settings_mgr.clone();

    let supervisor = Arc::new(Supervisor::new());
    let bridge = Arc::new(CoreBridge::new());
    let service_registry = Arc::new(ServiceRegistry::new());
    // PR-021: the managed-capture executor.  It is operation-driven -- Core owns
    // the decision (PR-020) and this carries it out -- so it is not subscribed to
    // the mode itself.  The spawner is the existing ProcessManager path, injected
    // rather than duplicated, so there is one way to start the recorder.
    let capture_executor = Arc::new(ManagedCaptureExecutor::new((*supervisor).clone()));
    // PR-008: observe the desktop-side services so the typed identity/readiness
    // surface is actually populated.  Observation only -- the registry holds no
    // child handle and can therefore never confer stop authority by itself.
    service_registry.observe(
        "lva_core",
        service_registry::Readiness::Starting,
        supervisor::ProcessOwnership::Unknown,
        "lva_core:pending",
        None,
        None,
    );
    let bridge_for_events = bridge.clone();
    let supervisor_for_core = supervisor.clone();
    let bridge_for_core = bridge.clone();
    let service_registry_for_core = service_registry.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            println!("[SingleInstance] Second instance launched -> focusing main pet window");
            mark_user_activity();
            let _ = tray::show_or_create_pet_window(app);
        }))
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(process_mgr)
        .manage(settings_mgr)
        .manage(supervisor)
        .manage(bridge)
        .manage(service_registry)
        .manage(capture_executor)
        .invoke_handler(tauri::generate_handler![
            get_services_status,
            get_service_identity_status,
            get_capture_capability,
            execute_capture_operation,
            toggle_pet,
            open_settings,
            open_chat,
            open_memory,
            get_settings,
            get_public_settings,
            set_secret,
            clear_secret,
            send_core_command,
            update_settings,
            rebuild_pet_benchmark,
            get_autostart_status,
            set_autostart_status
        ])
        .setup(move |app| {
            if cfg!(debug_assertions) {
                let _ = app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                );
            }

            // PR-007: one Rust-owned authenticated WebSocket to Core. The worker
            // thread reconnects on its own; the WebView only sees lva://event.
            bridge_for_events.attach_app(app.handle().clone());
            bridge_for_events.start();
            // PR-012: keep Core's bind attestation fresh.  Core expires a verdict
            // through `revalidate_after`, so a one-shot report would let the
            // control gate close on its own.
            start_attestation_reporter(bridge_for_events.clone());

            // v1.2.1 PR-007: Tauri owns the Core child handle and the runtime token.
            // The token exists only inside the bootstrap pipe payload; it is never
            // written to argv, env, disk or the WebView. Spawning happens off the UI
            // thread so a slow model load cannot delay the pet window.
            std::thread::spawn(move || {
                let workspace_root = paths::get_app_dir();
                let python_path = workspace_root
                    .join(".venv")
                    .join("Scripts")
                    .join("python.exe");
                let core_supervisor = CoreSupervisor::new(
                    (*supervisor_for_core).clone(),
                    python_path,
                    workspace_root,
                );
                match core_supervisor.spawn_core(Duration::from_secs(20)) {
                    Ok(instance) => {
                        log::info!(
                            "[Core] LVA Core READY on port {} (runtime_instance_id={})",
                            instance.port, instance.runtime_instance_id
                        );
                        // PR-008: the READY handshake is what turns an observed
                        // process into an identified, ready service.
                        service_registry_for_core.observe(
                            "lva_core",
                            service_registry::Readiness::Ready,
                            supervisor::ProcessOwnership::Spawned,
                            &instance.runtime_instance_id,
                            None,
                            Some(instance.port),
                        );
                        bridge_for_core.set_instance(instance);
                    }
                    Err(e) => {
                        eprintln!("[Core] Failed to start LVA Core: {}", e);
                        service_registry_for_core.observe(
                            "lva_core",
                            service_registry::Readiness::Exited,
                            supervisor::ProcessOwnership::Spawned,
                            "lva_core:failed",
                            None,
                            None,
                        );
                        service_registry_for_core
                            .record_crash("lva_core", service_registry::CrashReason::HandshakeFailed);
                    }
                }
            });

            // Setup Tray with process_mgr and settings_mgr
            tray::setup_tray(app.handle(), pm_clone, sm_clone)?;

            // Setup Hotkey (Alt+V / Ctrl+Shift+Space / Ctrl+Space)
            if let Err(e) = hotkey::setup_hotkey(app.handle()) {
                eprintln!("[Hotkey] Warning: failed to register hotkey: {}", e);
            }

            // Immediately display the pet window on startup
            let app_init = app.handle().clone();
            tray::show_or_create_pet_window(&app_init);

            // Win32 Named Event Listener for instant IPC wake and dormancy signals
            let app_h = app.handle().clone();
            std::thread::spawn(move || {
                use std::ffi::OsStr;
                use std::os::windows::ffi::OsStrExt;

                let wake_name: Vec<u16> = OsStr::new("Local\\lva_pet_toggle_event_v1")
                    .encode_wide()
                    .chain(std::iter::once(0))
                    .collect();
                let dorm_name: Vec<u16> = OsStr::new("Local\\lva_pet_dormancy_event_v1")
                    .encode_wide()
                    .chain(std::iter::once(0))
                    .collect();

                extern "system" {
                    fn CreateEventW(lpEventAttributes: *mut std::ffi::c_void, bManualReset: i32, bInitialState: i32, lpName: *const u16) -> *mut std::ffi::c_void;
                    fn WaitForSingleObject(hHandle: *mut std::ffi::c_void, dwMilliseconds: u32) -> u32;
                }

                unsafe {
                    let h_wake = CreateEventW(std::ptr::null_mut(), 0, 0, wake_name.as_ptr());
                    let h_dorm = CreateEventW(std::ptr::null_mut(), 0, 0, dorm_name.as_ptr());
                    loop {
                        if WaitForSingleObject(h_wake, 100) == 0 {
                            println!("[WakeEvent] Received wake signal -> recreating pet window");
                            mark_user_activity();
                            let _ = tray::show_or_create_pet_window(&app_h);
                        }
                        if WaitForSingleObject(h_dorm, 100) == 0 {
                            println!("[DormancyEvent] Received dormancy signal -> destroying pet window");
                            if let Some(w) = app_h.get_webview_window("main") {
                                let _ = w.destroy();
                            }
                            std::thread::sleep(std::time::Duration::from_millis(150));
                            #[cfg(windows)]
                            tray::trim_working_set();
                        }
                    }
                }
            });

            #[cfg(windows)]
            std::thread::spawn(|| {
                std::thread::sleep(std::time::Duration::from_millis(300));
                tray::trim_working_set();
            });

            println!("============================================================");
            println!("  LVA DESKTOP SHELL (lva-pet) P2 INITIALIZED & READY       ");
            println!("  Hotkey: Ctrl+Shift+Space | Tray: Settings & Dormancy    ");
            println!("============================================================");

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, _event| {});
}
