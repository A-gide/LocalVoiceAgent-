use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, WebviewUrl, WebviewWindowBuilder,
};
use crate::process_manager::ProcessManager;
use crate::settings::SettingsManager;
use std::sync::Arc;
use std::time::{Duration, Instant};

#[cfg(windows)]
pub fn show_native_message(title: &str, text: &str, is_error: bool) {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    let title_w: Vec<u16> = OsStr::new(title).encode_wide().chain(Some(0)).collect();
    let text_w: Vec<u16> = OsStr::new(text).encode_wide().chain(Some(0)).collect();
    let u_type = (if is_error { 0x00000010 /* MB_ICONERROR */ } else { 0x00000040 /* MB_ICONINFORMATION */ })
        | 0x00040000 /* MB_TOPMOST */
        | 0x00010000 /* MB_SETFOREGROUND */;
    unsafe {
        extern "system" {
            fn MessageBoxW(
                hWnd: *mut std::ffi::c_void,
                lpText: *const u16,
                lpCaption: *const u16,
                uType: u32,
            ) -> i32;
        }
        MessageBoxW(std::ptr::null_mut(), text_w.as_ptr(), title_w.as_ptr(), u_type);
    }
}

#[cfg(not(windows))]
pub fn show_native_message(title: &str, text: &str, is_error: bool) {
    if is_error {
        eprintln!("{}: {}", title, text);
    } else {
        println!("{}: {}", title, text);
    }
}

pub fn setup_tray(
    app: &AppHandle,
    process_mgr: Arc<ProcessManager>,
    settings_mgr: Arc<SettingsManager>,
) -> Result<(), Box<dyn std::error::Error>> {
    let toggle_i = MenuItem::with_id(app, "toggle", "显示/休眠宠物 (Alt+V / Ctrl+Space)", true, None::<&str>)?;
    let chat_i = MenuItem::with_id(app, "chat", "打开对话 (Chat)", true, None::<&str>)?;
    let memory_i = MenuItem::with_id(app, "memory", "记忆管理 (Journal v2)", true, None::<&str>)?;
    let select_model_i = MenuItem::with_id(app, "select_model", "选择/切换 LLM 模型 (Model)", true, None::<&str>)?;
    let settings_i = MenuItem::with_id(app, "settings", "设置与控制面板 (Settings)", true, None::<&str>)?;
    let sep1 = PredefinedMenuItem::separator(app)?;
    let live_i = MenuItem::with_id(app, "live", "唤醒宠物 (加载 Live2D)", true, None::<&str>)?;
    let screenpipe_i = MenuItem::with_id(app, "screenpipe", "被动记录 (Screenpipe) 状态", true, None::<&str>)?;
    let sep2 = PredefinedMenuItem::separator(app)?;
    let status_i = MenuItem::with_id(app, "status", "服务状态检测", true, None::<&str>)?;
    let glass_i = MenuItem::with_id(app, "toggle_glass", "切换显示风格 (透明 / 玻璃卡片)", true, None::<&str>)?;
    let sep3 = PredefinedMenuItem::separator(app)?;
    let quit_i = MenuItem::with_id(app, "quit", "退出 (关闭应用)", true, None::<&str>)?;

    let menu = Menu::with_items(
        app,
        &[
            &toggle_i,
            &chat_i,
            &memory_i,
            &select_model_i,
            &settings_i,
            &sep1,
            &live_i,
            &screenpipe_i,
            &sep2,
            &status_i,
            &glass_i,
            &sep3,
            &quit_i,
        ],
    )?;

    let app_handle = app.clone();
    let pm = process_mgr.clone();
    let sm_menu = settings_mgr.clone();
    let sm_click = settings_mgr.clone();

    let _tray = TrayIconBuilder::with_id("lva-tray")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, event| {
            let id = event.id().as_ref();
            match id {
                "toggle" => {
                    toggle_pet_window(app, &sm_menu);
                }
                "chat" => {
                    open_chat_window(app);
                }
                "memory" => {
                    open_memory_window(app);
                }
                "select_model" => {
                    open_settings_window(app);
                }
                "settings" => {
                    open_settings_window(app);
                }
                "live" => {
                    show_or_create_pet_window(app);
                }
                "screenpipe" => {
                    let is_up = ProcessManager::is_port_listening(3030);
                    let status_msg = if is_up {
                        "【Screenpipe 捕获系统】\n\n状态：运行中 (端口 3030 监听中)\n模式：后台被动捕获\n数据存储：screenpipe-data/".to_string()
                    } else {
                        "【Screenpipe 捕获系统】\n\n状态：未运行 (端口 3030 未监听)\n提示：可通过设置或外部实例启动。".to_string()
                    };
                    std::thread::spawn(move || {
                        show_native_message("Screenpipe 状态", &status_msg, !is_up);
                    });
                }
                "status" => {
                    let st = pm.get_status();
                    let hub_str = if st.llama_server.is_running {
                        format!("运行中 (端口: {})", st.llama_server.port)
                    } else {
                        "未连接 / 离线".to_string()
                    };
                    let screenpipe_str = if st.screenpipe.is_running {
                        "运行中 (端口: 3030)".to_string()
                    } else {
                        "未运行".to_string()
                    };
                    let report = format!(
                        "【LocalVoiceAgent 服务状态检测】\n\n• llama.cpp-hub 模型服务:\n   {}\n\n• Screenpipe 记忆捕获:\n   {}\n\n• 架构模式: 单一 Conversation Authority (LVA Core)",
                        hub_str, screenpipe_str
                    );
                    std::thread::spawn(move || {
                        show_native_message("LocalVoiceAgent 服务检测", &report, false);
                    });
                }
                "toggle_glass" => {
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.eval("document.body.classList.toggle('glass-card');");
                    }
                }
                "quit" => {
                    pm.shutdown_all_services();
                    std::process::exit(0);
                }
                _ => {}
            }
        })
        .on_tray_icon_event(move |_tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                toggle_pet_window(&app_handle, &sm_click);
            }
        })
        .build(app)?;

    Ok(())
}

