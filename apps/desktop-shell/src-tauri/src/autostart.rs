//! Windows Registry Autostart Manager (HKCU\Software\Microsoft\Windows\CurrentVersion\Run)
//! Conforms to Reviewer requirements:
//! - Default OFF
//! - Reversible via settings panel
//! - Cleans up on uninstall
//! - S1: Strictly quotes path to handle spaces and unicode/Chinese characters safely.

use std::path::Path;

#[cfg(windows)]
extern "system" {
    fn RegOpenKeyExW(
        h_key: isize,
        lp_sub_key: *const u16,
        ul_options: u32,
        sam_desired: u32,
        phk_result: *mut isize,
    ) -> i32;

    fn RegQueryValueExW(
        h_key: isize,
        lp_value_name: *const u16,
        lp_reserved: *mut u32,
        lp_type: *mut u32,
        lp_data: *mut u8,
        lpcb_data: *mut u32,
    ) -> i32;

    fn RegSetValueExW(
        h_key: isize,
        lp_value_name: *const u16,
        reserved: u32,
        dw_type: u32,
        lp_data: *const u8,
        cb_data: u32,
    ) -> i32;

    fn RegDeleteValueW(
        h_key: isize,
        lp_value_name: *const u16,
    ) -> i32;

    fn RegCloseKey(h_key: isize) -> i32;
}

const HKEY_CURRENT_USER: isize = 0x80000001u32 as i32 as isize;
const KEY_READ: u32 = 0x20019;
const KEY_WRITE: u32 = 0x20006;
const REG_SZ: u32 = 1;
const ERROR_SUCCESS: i32 = 0;
const SUBKEY: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
const VALUE_NAME: &str = "LocalVoiceAgentPet";

fn to_wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// S1: Format executable path into quoted registry command string, safely handling spaces and Chinese/unicode paths.
pub fn format_autostart_command(exe_path: &Path) -> String {
    format!("\"{}\"", exe_path.display())
}

/// Query whether autostart is currently registered in HKCU\...\Run.
pub fn is_autostart_enabled() -> bool {
    #[cfg(windows)]
    unsafe {
        let subkey_w = to_wide(SUBKEY);
        let mut hkey: isize = 0;
        if RegOpenKeyExW(HKEY_CURRENT_USER, subkey_w.as_ptr(), 0, KEY_READ, &mut hkey) != ERROR_SUCCESS {
            return false;
        }
        let val_w = to_wide(VALUE_NAME);
        let mut val_type: u32 = 0;
        let mut data_len: u32 = 0;
        let ret = RegQueryValueExW(
            hkey,
            val_w.as_ptr(),
            std::ptr::null_mut(),
            &mut val_type,
            std::ptr::null_mut(),
            &mut data_len,
        );
        RegCloseKey(hkey);
        ret == ERROR_SUCCESS && val_type == REG_SZ && data_len > 0
    }
    #[cfg(not(windows))]
    {
        false
    }
}

/// Enable or disable autostart in HKCU\...\Run.
pub fn set_autostart_enabled(enabled: bool) -> Result<(), String> {
    #[cfg(windows)]
    unsafe {
        let subkey_w = to_wide(SUBKEY);
        let mut hkey: isize = 0;
        let open_res = RegOpenKeyExW(HKEY_CURRENT_USER, subkey_w.as_ptr(), 0, KEY_WRITE, &mut hkey);
        if open_res != ERROR_SUCCESS {
            return Err(format!("Failed to open registry Run key: error code {}", open_res));
        }

        let val_w = to_wide(VALUE_NAME);
        let result = if enabled {
            let exe_path = std::env::current_exe()
                .map_err(|e| format!("Cannot get current_exe: {}", e))?;
            let cmd_str = format_autostart_command(&exe_path);
            let cmd_w = to_wide(&cmd_str);
            let byte_len = (cmd_w.len() * 2) as u32;
            let set_res = RegSetValueExW(
                hkey,
                val_w.as_ptr(),
                0,
                REG_SZ,
                cmd_w.as_ptr() as *const u8,
                byte_len,
            );
            if set_res == ERROR_SUCCESS {
                Ok(())
            } else {
                Err(format!("Failed to set autostart registry value: error code {}", set_res))
            }
        } else {
            let del_res = RegDeleteValueW(hkey, val_w.as_ptr());
            if del_res == ERROR_SUCCESS || del_res == 2 {
                // 2 = ERROR_FILE_NOT_FOUND (already clean)
                Ok(())
            } else {
                Err(format!("Failed to delete autostart registry value: error code {}", del_res))
            }
        };

        RegCloseKey(hkey);
        result
    }
    #[cfg(not(windows))]
    {
        Err("Autostart is only supported on Windows".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn test_format_autostart_command_with_spaces_and_unicode() {
        let path = PathBuf::from(r"C:\Program Files\LocalVoiceAgent 测试\lva-pet.exe");
        let formatted = format_autostart_command(&path);
        assert_eq!(formatted, r#""C:\Program Files\LocalVoiceAgent 测试\lva-pet.exe""#);
    }
}
