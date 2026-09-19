fn main() {
  println!("cargo:rustc-link-lib=crypt32");
  println!("cargo:rustc-link-lib=advapi32");
  tauri_build::build()
}
