//! Win32 DPAPI (Data Protection API) wrapper for Windows user-level credential protection.
//!
//! Threat Model Note (S1):
//! Encryption scope is CurrentUser (user-level credential encryption).
//! It prevents plaintext credential theft if configuration files are copied to other machines
//! or accessed by other user accounts. Local processes running under the same user token
//! cannot decrypt without supplying the matching application entropy.

#[repr(C)]
struct DataBlob {
    cb_data: u32,
    pb_data: *mut u8,
}

#[cfg(windows)]
extern "system" {
    fn CryptProtectData(
        p_data_in: *const DataBlob,
        sz_data_descr: *const u16,
        p_optional_entropy: *const DataBlob,
        pv_reserved: *mut std::ffi::c_void,
        p_prompt_struct: *mut std::ffi::c_void,
        dw_flags: u32,
        p_data_out: *mut DataBlob,
    ) -> i32;

    fn CryptUnprotectData(
        p_data_in: *const DataBlob,
        ppsz_data_descr: *mut *mut u16,
        p_optional_entropy: *const DataBlob,
        pv_reserved: *mut std::ffi::c_void,
        p_prompt_struct: *mut std::ffi::c_void,
        dw_flags: u32,
        p_data_out: *mut DataBlob,
    ) -> i32;

    fn LocalFree(h_mem: *mut std::ffi::c_void) -> *mut std::ffi::c_void;
}

const CRYPTPROTECT_UI_FORBIDDEN: u32 = 0x1;
const APP_ENTROPY: &[u8] = b"LocalVoiceAgent-DPAPI-Entropy-v2";

pub fn dpapi_encrypt(plaintext: &str) -> Result<String, String> {
    if plaintext.is_empty() {
        return Ok(String::new());
    }
    #[cfg(windows)]
    unsafe {
        let mut in_bytes = plaintext.as_bytes().to_vec();
        let in_blob = DataBlob {
            cb_data: in_bytes.len() as u32,
            pb_data: in_bytes.as_mut_ptr(),
        };

        let mut entropy_bytes = APP_ENTROPY.to_vec();
        let entropy_blob = DataBlob {
            cb_data: entropy_bytes.len() as u32,
            pb_data: entropy_bytes.as_mut_ptr(),
        };

        let mut out_blob = DataBlob {
            cb_data: 0,
            pb_data: std::ptr::null_mut(),
        };

        let res = CryptProtectData(
            &in_blob,
            std::ptr::null(),
            &entropy_blob,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut out_blob,
        );

        if res == 0 {
            return Err("CryptProtectData failed".to_string());
        }

        let slice = std::slice::from_raw_parts(out_blob.pb_data, out_blob.cb_data as usize);
        let b64 = base64_encode(slice);
        LocalFree(out_blob.pb_data as *mut _);

        Ok(format!("dpapi:{}", b64))
    }
    #[cfg(not(windows))]
    {
        Err("DPAPI encryption is only supported on Windows platforms".to_string())
    }
}

pub fn dpapi_decrypt(ciphertext: &str) -> Result<String, String> {
    if ciphertext.is_empty() {
        return Ok(String::new());
    }
    if !ciphertext.starts_with("dpapi:") {
        // Plaintext fallback if not encrypted
        return Ok(ciphertext.to_string());
    }

    let b64_str = &ciphertext["dpapi:".len()..];
    let cipher_bytes = base64_decode(b64_str).map_err(|e| format!("Base64 decode error: {}", e))?;

    #[cfg(windows)]
    unsafe {
        let mut in_bytes = cipher_bytes;
        let in_blob = DataBlob {
            cb_data: in_bytes.len() as u32,
            pb_data: in_bytes.as_mut_ptr(),
        };

        let mut entropy_bytes = APP_ENTROPY.to_vec();
        let entropy_blob = DataBlob {
            cb_data: entropy_bytes.len() as u32,
            pb_data: entropy_bytes.as_mut_ptr(),
        };

        let mut out_blob = DataBlob {
            cb_data: 0,
            pb_data: std::ptr::null_mut(),
        };

        let res = CryptUnprotectData(
            &in_blob,
            std::ptr::null_mut(),
            &entropy_blob,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut out_blob,
        );

        if res == 0 {
            return Err("CryptUnprotectData failed: cannot decrypt with current user token".to_string());
        }

        let slice = std::slice::from_raw_parts(out_blob.pb_data, out_blob.cb_data as usize);
        let plain = String::from_utf8_lossy(slice).to_string();
        LocalFree(out_blob.pb_data as *mut _);

        Ok(plain)
    }
    #[cfg(not(windows))]
    {
        Err("DPAPI decryption is only supported on Windows platforms".to_string())
    }
}

// Minimal standard RFC 4648 Base64 helper
const B64_CHARS: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

fn base64_encode(data: &[u8]) -> String {
    let mut out = String::new();
    let mut i = 0;
    while i < data.len() {
        let b0 = data[i] as usize;
        let b1 = if i + 1 < data.len() { data[i + 1] as usize } else { 0 };
        let b2 = if i + 2 < data.len() { data[i + 2] as usize } else { 0 };

        let triple = (b0 << 16) | (b1 << 8) | b2;

        out.push(B64_CHARS[(triple >> 18) & 0x3F] as char);
        out.push(B64_CHARS[(triple >> 12) & 0x3F] as char);

        if i + 1 < data.len() {
            out.push(B64_CHARS[(triple >> 6) & 0x3F] as char);
        } else {
            out.push('=');
        }

        if i + 2 < data.len() {
            out.push(B64_CHARS[triple & 0x3F] as char);
        } else {
            out.push('=');
        }

        i += 3;
    }
    out
}

fn base64_decode(s: &str) -> Result<Vec<u8>, String> {
    let mut table = [255u8; 256];
    for (idx, &c) in B64_CHARS.iter().enumerate() {
        table[c as usize] = idx as u8;
    }

    let clean: Vec<u8> = s.bytes().filter(|&b| !b.is_ascii_whitespace()).collect();
    if clean.len() % 4 != 0 {
        return Err("Invalid Base64 length".to_string());
    }

    let mut out = Vec::new();
    let mut i = 0;
    while i < clean.len() {
        let c0 = clean[i];
        let c1 = clean[i + 1];
        let c2 = clean[i + 2];
        let c3 = clean[i + 3];

        let v0 = table[c0 as usize];
        let v1 = table[c1 as usize];
        if v0 == 255 || v1 == 255 {
            return Err("Invalid Base64 character".to_string());
        }

        let mut triple = ((v0 as u32) << 18) | ((v1 as u32) << 12);

        if c2 != b'=' {
            let v2 = table[c2 as usize];
            if v2 == 255 { return Err("Invalid Base64 character".to_string()); }
            triple |= (v2 as u32) << 6;
        }
        if c3 != b'=' {
            let v3 = table[c3 as usize];
            if v3 == 255 { return Err("Invalid Base64 character".to_string()); }
            triple |= v3 as u32;
        }

        out.push(((triple >> 16) & 0xFF) as u8);
        if c2 != b'=' {
            out.push(((triple >> 8) & 0xFF) as u8);
        }
        if c3 != b'=' {
            out.push((triple & 0xFF) as u8);
        }

        i += 4;
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dpapi_roundtrip() {
        let secret = "sk-antigravity-test-key-123456789";
        let encrypted = dpapi_encrypt(secret).expect("encrypt ok");
        assert!(encrypted.starts_with("dpapi:"));
        assert_ne!(secret, encrypted);

        let decrypted = dpapi_decrypt(&encrypted).expect("decrypt ok");
        assert_eq!(secret, decrypted);
    }
}