/// Open Settings Window with single-page app index.html auto-routing
pub fn open_settings_window(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("settings") {
        let _ = w.show();
        let _ = w.set_focus();
        return;
    }

    let builder = WebviewWindowBuilder::new(
        app,
        "settings",
        WebviewUrl::App("index.html".into()),
    )
    .title("LocalVoiceAgent 设置与控制面板")
    .inner_size(800.0, 750.0)
    .resizable(true)
    .decorations(true)
    .always_on_top(false)
    .skip_taskbar(false);

    match builder.build() {
        Ok(w) => {
            let w_clone = w.clone();
            w.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = w_clone.destroy();
                    std::thread::spawn(|| {
                        std::thread::sleep(Duration::from_millis(150));
                        #[cfg(windows)]
                        trim_working_set();
                    });
                }
            });
            let _ = w.show();
            let _ = w.set_focus();
        }
        Err(e) => {
            eprintln!("[Settings] Failed to open settings window: {}", e);
            show_native_message("打开设置失败", &format!("无法创建设置窗口：{}", e), true);
        }
    }
}

/// Open Chat Window with single-page app index.html auto-routing
pub fn open_chat_window(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("chat") {
        let _ = w.show();
        let _ = w.set_focus();
        return;
    }

    let builder = WebviewWindowBuilder::new(
        app,
        "chat",
        WebviewUrl::App("index.html".into()),
    )
    .title("LocalVoiceAgent 对话记录")
    .inner_size(560.0, 720.0)
    .resizable(true)
    .decorations(true)
    .always_on_top(false)
    .skip_taskbar(false);

    match builder.build() {
        Ok(w) => {
            let w_clone = w.clone();
            w.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = w_clone.destroy();
                    std::thread::spawn(|| {
                        std::thread::sleep(Duration::from_millis(150));
                        #[cfg(windows)]
                        trim_working_set();
                    });
                }
            });
            let _ = w.show();
            let _ = w.set_focus();
        }
        Err(e) => {
            eprintln!("[Chat] Failed to open chat window: {}", e);
            show_native_message("打开对话窗口失败", &format!("无法创建对话窗口：{}", e), true);
        }
    }
}

