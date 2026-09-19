use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

/// Check if a directory is writable by attempting to create and immediately delete a temporary test file.
pub fn is_directory_writable(dir: &Path) -> bool {
    if !dir.is_dir() {
        return false;
    }
    let test_file = dir.join(format!(".lva_write_probe_{}", std::process::id()));
    match OpenOptions::new().create(true).write(true).open(&test_file) {
        Ok(mut f) => {
            let _ = f.write_all(b"probe");
            drop(f);
            let _ = fs::remove_file(&test_file);
            true
        }
        Err(_) => false,
    }
}

/// Resolve the configuration and runtime root directory.
/// Precedence rules (conforming to M1):
/// 1. Environment variable override `LVA_ROOT` or `LVA_CONFIG_DIR` (if set and exists).
/// 2. Portable mode next to exe:
///    Requires EITHER explicit `.portable` marker file OR existing `services.json`/`settings.json`
///    AND the executable directory MUST be writable!
/// 3. Development / Test repository hierarchy:
///    Walk up parent directories (up to 5 levels) to check for `services.json` in workspace root.
/// 4. Standard User AppData directory:
///    `%APPDATA%\LocalVoiceAgent`.
pub fn get_app_dir() -> PathBuf {
    // 1. Env var override
    if let Ok(env_root) = std::env::var("LVA_ROOT") {
        let p = PathBuf::from(env_root);
        if p.exists() {
            return p;
        }
    }
    if let Ok(env_cfg) = std::env::var("LVA_CONFIG_DIR") {
        let p = PathBuf::from(env_cfg);
        if p.exists() {
            return p;
        }
    }

    // Inspect executable location
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            // 2. Portable mode: must have marker or config AND must be writable
            let has_portable_marker = exe_dir.join(".portable").exists();
            let has_local_config = exe_dir.join("services.json").exists() || exe_dir.join("settings.json").exists();
            let is_in_target = exe_dir.to_string_lossy().replace('/', "\\").contains(r"\target\");

            if (has_portable_marker || has_local_config) && !is_in_target && is_directory_writable(exe_dir) {
                return exe_dir.to_path_buf();
            }

            // 3. Development / Test repository root: walk up from target/debug or target/release
            let mut cur = exe_dir;
            for _ in 0..5 {
                if let Some(parent) = cur.parent() {
                    if parent.join("services.json").exists() && parent.join("apps").exists() {
                        return parent.to_path_buf();
                    }
                    cur = parent;
                }
            }
        }
    }

    // 4. Fallback to %APPDATA%\LocalVoiceAgent
    if let Ok(appdata) = std::env::var("APPDATA") {
        let p = PathBuf::from(appdata).join("LocalVoiceAgent");
        if !p.exists() {
            let _ = fs::create_dir_all(&p);
        }
        return p;
    }

    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

pub fn get_services_json_path() -> PathBuf {
    let app_dir = get_app_dir();
    let direct = app_dir.join("services.json");
    if direct.exists() {
        return direct;
    }
    // If not in app_dir (e.g. fresh %APPDATA%), check if a default template exists next to exe
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let template = dir.join("services.default.json");
            if template.exists() {
                let _ = fs::copy(&template, &direct);
                return direct;
            }
        }
    }
    direct
}

pub fn get_settings_json_path() -> PathBuf {
    let app_dir = get_app_dir();
    let direct = app_dir.join("settings.json");
    if direct.exists() {
        return direct;
    }
    // If not in app_dir, check if default template exists
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let template = dir.join("settings.default.json");
            if template.exists() {
                let _ = fs::copy(&template, &direct);
                return direct;
            }
        }
    }
    direct
}
