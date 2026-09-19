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
            asr_base_url: "http://127.0.0.1:12393/v1/audio/transcriptions".to_string(),
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
}

impl SettingsManager {
    pub fn new() -> Self {
        let config_path = crate::paths::get_settings_json_path();
        log::info!("[SettingsManager] Loaded settings from: {:?}", config_path);
        let sm = Self {
            config_path,
            settings: RwLock::new(AppSettings::default()),
            model_cache: RwLock::new(Vec::new()),
        };
        sm.load_from_disk();
        sm
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

    pub fn update_settings(&self, new_settings: AppSettings) -> Result<(), String> {
        {
            let mut s = self.settings.write().unwrap();
            *s = new_settings;
        }
        self.save_to_disk()
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
