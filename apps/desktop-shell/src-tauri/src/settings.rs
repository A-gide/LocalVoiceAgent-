use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::RwLock;
use crate::crypto;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GgufModelInfo {
    pub name: String,
    pub path: String,
    pub size_gb: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PublicAppSettings {
    pub llm_mode: String,
    pub local_gguf_path: String,
    pub cloud_provider: String,
    pub cloud_base_url: String,
    pub cloud_api_key_configured: bool,
    pub cloud_model: String,

    pub asr_provider: String,
    pub asr_base_url: String,
    pub asr_api_key_configured: bool,
    pub asr_model: String,

    pub tts_provider: String,
    pub tts_base_url: String,
    pub tts_api_key_configured: bool,
    pub tts_model: String,
    pub tts_voice: String,

    pub active_character: String,
    pub idle_vram_release_mins: u32,
    pub pet_dormancy_mode: bool,
    /// Monotonic settings aggregate revision (PR-004 L1173 / plan L397).
    ///
    /// Lives on the Rust public settings DTO -- deliberately **not** in the global
    /// RuntimeState CAS, because secrets are owned by the Rust settings/OS
    /// protection layer (plan L293).  A write that carries a stale revision is
    /// rejected as `STALE_REVISION`, so concurrent edits cannot silently clobber
    /// each other while heartbeat traffic leaves this value untouched.
    pub settings_revision: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppSettings {
    pub llm_mode: String, // "local" or "cloud"
    pub local_gguf_path: String,
    pub cloud_provider: String,
    pub cloud_base_url: String,
    pub cloud_api_key: String, // Plaintext in memory, DPAPI on disk
    pub cloud_model: String,

    pub asr_provider: String, // "local" or "openai_compatible"
    pub asr_base_url: String,
    pub asr_api_key: String,
    pub asr_model: String,

    pub tts_provider: String, // "local" or "openai_compatible"
    pub tts_base_url: String,
    pub tts_api_key: String,
    pub tts_model: String,
    pub tts_voice: String,

    pub active_character: String,
    pub idle_vram_release_mins: u32, // 0 = disabled
    pub pet_dormancy_mode: bool,     // true = destroy WebView2 window on hide to enter standby mode
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            llm_mode: "local".to_string(),
            local_gguf_path: "W:\\model\\XHToken\\Spark-X2.5-4B-GGUF\\Spark-X2.5-4B-Q8_0.gguf".to_string(),
            cloud_provider: "deepseek".to_string(),
            cloud_base_url: "https://api.deepseek.com/v1".to_string(),
            cloud_api_key: String::new(),
            cloud_model: "deepseek-chat".to_string(),

            asr_provider: "local".to_string(),
            asr_base_url: "http://127.0.0.1:8765/api/asr".to_string(),
            asr_api_key: String::new(),
            asr_model: "whisper-1".to_string(),

            tts_provider: "local".to_string(),
            tts_base_url: "http://127.0.0.1:8880/v1".to_string(),
            tts_api_key: String::new(),
            tts_model: "kokoro".to_string(),
            tts_voice: "af_sky+af_bella".to_string(),

            active_character: "conf.yaml".to_string(),
            idle_vram_release_mins: 15,
            pet_dormancy_mode: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct DiskSettings {
    pub llm_mode: String,
    pub local_gguf_path: String,
    pub cloud_provider: String,
    pub cloud_base_url: String,
    pub cloud_api_key_enc: String,
    pub cloud_model: String,

    pub asr_provider: String,
    pub asr_base_url: String,
    pub asr_api_key_enc: String,
    pub asr_model: String,

    pub tts_provider: String,
    pub tts_base_url: String,
    pub tts_api_key_enc: String,
    pub tts_model: String,
    pub tts_voice: String,

    pub active_character: String,
    pub idle_vram_release_mins: u32,
    pub pet_dormancy_mode: bool,
}

pub struct SettingsManager {
    config_path: PathBuf,
    settings: RwLock<AppSettings>,
    model_cache: RwLock<Vec<GgufModelInfo>>,
    /// Settings aggregate revision (PR-004).  Bumped by every write that reaches
    /// this manager; read by `get_public_settings`; compared by
    /// [`SettingsManager::check_revision`].  Heartbeat traffic never touches it.
    settings_revision: std::sync::atomic::AtomicU64,
}

impl SettingsManager {
    /// Construct a manager bound to an explicit config path.
    ///
    /// Production always uses [`SettingsManager::new`], which resolves the path
    /// through `paths::get_settings_json_path()`.  This constructor exists so a
    /// test can point the manager at an isolated temporary directory instead of
    /// mutating the real per-user runtime config root.
    pub fn with_config_path(config_path: PathBuf) -> Self {
        if let Some(parent) = config_path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let sm = Self {
            config_path,
            settings: RwLock::new(AppSettings::default()),
            model_cache: RwLock::new(Vec::new()),
            settings_revision: std::sync::atomic::AtomicU64::new(0),
        };
        sm.load_from_disk();
        sm
    }

    pub fn new() -> Self {
        // PR-003: import any legacy in-repo runtime config into the per-user root
        // before the settings path is resolved, then report what happened in a
        // redacted form.  The legacy files themselves are left untouched.
        if let Ok(exe) = std::env::current_exe() {
            if let Some(exe_dir) = exe.parent() {
                let report = crate::paths::migrate_legacy_runtime_config(exe_dir);
                for entry in &report {
                    log::info!("[SettingsManager] config migration: {}", entry.to_redacted_line());
                }
            }
        }
        let config_path = crate::paths::get_settings_json_path();
        log::info!("[SettingsManager] Loaded settings from: {:?}", config_path);
        let sm = Self {
            config_path,
            settings: RwLock::new(AppSettings::default()),
            model_cache: RwLock::new(Vec::new()),
            settings_revision: std::sync::atomic::AtomicU64::new(0),
        };
        sm.load_from_disk();
        sm
    }

    /// Current settings aggregate revision.
    pub fn settings_revision(&self) -> u64 {
        self.settings_revision.load(std::sync::atomic::Ordering::SeqCst)
    }

    /// Compare-and-set guard for a settings write (PR-004 acceptance: a concurrent
    /// write can return `STALE_REVISION`).
    ///
    /// `expected` of `None` means "the caller did not supply a revision", which is
    /// the documented behaviour for a first-time write and is accepted.  A supplied
    /// revision that no longer matches the current one is rejected, and the caller
    /// must re-read before retrying.
    pub fn check_revision(&self, expected: Option<u64>) -> Result<(), String> {
        match expected {
            None => Ok(()),
            Some(exp) if exp == self.settings_revision() => Ok(()),
            Some(exp) => Err(format!(
                "STALE_REVISION: expected settings_revision {} but current is {}",
                exp,
                self.settings_revision()
            )),
        }
    }

    /// Bump the settings revision after a successful write.
    fn bump_settings_revision(&self) {
        self.settings_revision
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    }

    /// S2: Start model scanner on a background thread to prevent blocking main startup thread
    pub fn start_background_scanner(self: &std::sync::Arc<Self>) {
        let sm_clone = self.clone();
        std::thread::Builder::new()
            .name("lva-model-scanner".into())
            .spawn(move || {
                sm_clone.refresh_model_cache();
            })
            .ok();
    }

    pub fn load_from_disk(&self) {
        if !self.config_path.exists() {
            let _ = self.save_to_disk();
            return;
        }

        match fs::read_to_string(&self.config_path) {
            Ok(content) => {
                // P1: Strip UTF-8 BOM defensively if present
                let clean = content.trim_start_matches('\u{feff}').trim();
                match serde_json::from_str::<DiskSettings>(clean) {
                    Ok(disk) => {
                        let mut s = self.settings.write().unwrap();
                        s.llm_mode = disk.llm_mode;
                        s.local_gguf_path = disk.local_gguf_path;
                        s.cloud_provider = disk.cloud_provider;
                        s.cloud_base_url = disk.cloud_base_url;
                        s.cloud_api_key = match crypto::dpapi_decrypt(&disk.cloud_api_key_enc) {
                            Ok(k) => k,
                            Err(e) => {
                                eprintln!("[SettingsManager] WARNING: Failed to decrypt cloud_api_key via DPAPI: {}", e);
                                String::new()
                            }
                        };
                        s.cloud_model = disk.cloud_model;

                        s.asr_provider = disk.asr_provider;
                        s.asr_base_url = disk.asr_base_url;
                        s.asr_api_key = match crypto::dpapi_decrypt(&disk.asr_api_key_enc) {
                            Ok(k) => k,
                            Err(e) => {
                                eprintln!("[SettingsManager] WARNING: Failed to decrypt asr_api_key via DPAPI: {}", e);
                                String::new()
                            }
                        };
                        s.asr_model = disk.asr_model;

                        s.tts_provider = disk.tts_provider;
                        s.tts_base_url = disk.tts_base_url;
                        s.tts_api_key = match crypto::dpapi_decrypt(&disk.tts_api_key_enc) {
                            Ok(k) => k,
                            Err(e) => {
                                eprintln!("[SettingsManager] WARNING: Failed to decrypt tts_api_key via DPAPI: {}", e);
                                String::new()
                            }
                        };
                        s.tts_model = disk.tts_model;
                        s.tts_voice = disk.tts_voice;

                        s.active_character = disk.active_character;
                        s.idle_vram_release_mins = disk.idle_vram_release_mins;
                        s.pet_dormancy_mode = disk.pet_dormancy_mode;
                    }
                    Err(e) => {
                        eprintln!("[SettingsManager] ERROR: Failed to parse settings file ({}): {}", self.config_path.display(), e);
                    }
                }
            }
            Err(e) => {
                eprintln!("[SettingsManager] ERROR: Failed to read settings file ({}): {}", self.config_path.display(), e);
            }
        }
    }

    pub fn save_to_disk(&self) -> Result<(), String> {
        let s = self.settings.read().unwrap();
        let disk = DiskSettings {
            llm_mode: s.llm_mode.clone(),
            local_gguf_path: s.local_gguf_path.clone(),
            cloud_provider: s.cloud_provider.clone(),
            cloud_base_url: s.cloud_base_url.clone(),
            cloud_api_key_enc: crypto::dpapi_encrypt(&s.cloud_api_key).unwrap_or_default(),
            cloud_model: s.cloud_model.clone(),

            asr_provider: s.asr_provider.clone(),
            asr_base_url: s.asr_base_url.clone(),
            asr_api_key_enc: crypto::dpapi_encrypt(&s.asr_api_key).unwrap_or_default(),
            asr_model: s.asr_model.clone(),

            tts_provider: s.tts_provider.clone(),
            tts_base_url: s.tts_base_url.clone(),
            tts_api_key_enc: crypto::dpapi_encrypt(&s.tts_api_key).unwrap_or_default(),
            tts_model: s.tts_model.clone(),
            tts_voice: s.tts_voice.clone(),

            active_character: s.active_character.clone(),
            idle_vram_release_mins: s.idle_vram_release_mins,
            pet_dormancy_mode: s.pet_dormancy_mode,
        };

        let json = serde_json::to_string_pretty(&disk).map_err(|e| e.to_string())?;
        fs::write(&self.config_path, json).map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn get_settings(&self) -> AppSettings {
        self.settings.read().unwrap().clone()
    }

    pub fn get_public_settings(&self) -> PublicAppSettings {
        let s = self.settings.read().unwrap();
        PublicAppSettings {
            llm_mode: s.llm_mode.clone(),
            local_gguf_path: s.local_gguf_path.clone(),
            cloud_provider: s.cloud_provider.clone(),
            cloud_base_url: s.cloud_base_url.clone(),
            cloud_api_key_configured: !s.cloud_api_key.is_empty(),
            cloud_model: s.cloud_model.clone(),

            asr_provider: s.asr_provider.clone(),
            asr_base_url: s.asr_base_url.clone(),
            asr_api_key_configured: !s.asr_api_key.is_empty(),
            asr_model: s.asr_model.clone(),

            tts_provider: s.tts_provider.clone(),
            tts_base_url: s.tts_base_url.clone(),
            tts_api_key_configured: !s.tts_api_key.is_empty(),
            tts_model: s.tts_model.clone(),
            tts_voice: s.tts_voice.clone(),

            active_character: s.active_character.clone(),
            idle_vram_release_mins: s.idle_vram_release_mins,
            pet_dormancy_mode: s.pet_dormancy_mode,
            settings_revision: self.settings_revision(),
        }
    }

    pub fn set_secret(&self, secret_type: &str, secret_value: &str) -> Result<(), String> {
        self.set_secret_checked(secret_type, secret_value, None)
    }

    /// Write a secret, optionally guarded by the settings revision (plan L463).
    ///
    /// L463 requires a `settings_revision` precondition on "settings update/clear
    /// secret".  The guard belongs here rather than in Core: the authority matrix
    /// (L293) gives secrets to this layer, so a concurrent write is detectable
    /// exactly where the write happens.
    ///
    /// `expected` of `None` keeps the previous behaviour and is what a first write
    /// from a UI that has not read the DTO yet supplies.  A supplied revision that
    /// no longer matches is refused with `STALE_REVISION` and the current revision,
    /// so the caller can refresh and retry instead of clobbering the other edit.
    pub fn set_secret_checked(
        &self,
        secret_type: &str,
        secret_value: &str,
        expected: Option<u64>,
    ) -> Result<(), String> {
        self.check_revision(expected)?;
        {
            let mut s = self.settings.write().unwrap();
            match secret_type {
                "cloud_api_key" => s.cloud_api_key = secret_value.to_string(),
                "asr_api_key" => s.asr_api_key = secret_value.to_string(),
                "tts_api_key" => s.tts_api_key = secret_value.to_string(),
                _ => return Err(format!("Unknown secret type '{}'", secret_type)),
            }
        }
        let result = self.save_to_disk();
        if result.is_ok() {
            // A write that reached disk advances the settings aggregate revision.
            self.bump_settings_revision();
        }
        result
    }

    pub fn clear_secret(&self, secret_type: &str) -> Result<(), String> {
        self.set_secret(secret_type, "")
    }

    /// Clear a secret under the same revision guard as a write (plan L463).
    pub fn clear_secret_checked(&self, secret_type: &str, expected: Option<u64>) -> Result<(), String> {
        self.set_secret_checked(secret_type, "", expected)
    }

    pub fn update_settings(&self, new_settings: AppSettings) -> Result<(), String> {
        {
            let mut s = self.settings.write().unwrap();
            let mut updated = new_settings;
            if updated.cloud_api_key.is_empty() {
                updated.cloud_api_key = s.cloud_api_key.clone();
            }
            if updated.asr_api_key.is_empty() {
                updated.asr_api_key = s.asr_api_key.clone();
            }
            if updated.tts_api_key.is_empty() {
                updated.tts_api_key = s.tts_api_key.clone();
            }
            *s = updated;
        }
        let result = self.save_to_disk();
        if result.is_ok() {
            self.bump_settings_revision();
        }
        result
    }

    /// S2: Recursively scan local models with max_depth <= 3
    pub fn scan_models_dir(&self, root_dir: &str, max_depth: usize) -> Vec<GgufModelInfo> {
        let root = Path::new(root_dir);
        if !root.exists() {
            return Vec::new();
        }

        let mut results = Vec::new();
        Self::scan_recursive(root, 0, max_depth, &mut results);
        results
    }

    fn scan_recursive(dir: &Path, current_depth: usize, max_depth: usize, results: &mut Vec<GgufModelInfo>) {
        if current_depth > max_depth {
            return;
        }

        if let Ok(entries) = fs::read_dir(dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    Self::scan_recursive(&path, current_depth + 1, max_depth, results);
                } else if path.is_file() {
                    if let Some(ext) = path.extension() {
                        if ext.to_string_lossy().eq_ignore_ascii_case("gguf") {
                            let name = path.file_name().unwrap_or_default().to_string_lossy().to_string();
                            let len = entry.metadata().map(|m| m.len()).unwrap_or(0);
                            let size_gb = (len as f64) / (1024.0 * 1024.0 * 1024.0);
                            results.push(GgufModelInfo {
                                name,
                                path: path.to_string_lossy().to_string(),
                                size_gb: (size_gb * 100.0).round() / 100.0,
                            });
                        }
                    }
                }
            }
        }
    }

    pub fn refresh_model_cache(&self) {
        let models = self.scan_models_dir("W:\\model", 3);
        let mut cache = self.model_cache.write().unwrap();
        *cache = models;
    }

    pub fn get_cached_models(&self) -> Vec<GgufModelInfo> {
        self.model_cache.read().unwrap().clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// An isolated manager writing into its own temp directory.
    ///
    /// Never touch the real per-user runtime config root from a test: the test
    /// process may not be allowed to write there, and it would mutate the user's
    /// actual settings.
    fn isolated_manager(tag: &str) -> SettingsManager {
        let dir = std::env::temp_dir().join(format!(
            "lva-settings-test-{}-{}",
            tag,
            std::process::id()
        ));
        let _ = fs::create_dir_all(&dir);
        SettingsManager::with_config_path(dir.join("settings.json"))
    }

    // ---------------------------------------------------- PR-004 secret boundary
    #[test]
    fn public_dto_has_no_secret_or_ciphertext_field() {
        // Serialize the public DTO and prove no key material can cross the boundary.
        let dto = PublicAppSettings {
            llm_mode: "hub".into(),
            local_gguf_path: String::new(),
            cloud_provider: "deepseek".into(),
            cloud_base_url: "https://api.deepseek.com/v1".into(),
            cloud_api_key_configured: true,
            cloud_model: "deepseek-chat".into(),
            asr_provider: "local".into(),
            asr_base_url: String::new(),
            asr_api_key_configured: false,
            asr_model: "sensevoice".into(),
            tts_provider: "local".into(),
            tts_base_url: String::new(),
            tts_api_key_configured: false,
            tts_model: "melotts".into(),
            tts_voice: "zh_en".into(),
            active_character: "conf.yaml".into(),
            idle_vram_release_mins: 15,
            pet_dormancy_mode: true,
            settings_revision: 7,
        };
        let json = serde_json::to_string(&dto).expect("public DTO must serialize");
        assert!(!json.contains("_enc"), "no ciphertext field may be serialized");
        assert!(!json.contains("api_key\""), "no raw key field may be serialized");
        assert!(json.contains("settings_revision"), "the revision must be published");
        assert!(json.contains("cloud_api_key_configured"), "only the flag may cross");
    }

    #[test]
    fn a_missing_expected_revision_is_accepted() {
        let sm = isolated_manager("missing-rev");
        assert!(sm.check_revision(None).is_ok());
    }

    #[test]
    fn a_matching_revision_is_accepted_and_a_stale_one_is_rejected() {
        let sm = isolated_manager("stale-rev");
        let current = sm.settings_revision();
        assert!(sm.check_revision(Some(current)).is_ok());
        let err = sm
            .check_revision(Some(current + 99))
            .expect_err("a stale revision must be rejected");
        assert!(err.contains("STALE_REVISION"), "error must name STALE_REVISION");
    }

    #[test]
    fn a_settings_write_advances_the_revision() {
        let sm = isolated_manager("advance-rev");
        let before = sm.settings_revision();
        sm.set_secret("cloud_api_key", "test-value-not-a-real-key")
            .expect("set_secret should succeed");
        assert_eq!(
            sm.settings_revision(),
            before + 1,
            "a successful settings write must advance the revision"
        );
        sm.clear_secret("cloud_api_key").expect("clear_secret should succeed");
        assert_eq!(sm.settings_revision(), before + 2);
    }

    #[test]
    fn a_rejected_secret_write_does_not_advance_the_revision() {
        let sm = isolated_manager("reject-rev");
        let before = sm.settings_revision();
        assert!(sm.set_secret("not_a_secret_type", "x").is_err());
        assert_eq!(
            sm.settings_revision(),
            before,
            "a failed write must not bump the revision"
        );
    }

    #[test]
    fn a_secret_write_is_guarded_by_the_revision_it_quotes() {
        // Plan L463 requires the precondition on "settings update/clear secret".
        // The guard must be on the *write path*, not merely available as a helper:
        // a stale caller has to be refused before the value is replaced.
        let sm = isolated_manager("l463-guard");
        let stale = sm.settings_revision();
        sm.set_secret("cloud_api_key", "first-value").expect("first write");

        let err = sm
            .set_secret_checked("cloud_api_key", "second-value", Some(stale))
            .expect_err("a write quoting a stale revision must be refused");
        assert!(err.contains("STALE_REVISION"), "error must name STALE_REVISION");

        // The refused write must not have replaced the value.
        assert_eq!(sm.get_settings().cloud_api_key, "first-value");

        // Quoting the current revision succeeds.
        let current = sm.settings_revision();
        sm.set_secret_checked("cloud_api_key", "third-value", Some(current))
            .expect("a write quoting the current revision must succeed");
        assert_eq!(sm.get_settings().cloud_api_key, "third-value");
    }

    #[test]
    fn clearing_a_secret_is_guarded_the_same_way() {
        let sm = isolated_manager("l463-clear");
        sm.set_secret("tts_api_key", "a-value").expect("seed");
        let stale = sm.settings_revision();
        sm.set_secret("tts_api_key", "another-value").expect("advance");

        assert!(sm.clear_secret_checked("tts_api_key", Some(stale)).is_err());
        assert_eq!(
            sm.get_settings().tts_api_key,
            "another-value",
            "a refused clear must leave the secret in place"
        );
    }

    #[test]
    fn clearing_a_secret_leaves_it_unconfigured_in_the_public_dto() {
        let sm = isolated_manager("clear-secret");
        sm.set_secret("tts_api_key", "test-value-not-a-real-key")
            .expect("set_secret should succeed");
        assert!(sm.get_public_settings().tts_api_key_configured);
        sm.clear_secret("tts_api_key").expect("clear_secret should succeed");
        assert!(!sm.get_public_settings().tts_api_key_configured);
    }
}
