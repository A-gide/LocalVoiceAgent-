use tauri::{AppHandle, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};
use crate::settings::SettingsManager;
use crate::tray::toggle_pet_window;
use std::sync::Arc;

pub fn setup_hotkey(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let candidates = ["Alt+V", "Ctrl+Shift+Space", "Ctrl+Space"];
    let app_handle = app.clone();
    let mut registered = Vec::new();

    for candidate in &candidates {
        if let Ok(shortcut) = candidate.parse::<Shortcut>() {
            let handle = app_handle.clone();
            let name = candidate.to_string();
            if app.global_shortcut().on_shortcut(shortcut, move |_app, _sc, event| {
                if event.state() == ShortcutState::Pressed {
                    println!("[Hotkey] {} pressed -> toggling pet window", name);
                    if let Some(sm) = handle.try_state::<Arc<SettingsManager>>() {
                        toggle_pet_window(&handle, &sm);
                    }
                }
            }).is_ok() {
                registered.push(*candidate);
            }
        }
    }

    if !registered.is_empty() {
        println!("[Hotkey] Global shortcuts registered successfully: {:?}", registered);
    } else {
        println!("[Hotkey] Notice: Global hotkeys reserved by OS, fallback to tray click");
    }
    Ok(())
}
