pub mod process_manager;
pub mod tray;
pub mod hotkey;
pub mod crypto;
pub mod settings;
pub mod paths;
pub mod autostart;

use std::sync::{atomic::{AtomicU64, Ordering}, Arc};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager, State};
use process_manager::{FullServicesStatus, ProcessManager};
use settings::{AppSettings, GgufModelInfo, SettingsManager};

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

#[tauri::command]
fn unload_vram(state: State<Arc<ProcessManager>>) -> Result<String, String> {
    state.unload_vram()
}

#[tauri::command]
fn cold_start_llm(state: State<Arc<ProcessManager>>) -> Result<f64, String> {
    mark_user_activity();
    state.cold_start_llm()
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
fn get_settings(sm: State<Arc<SettingsManager>>) -> AppSettings {
    sm.get_settings()
}

#[tauri::command]
fn update_settings(new_settings: AppSettings, sm: State<Arc<SettingsManager>>) -> Result<(), String> {
    sm.update_settings(new_settings)
}

#[tauri::command]
fn scan_models(sm: State<Arc<SettingsManager>>) -> Vec<GgufModelInfo> {
    sm.get_cached_models()
}

#[tauri::command]
fn refresh_models(sm: State<Arc<SettingsManager>>) -> Vec<GgufModelInfo> {
    sm.refresh_model_cache();
    sm.get_cached_models()
}

#[tauri::command]
fn switch_llm_model(
    model_path: String,
    pm: State<Arc<ProcessManager>>,
    sm: State<Arc<SettingsManager>>,
) -> Result<f64, String> {
    mark_user_activity();
    let elapsed = pm.switch_model(&model_path)?;
    let mut current = sm.get_settings();
    current.local_gguf_path = model_path;
    let _ = sm.update_settings(current);
    Ok(elapsed)
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

    // Spawn Idle VRAM release daemon thread
    let pm_idle = process_mgr.clone();
    let sm_idle = settings_mgr.clone();
    std::thread::spawn(move || {
        loop {
            std::thread::sleep(Duration::from_secs(30));
            let policy_mins = sm_idle.get_settings().idle_vram_release_mins;
            if policy_mins > 0 && ProcessManager::is_port_listening(1234) {
                let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs();
                let last = LAST_ACTIVITY_EPOCH.load(Ordering::SeqCst);
                let idle_secs = now.saturating_sub(last);
                if idle_secs >= (policy_mins as u64 * 60) {
                    println!("[IdleVRAM] Inactive for {}s (threshold: {}m) -> Releasing ~4.9GB VRAM", idle_secs, policy_mins);
                    let _ = pm_idle.unload_vram();
                }
            }
        }
    });

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            println!("[SingleInstance] Second instance launched -> focusing main pet window");
            mark_user_activity();
            let _ = tray::show_or_create_pet_window(app);
        }))
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(process_mgr)
        .manage(settings_mgr)
        .invoke_handler(tauri::generate_handler![
            get_services_status,
            unload_vram,
            cold_start_llm,
            toggle_pet,
            open_settings,
            get_settings,
            update_settings,
            scan_models,
            refresh_models,
            switch_llm_model,
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
