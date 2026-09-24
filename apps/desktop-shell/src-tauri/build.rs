fn main() {
    println!("cargo:rustc-link-lib=crypt32");
    println!("cargo:rustc-link-lib=advapi32");

    // Ensure w64devkit is in PATH for windres during GNU target builds
    if let Ok(path) = std::env::var("PATH") {
        let manifest = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        // src-tauri -> desktop-shell -> apps -> repo root
        let repo_root = manifest
            .parent()
            .and_then(|p| p.parent())
            .and_then(|p| p.parent());
        if let Some(root) = repo_root {
            let tb = root.join("tools").join("w64devkit").join("bin");
            if tb.exists() {
                let new_path = format!("{};{}", tb.display(), path);
                std::env::set_var("PATH", new_path);
            }
        }
    }

    if let Ok(out_dir) = std::env::var("OUT_DIR") {
        let p = std::path::PathBuf::from(out_dir);
        if let Some(target_dir) = p.parent().and_then(|p| p.parent()).and_then(|p| p.parent()) {
            let loader = target_dir.join("WebView2Loader.dll");
            if loader.exists() {
                let _ = std::fs::remove_file(loader);
            }
        }
    }

    tauri_build::build()
}