/// Open Memory Window with single-page app index.html auto-routing
pub fn open_memory_window(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("memory") {
        let _ = w.show();
        let _ = w.set_focus();
        return;
    }

    let builder = WebviewWindowBuilder::new(
        app,
        "memory",
        WebviewUrl::App("index.html".into()),
    )
    .title("LocalVoiceAgent 长期记忆管理 (Journal v2)")
    .inner_size(780.0, 720.0)
    .resizable(true)
    .decorations(true)
    .always_on_top(false)
    .skip_taskbar(false);

    match builder.build() {
        Ok(w) => {
            let w_clone = w.clone();
            w.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = w_clone.destroy();
                    std::thread::spawn(|| {
                        std::thread::sleep(Duration::from_millis(150));
                        #[cfg(windows)]
                        trim_working_set();
                    });
                }
            });
            let _ = w.show();
            let _ = w.set_focus();
        }
        Err(e) => {
            eprintln!("[Memory] Failed to open memory window: {}", e);
            show_native_message("打开记忆窗口失败", &format!("无法创建记忆窗口：{}", e), true);
        }
    }
}

/// Windows working set trimming to physically reclaim discarded pages on dormancy
#[cfg(windows)]
pub fn trim_working_set() {
    unsafe {
        extern "system" {
            fn GetCurrentProcess() -> *mut std::ffi::c_void;
            fn SetProcessWorkingSetSize(
                hProcess: *mut std::ffi::c_void,
                dwMinimumWorkingSetSize: usize,
                dwMaximumWorkingSetSize: usize,
            ) -> i32;
        }
        let handle = GetCurrentProcess();
        SetProcessWorkingSetSize(handle, usize::MAX, usize::MAX);
    }
}

/// P1 closure & M4: Toggle Pet Window with genuine dormancy destroy / dynamic rebuild
pub fn toggle_pet_window(app: &AppHandle, sm: &SettingsManager) {
    let dormancy = sm.get_settings().pet_dormancy_mode;

    if let Some(window) = app.get_webview_window("main") {
        if dormancy {
            // P1 closure: True Dormancy -> Destroy WebView2 window instance
            // Releases all ~440MB WebView2 GPU/Renderer child processes
            let _ = window.destroy();
            println!("[Dormancy] Pet WebView2 destroyed -> Shell entering standby.");
            std::thread::spawn(|| {
                std::thread::sleep(Duration::from_millis(150));
                #[cfg(windows)]
                trim_working_set();
            });
        } else {
            let _ = window.eval("if (window.setSuspended) window.setSuspended(true);");
            let _ = window.hide();
        }
    } else {
        // Recreate dynamically
        show_or_create_pet_window(app);
    }
}

pub fn show_or_create_pet_window(app: &AppHandle) -> f64 {
    let t0 = Instant::now();
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
        let _ = window.eval("if (window.setSuspended) window.setSuspended(false);");
        return (t0.elapsed().as_secs_f64() * 1000.0).round();
    }

    let builder = WebviewWindowBuilder::new(
        app,
        "main",
        WebviewUrl::App("index.html".into()),
    )
    .title("LocalVoiceAgent Pet")
    .inner_size(360.0, 520.0)
    .resizable(false)
    .fullscreen(false)
    .transparent(true)
    .decorations(false)
    .always_on_top(true)
    .skip_taskbar(false)
    .shadow(false);

    match builder.build() {
        Ok(window) => {
            let w_clone = window.clone();
            window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = w_clone.destroy();
                    std::thread::spawn(|| {
                        std::thread::sleep(Duration::from_millis(150));
                        #[cfg(windows)]
                        trim_working_set();
                    });
                }
            });
            let elapsed_ms = (t0.elapsed().as_secs_f64() * 1000.0).round();
            println!("[Rebuild] Tauri WebviewWindowBuilder finished in {:.1} ms", elapsed_ms);
            elapsed_ms
        }
        Err(e) => {
            eprintln!("[Rebuild] Failed to rebuild pet window: {}", e);
            0.0
        }
    }
}