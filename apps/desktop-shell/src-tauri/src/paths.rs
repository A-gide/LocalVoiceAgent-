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
/// 4. Standard per-user runtime config root (PR-003 target):
///    `%LOCALAPPDATA%\LocalVoiceAgent`, falling back to `%APPDATA%\LocalVoiceAgent`.
///
/// PR-003 boundary: user configuration belongs in the per-user runtime config root,
/// not in the repository.  A legacy in-repo `settings.json`/`services.json` is
/// imported once by [`migrate_legacy_runtime_config`] and never auto-deleted.
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

    // 4. Fallback to the per-user runtime config root.  %LOCALAPPDATA% is the
    // frozen target (PR-003 L1161); %APPDATA% stays as a last-resort fallback for
    // environments that do not define LOCALAPPDATA.
    let base = std::env::var("LOCALAPPDATA").or_else(|_| std::env::var("APPDATA"));
    if let Ok(base) = base {
        let p = PathBuf::from(base).join("LocalVoiceAgent");
        if !p.exists() {
            let _ = fs::create_dir_all(&p);
        }
        return p;
    }

    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

/// One entry of the redacted migration report (PR-003 L1163).
///
/// Carries a file name and an outcome only -- never a path, never a value, so the
/// report can be logged or attached to diagnostics without leaking anything.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MigrationEntry {
    pub file: String,
    pub outcome: MigrationOutcome,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MigrationOutcome {
    /// Nothing to do: the runtime root already had this file.
    AlreadyPresent,
    /// Copied from the legacy location and the original was backed up.
    Copied,
    /// The legacy file existed but could not be read.
    Failed,
}

impl MigrationEntry {
    /// A single redacted line, safe for logs and diagnostic exports.
    pub fn to_redacted_line(&self) -> String {
        format!("{}: {:?}", self.file, self.outcome)
    }
}

/// Import legacy in-repo runtime configuration into the per-user config root.
///
/// PR-003 steps: first-run copy/migrate; back up the original runtime file; emit a
/// redacted migration report.  Rollback note: the legacy file is left in place
/// (read-only import for one release) -- this function **never deletes** a user's
/// own file, it only copies it and records what happened.
pub fn migrate_legacy_runtime_config(legacy_dir: &Path) -> Vec<MigrationEntry> {
    let target_dir = get_app_dir();
    let mut report = Vec::new();

    for file in ["settings.json", "services.json", "user_profile.json"] {
        let target = target_dir.join(file);
        if target.exists() {
            report.push(MigrationEntry {
                file: file.to_string(),
                outcome: MigrationOutcome::AlreadyPresent,
            });
            continue;
        }
        let legacy = legacy_dir.join(file);
        if !legacy.is_file() {
            continue;
        }
        // Back up the original before importing it, so a failed migration can be
        // diagnosed from the exact bytes that were present.
        let backup = legacy.with_extension("json.migrated-backup");
        let _ = fs::copy(&legacy, &backup);
        match fs::copy(&legacy, &target) {
            Ok(_) => report.push(MigrationEntry {
                file: file.to_string(),
                outcome: MigrationOutcome::Copied,
            }),
            Err(_) => report.push(MigrationEntry {
                file: file.to_string(),
                outcome: MigrationOutcome::Failed,
            }),
        }
    }

    report
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
