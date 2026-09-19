// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(windows)]
fn enforce_single_instance() -> bool {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;

    let name: Vec<u16> = OsStr::new("Local\\lva_pet_single_instance_mutex_v1")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    extern "system" {
        fn CreateMutexW(
            lpMutexAttributes: *mut std::ffi::c_void,
            bInitialOwner: i32,
            lpName: *const u16,
        ) -> *mut std::ffi::c_void;
        fn GetLastError() -> u32;
    }

    unsafe {
        let handle = CreateMutexW(std::ptr::null_mut(), 1, name.as_ptr());
        if GetLastError() == 183 { // ERROR_ALREADY_EXISTS = 183
            return false;
        }
        let _ = handle;
    }
    true
}

#[cfg(windows)]
fn signal_event(name: &str) {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;

    let event_name: Vec<u16> = OsStr::new(name)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    extern "system" {
        fn OpenEventW(dwDesiredAccess: u32, bInheritHandle: i32, lpName: *const u16) -> *mut std::ffi::c_void;
        fn SetEvent(hEvent: *mut std::ffi::c_void) -> i32;
        fn CloseHandle(hObject: *mut std::ffi::c_void) -> i32;
    }

    unsafe {
        let h = OpenEventW(0x0002, 0, event_name.as_ptr()); // EVENT_MODIFY_STATE = 0x0002
        if !h.is_null() {
            SetEvent(h);
            CloseHandle(h);
        }
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let is_dormancy = args.iter().any(|a| a == "--dormancy" || a == "--destroy");

    #[cfg(windows)]
    if !enforce_single_instance() {
        if is_dormancy {
            signal_event("Local\\lva_pet_dormancy_event_v1");
            eprintln!("[SingleInstance] Signaled dormancy destroy event to running instance.");
        } else {
            signal_event("Local\\lva_pet_toggle_event_v1");
            eprintln!("[SingleInstance] Another instance is already running. Signaled wake event and exiting cleanly.");
        }
        std::process::exit(0);
    }

    lva_pet_lib::run();
}