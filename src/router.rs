#![allow(dead_code)]

use std::fs;
use std::path::PathBuf;
use log::{info, warn, error};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::models::AccountItem;

/// Return the current user's home directory.
pub fn home_dir() -> PathBuf {
    if let Ok(p) = std::env::var("USERPROFILE") {
        return PathBuf::from(p);
    }
    if let Ok(p) = std::env::var("HOME") {
        return PathBuf::from(p);
    }
    PathBuf::from(r"C:\Users\drops")
}

/// Directory where Gemini/Antigravity CLI configurations reside (`~/.gemini`).
pub fn gemini_dir() -> PathBuf {
    if let Ok(p) = std::env::var("GEMINI_DIR") {
        return PathBuf::from(p);
    }
    home_dir().join(".gemini")
}

/// Profiles directory (`~/.gemini/profiles`).
pub fn profiles_dir() -> PathBuf {
    gemini_dir().join("profiles")
}

/// Active OAuth credentials file (`~/.gemini/oauth_creds.json`).
pub fn active_oauth_path() -> PathBuf {
    gemini_dir().join("oauth_creds.json")
}

/// Active Google accounts file (`~/.gemini/google_accounts.json`).
pub fn active_accounts_path() -> PathBuf {
    gemini_dir().join("google_accounts.json")
}

/// App storage path for Antigravity App (`%APPDATA%\Antigravity\app_storage.json`).
pub fn app_storage_path() -> PathBuf {
    if let Ok(p) = std::env::var("ANTIGRAVITY_APP_STORAGE") {
        return PathBuf::from(p);
    }
    let appdata = std::env::var("APPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|_| home_dir().join("AppData").join("Roaming"));
    appdata.join("Antigravity").join("app_storage.json")
}

/// State tracking file (`.usage_state.json`) in repository root or current directory.
pub fn state_file_path() -> PathBuf {
    if let Ok(p) = std::env::var("ANTIGRAVITY_STATE_FILE") {
        return PathBuf::from(p);
    }
    std::env::current_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
        .join(".usage_state.json")
}

/// Atomically write data to a file by writing to a temporary file in the same directory
/// and renaming it over the destination file.
pub fn atomic_write_file(dest: &std::path::Path, data: &[u8]) -> std::io::Result<()> {
    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent)?;
    }
    let parent = dest.parent().unwrap_or_else(|| std::path::Path::new("."));
    let file_name = dest.file_name().and_then(|n| n.to_str()).unwrap_or("file");
    let tmp_name = format!(
        ".{}_{}_{}.tmp",
        file_name,
        std::process::id(),
        chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0)
    );
    let tmp_path = parent.join(tmp_name);

    fs::write(&tmp_path, data)?;
    if let Err(e) = fs::rename(&tmp_path, dest) {
        let _ = fs::remove_file(&tmp_path);
        return Err(e);
    }
    Ok(())
}

/// Atomically copy a file by copying to a temporary file in the destination's directory
/// and renaming it over the destination file.
pub fn atomic_copy_file(src: &std::path::Path, dest: &std::path::Path) -> std::io::Result<()> {
    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent)?;
    }
    let parent = dest.parent().unwrap_or_else(|| std::path::Path::new("."));
    let file_name = dest.file_name().and_then(|n| n.to_str()).unwrap_or("file");
    let tmp_name = format!(
        ".{}_{}_{}.tmp",
        file_name,
        std::process::id(),
        chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0)
    );
    let tmp_path = parent.join(tmp_name);

    fs::copy(src, &tmp_path)?;
    if let Err(e) = fs::rename(&tmp_path, dest) {
        let _ = fs::remove_file(&tmp_path);
        return Err(e);
    }
    Ok(())
}

/// Configuration structure for profile metadata (`profile_meta.json`).
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ProfileMeta {
    pub name: Option<String>,
    pub email: Option<String>,
    pub alias: Option<String>,
    pub saved_at: Option<String>,
}

/// Check if a profile name contains only allowed safe characters to prevent path traversal.
pub fn is_valid_profile_name(name: &str) -> bool {
    let clean = name.trim();
    if clean.is_empty() || clean.len() > 64 {
        return false;
    }
    let reserved = [
        "con", "prn", "aux", "nul",
        "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
        "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
    ];
    if reserved.contains(&clean.to_lowercase().as_str()) {
        return false;
    }
    clean.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

/// Sanitize profile name to alphanumeric, underscores, and hyphens.
pub fn sanitize_profile_name(name: &str) -> String {
    let raw = name.trim();
    let mut clean = String::new();
    for c in raw.chars() {
        if c.is_ascii_alphanumeric() || c == '_' || c == '-' {
            clean.push(c);
        } else {
            clean.push('_');
        }
    }
    let trimmed = clean.trim_matches('_');
    if trimmed.is_empty() {
        return "google_1".to_string();
    }
    let mut res = trimmed.to_string();
    if res.len() > 64 {
        res.truncate(64);
    }
    let reserved = [
        "con", "prn", "aux", "nul",
        "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
        "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
    ];
    if reserved.contains(&res.to_lowercase().as_str()) {
        return "google_1".to_string();
    }
    res
}

/// Minimal Base64url decoder without external dependencies.
#[allow(clippy::manual_is_multiple_of)]
fn base64url_decode(input: &str) -> Option<Vec<u8>> {
    let mut clean = input.replace('-', "+").replace('_', "/");
    while clean.len() % 4 != 0 {
        clean.push('=');
    }
    let chars: Vec<char> = clean.chars().collect();
    let mut bytes = Vec::new();

    let decode_char = |c: char| -> Option<u8> {
        match c {
            'A'..='Z' => Some(c as u8 - b'A'),
            'a'..='z' => Some(c as u8 - b'a' + 26),
            '0'..='9' => Some(c as u8 - b'0' + 52),
            '+' => Some(62),
            '/' => Some(63),
            '=' => Some(0),
            _ => None,
        }
    };

    for chunk in chars.chunks(4) {
        if chunk.len() < 4 {
            return None;
        }
        let b0 = decode_char(chunk[0])?;
        let b1 = decode_char(chunk[1])?;
        let b2 = decode_char(chunk[2])?;
        let b3 = decode_char(chunk[3])?;

        let triple = ((b0 as u32) << 18) | ((b1 as u32) << 12) | ((b2 as u32) << 6) | (b3 as u32);

        bytes.push(((triple >> 16) & 0xFF) as u8);
        if chunk[2] != '=' {
            bytes.push(((triple >> 8) & 0xFF) as u8);
        }
        if chunk[3] != '=' {
            bytes.push((triple & 0xFF) as u8);
        }
    }
    Some(bytes)
}

/// Extract email address from a JWT ID token string.
pub fn extract_email_from_jwt(id_tok: &str) -> Option<String> {
    if !id_tok.contains('.') {
        return None;
    }
    let parts: Vec<&str> = id_tok.split('.').collect();
    if parts.len() < 2 {
        return None;
    }
    let payload_bytes = base64url_decode(parts[1])?;
    let payload_str = String::from_utf8(payload_bytes).ok()?;
    let value: Value = serde_json::from_str(&payload_str).ok()?;
    value.get("email").and_then(|v| v.as_str()).map(|s| s.trim().to_lowercase())
}

/// Extract email address from credential blob JSON.
pub fn extract_email_from_blob(blob: &[u8]) -> Option<String> {
    let text = std::str::from_utf8(blob).ok()?;
    let value: Value = serde_json::from_str(text).ok()?;
    let id_tok = value.get("id_token")
        .and_then(|v| v.as_str())
        .or_else(|| value.get("token").and_then(|t| t.get("id_token")).and_then(|v| v.as_str()));

    if let Some(tok) = id_tok {
        extract_email_from_jwt(tok)
    } else {
        None
    }
}

/// Read active Google account email address from `google_accounts.json` or fallback paths.
pub fn get_live_antigravity_email() -> Option<String> {
    let p = active_accounts_path();
    if p.exists() {
        if let Ok(content) = fs::read_to_string(&p) {
            if let Ok(val) = serde_json::from_str::<Value>(&content) {
                if let Some(active) = val.get("active").and_then(|v| v.as_str()) {
                    let trimmed = active.trim();
                    if !trimmed.is_empty() && trimmed != "Unknown" {
                        return Some(trimmed.to_string());
                    }
                }
            }
        }
    }

    // Fallback: AppData app_storage.json
    let app_storage = app_storage_path();
    if app_storage.exists() {
        if let Ok(content) = fs::read_to_string(&app_storage) {
            if let Ok(val) = serde_json::from_str::<Value>(&content) {
                if let Some(user) = val.get("jetski.onboarding.lastLoginUsername").and_then(|v| v.as_str()) {
                    let trimmed = user.trim();
                    if !trimmed.is_empty() {
                        return Some(trimmed.to_string());
                    }
                }
            }
        }
    }

    // Fallback: Read active credential email from Windows Credential Manager
    let (_, cred_email) = read_windows_credential();
    if let Some(email) = cred_email {
        let trimmed = email.trim();
        if !trimmed.is_empty() {
            return Some(trimmed.to_string());
        }
    }

    None
}

/// Read Windows Credential Manager entry for "gemini:antigravity".
pub fn read_windows_credential() -> (Option<Vec<u8>>, Option<String>) {
    // If mock or isolated environment is requested, read from isolated storage to prevent host mutation.
    if std::env::var("ANTIGRAVITY_MOCK_CREDENTIALS").is_ok() || std::env::var("GEMINI_DIR").is_ok() {
        let mock_file = gemini_dir().join("mock_credential_blob.bin");
        if let Ok(blob) = fs::read(mock_file) {
            let email = extract_email_from_blob(&blob);
            return (Some(blob), email);
        }
        return (None, None);
    }

    #[cfg(windows)]
    {
        use windows_sys::Win32::Security::Credentials::{
            CredFree, CredReadW, CREDENTIALW, CRED_TYPE_GENERIC,
        };
        use std::os::windows::ffi::OsStrExt;

        let target_name: Vec<u16> = std::ffi::OsStr::new("gemini:antigravity")
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();

        let mut cred_ptr: *mut CREDENTIALW = std::ptr::null_mut();
        let success = unsafe {
            CredReadW(target_name.as_ptr(), CRED_TYPE_GENERIC, 0, &mut cred_ptr)
        };

        if success != 0 && !cred_ptr.is_null() {
            let blob = unsafe {
                let c = &*cred_ptr;
                if !c.CredentialBlob.is_null() && c.CredentialBlobSize > 0 {
                    let slice = std::slice::from_raw_parts(c.CredentialBlob, c.CredentialBlobSize as usize);
                    slice.to_vec()
                } else {
                    Vec::new()
                }
            };
            unsafe { CredFree(cred_ptr as *const std::ffi::c_void) };

            if blob.is_empty() {
                return (None, None);
            }

            let email = extract_email_from_blob(&blob);
            return (Some(blob), email);
        }
    }
    (None, None)
}

/// Write Windows Credential Manager generic credential for `gemini:antigravity`.
pub fn write_windows_credential(blob: &[u8]) -> bool {
    if blob.is_empty() {
        warn!("Cannot write empty Windows credential blob");
        return false;
    }

    // If mock or isolated environment is requested, write to isolated storage to prevent host mutation.
    if std::env::var("ANTIGRAVITY_MOCK_CREDENTIALS").is_ok() || std::env::var("GEMINI_DIR").is_ok() {
        let mock_file = gemini_dir().join("mock_credential_blob.bin");
        info!("[Mock/Isolated] Writing Windows credential blob ({} bytes)", blob.len());
        return atomic_write_file(&mock_file, blob).is_ok();
    }

    #[cfg(windows)]
    {
        use windows_sys::Win32::Security::Credentials::{
            CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
        };
        use std::os::windows::ffi::OsStrExt;

        fn to_wide(s: &str) -> Vec<u16> {
            std::ffi::OsStr::new(s)
                .encode_wide()
                .chain(std::iter::once(0))
                .collect()
        }

        let mut target_name = to_wide("gemini:antigravity");
        let mut comment = to_wide("Managed by Antigravity Switchboard");
        let mut user_name = to_wide("antigravity");

        let cred = CREDENTIALW {
            Flags: 0,
            Type: CRED_TYPE_GENERIC, // 1
            TargetName: target_name.as_mut_ptr(),
            Comment: comment.as_mut_ptr(),
            LastWritten: unsafe { std::mem::zeroed() },
            CredentialBlobSize: blob.len() as u32,
            CredentialBlob: blob.as_ptr() as *mut u8,
            Persist: CRED_PERSIST_LOCAL_MACHINE, // 2
            AttributeCount: 0,
            Attributes: std::ptr::null_mut(),
            TargetAlias: std::ptr::null_mut(),
            UserName: user_name.as_mut_ptr(),
        };

        let result = unsafe { CredWriteW(&cred, 0) };
        if result != 0 {
            info!("Successfully wrote Windows credential 'gemini:antigravity' ({} bytes)", blob.len());
            true
        } else {
            let err = unsafe { windows_sys::Win32::Foundation::GetLastError() };
            error!("Failed to write Windows credential 'gemini:antigravity' (OS error code {})", err);
            false
        }
    }

    #[cfg(not(windows))]
    {
        info!("[Mock] Wrote credential blob ({} bytes)", blob.len());
        true
    }
}

/// Discover all saved Google profiles from `~/.gemini/profiles`.
pub fn list_profiles() -> Vec<AccountItem> {
    let p_dir = profiles_dir();
    if !p_dir.exists() {
        if let Err(e) = fs::create_dir_all(&p_dir) {
            warn!("Failed to create profiles dir {:?}: {}", p_dir, e);
        }
    }

    let live_email = get_live_antigravity_email().unwrap_or_default().to_lowercase();
    let mut items = Vec::new();

    let mut dir_entries = Vec::new();
    if let Ok(read_dir) = fs::read_dir(&p_dir) {
        for entry in read_dir.flatten() {
            let path = entry.path();
            if path.is_dir() {
                if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                    if is_valid_profile_name(name) {
                        dir_entries.push((name.to_string(), path));
                    }
                }
            }
        }
    }

    dir_entries.sort_by(|a, b| a.0.cmp(&b.0));

    for (idx, (name, path)) in dir_entries.into_iter().enumerate() {
        let meta_file = path.join("profile_meta.json");
        let mut email = String::new();
        let mut alias = String::new();

        if meta_file.exists() {
            if let Ok(content) = fs::read_to_string(&meta_file) {
                if let Ok(meta) = serde_json::from_str::<ProfileMeta>(&content) {
                    if let Some(m_email) = meta.email {
                        email = m_email;
                    }
                    if let Some(m_alias) = meta.alias {
                        alias = m_alias;
                    }
                }
            }
        }

        if email.is_empty() {
            let acc_file = path.join("google_accounts.json");
            if acc_file.exists() {
                if let Ok(content) = fs::read_to_string(&acc_file) {
                    if let Ok(val) = serde_json::from_str::<Value>(&content) {
                        if let Some(act) = val.get("active").and_then(|v| v.as_str()) {
                            email = act.to_string();
                        }
                    }
                }
            }
        }

        if email.is_empty() {
            let blob_file = path.join("credential_blob.bin");
            if blob_file.exists() {
                if let Ok(bytes) = fs::read(&blob_file) {
                    if let Some(e) = extract_email_from_blob(&bytes) {
                        email = e;
                    }
                }
            }
        }

        if alias.is_empty() {
            alias = format!("Profile {}", idx + 1);
        }

        let is_live = !email.is_empty() && email.to_lowercase() == live_email;
        let hotkey_index = (idx + 1) as i32;

        items.push(AccountItem {
            name,
            email,
            alias,
            is_live,
            is_staged: false,
            is_cooldown: false,
            hotkey_index,
            is_smart_next: false,
        });
    }

    items
}

/// Retrieve the active Google profile name stored in `.usage_state.json`.
pub fn get_active_profile_name() -> String {
    let state_file = state_file_path();
    if state_file.exists() {
        if let Ok(content) = fs::read_to_string(&state_file) {
            if let Ok(val) = serde_json::from_str::<Value>(&content) {
                if let Some(name) = val.get("active_google_profile").and_then(|v| v.as_str()) {
                    return name.to_string();
                }
            }
        }
    }
    "google_1".to_string()
}

/// Set a friendly alias/nickname for a given profile.
pub fn set_profile_alias(name: &str, alias: &str) -> Result<bool, Box<dyn std::error::Error>> {
    let p_dir = profiles_dir();
    let safe_name = sanitize_profile_name(name);
    let target_dir = p_dir.join(&safe_name);

    if !target_dir.exists() {
        return Err(format!("Profile '{}' does not exist in {:?}", safe_name, p_dir).into());
    }

    let meta_file = target_dir.join("profile_meta.json");
    let mut meta = if meta_file.exists() {
        let content = fs::read_to_string(&meta_file)?;
        serde_json::from_str::<ProfileMeta>(&content).unwrap_or_default()
    } else {
        ProfileMeta::default()
    };

    meta.name = Some(safe_name.clone());
    meta.alias = Some(alias.trim().to_string());

    let updated_json = serde_json::to_string_pretty(&meta)?;
    atomic_write_file(&meta_file, updated_json.as_bytes())?;
    info!("Updated alias for profile '{}' to '{}'", safe_name, alias);
    Ok(true)
}

/// Switch active Google account credentials to the specified profile.
pub fn switch_google_profile(name: &str) -> Result<bool, Box<dyn std::error::Error>> {
    let p_dir = profiles_dir();
    let target_str = name.trim().to_lowercase();
    let profiles = list_profiles();

    let mut resolved_name: Option<String> = None;
    let mut resolved_dir: Option<PathBuf> = None;
    let mut resolved_email: Option<String> = None;

    // 1. Match by email or partial email
    for p in &profiles {
        let p_email = p.email.to_lowercase();
        if !p_email.is_empty() && (p_email == target_str || (target_str.len() >= 4 && p_email.contains(&target_str))) {
            resolved_name = Some(p.name.clone());
            resolved_dir = Some(p_dir.join(&p.name));
            resolved_email = Some(p.email.clone());
            break;
        }
    }

    // 2. Match numeric aliases (e.g. "1" -> "google_1", "2" -> "google_2")
    if resolved_name.is_none() && target_str.chars().all(|c| c.is_ascii_digit()) {
        let candidate = format!("google_{target_str}");
        let cand_dir = p_dir.join(&candidate);
        if cand_dir.exists() && cand_dir.is_dir() {
            resolved_name = Some(candidate);
            resolved_dir = Some(cand_dir);
        }
    }

    // 3. Match profile name or alias
    if resolved_name.is_none() {
        for p in &profiles {
            if p.name.eq_ignore_ascii_case(&target_str) || p.alias.to_lowercase() == target_str {
                resolved_name = Some(p.name.clone());
                resolved_dir = Some(p_dir.join(&p.name));
                resolved_email = Some(p.email.clone());
                break;
            }
        }
    }

    // 4. Match sanitized name
    if resolved_name.is_none() {
        let safe = sanitize_profile_name(name);
        let cand_dir = p_dir.join(&safe);
        if cand_dir.exists() && cand_dir.is_dir() {
            resolved_name = Some(safe);
            resolved_dir = Some(cand_dir);
        }
    }

    // 5. Case-insensitive filesystem scan
    if resolved_name.is_none() {
        if let Ok(entries) = fs::read_dir(&p_dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    if let Some(dirname) = path.file_name().and_then(|n| n.to_str()) {
                        if is_valid_profile_name(dirname) && dirname.eq_ignore_ascii_case(&target_str) {
                            resolved_name = Some(dirname.to_string());
                            resolved_dir = Some(path);
                            break;
                        }
                    }
                }
            }
        }
    }

    let (safe_name, target_dir) = match (resolved_name, resolved_dir) {
        (Some(n), Some(d)) => (n, d),
        _ => return Err(format!("Profile '{}' not found in {:?}", name, p_dir).into()),
    };

    info!("Switching active profile to '{}' at {:?}", safe_name, target_dir);

    // Read email from profile metadata if not resolved yet
    let target_email = if let Some(e) = resolved_email {
        e
    } else {
        let meta_file = target_dir.join("profile_meta.json");
        let mut e = String::new();
        if meta_file.exists() {
            if let Ok(content) = fs::read_to_string(&meta_file) {
                if let Ok(meta) = serde_json::from_str::<ProfileMeta>(&content) {
                    if let Some(m_email) = meta.email {
                        e = m_email;
                    }
                }
            }
        }
        if e.is_empty() {
            let acc_file = target_dir.join("google_accounts.json");
            if acc_file.exists() {
                if let Ok(content) = fs::read_to_string(&acc_file) {
                    if let Ok(val) = serde_json::from_str::<Value>(&content) {
                        if let Some(act) = val.get("active").and_then(|v| v.as_str()) {
                            e = act.to_string();
                        }
                    }
                }
            }
        }
        e
    };

    // 1. Restore Windows Credential Manager blob
    let blob_file = target_dir.join("credential_blob.bin");
    if blob_file.exists() {
        if let Ok(blob) = fs::read(&blob_file) {
            write_windows_credential(&blob);
        }
    } else {
        let oauth_file = target_dir.join("oauth_creds.json");
        if oauth_file.exists() {
            if let Ok(content) = fs::read_to_string(&oauth_file) {
                if let Ok(creds) = serde_json::from_str::<Value>(&content) {
                    let id_tok = creds.get("id_token").and_then(|v| v.as_str()).unwrap_or("");
                    let access_tok = creds.get("access_token").and_then(|v| v.as_str()).unwrap_or("");
                    let token_type = creds.get("token_type").and_then(|v| v.as_str()).unwrap_or("Bearer");
                    let refresh_tok = creds.get("refresh_token").and_then(|v| v.as_str()).unwrap_or("");
                    let expiry = creds.get("expiry_date").and_then(|v| v.as_str()).unwrap_or("");

                    let constructed = serde_json::json!({
                        "token": {
                            "access_token": access_tok,
                            "token_type": token_type,
                            "refresh_token": refresh_tok,
                            "expiry": expiry
                        },
                        "auth_method": "consumer",
                        "id_token": id_tok
                    });

                    if let Ok(blob_vec) = serde_json::to_vec(&constructed) {
                        write_windows_credential(&blob_vec);
                    }
                }
            }
        }
    }

    // 2. Restore file-based credentials to ~/.gemini using crash-resilient atomic operations
    let oauth_src = target_dir.join("oauth_creds.json");
    let acc_src = target_dir.join("google_accounts.json");

    if oauth_src.exists() {
        if let Err(e) = atomic_copy_file(&oauth_src, &active_oauth_path()) {
            warn!("Failed to copy oauth_creds.json: {}", e);
        }
    }
    if acc_src.exists() {
        if let Err(e) = atomic_copy_file(&acc_src, &active_accounts_path()) {
            warn!("Failed to copy google_accounts.json: {}", e);
        }
    } else if !target_email.is_empty() {
        // Synthesize google_accounts.json so active state matches target email immediately
        let acc_val = serde_json::json!({ "active": target_email });
        if let Ok(bytes) = serde_json::to_vec_pretty(&acc_val) {
            let _ = atomic_write_file(&active_accounts_path(), &bytes);
        }
    }

    // 3. Update Antigravity App app_storage.json atomically
    let storage_path = app_storage_path();
    if storage_path.exists() && !target_email.is_empty() {
        if let Ok(content) = fs::read_to_string(&storage_path) {
            if let Ok(mut storage_val) = serde_json::from_str::<Value>(&content) {
                if let Some(obj) = storage_val.as_object_mut() {
                    obj.insert(
                        "jetski.onboarding.lastLoginUsername".to_string(),
                        Value::String(target_email.clone()),
                    );
                    if let Ok(updated_storage) = serde_json::to_string_pretty(&storage_val) {
                        let _ = atomic_write_file(&storage_path, updated_storage.as_bytes());
                    }
                }
            }
        }
    }

    // 4. Update .usage_state.json atomically
    let state_file = state_file_path();
    let mut state_val = if state_file.exists() {
        let content = fs::read_to_string(&state_file).unwrap_or_default();
        serde_json::from_str::<Value>(&content).unwrap_or_else(|_| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    if let Some(obj) = state_val.as_object_mut() {
        obj.insert("active_google_profile".to_string(), Value::String(safe_name.clone()));
        obj.insert("last_rotation".to_string(), Value::String(chrono::Utc::now().to_rfc3339()));
        if let Ok(updated_state) = serde_json::to_string_pretty(&state_val) {
            let _ = atomic_write_file(&state_file, updated_state.as_bytes());
        }
    }

    info!("[OK] Switched active Google profile to '{}' ({})", safe_name, target_email);
    Ok(true)
}

/// Backup current active credentials into a profile slot in `~/.gemini/profiles/<name>`.
pub fn save_current_profile(name: &str, alias: Option<&str>) -> Result<bool, Box<dyn std::error::Error>> {
    let p_dir = profiles_dir();
    let safe_name = sanitize_profile_name(name);
    let target_dir = p_dir.join(&safe_name);
    fs::create_dir_all(&target_dir)?;

    let live_email = get_live_antigravity_email().unwrap_or_else(|| "Unknown".to_string());

    // 1. Backup Windows Credential blob
    let (blob_opt, _) = read_windows_credential();
    if let Some(blob) = blob_opt {
        atomic_write_file(&target_dir.join("credential_blob.bin"), &blob)?;
    }

    // 2. Backup file credentials
    let oauth_active = active_oauth_path();
    if oauth_active.exists() {
        atomic_copy_file(&oauth_active, &target_dir.join("oauth_creds.json"))?;
    }
    let acc_active = active_accounts_path();
    if acc_active.exists() {
        atomic_copy_file(&acc_active, &target_dir.join("google_accounts.json"))?;
    }

    // 3. Write profile metadata
    let meta = ProfileMeta {
        name: Some(safe_name.clone()),
        email: Some(live_email),
        alias: alias.map(|s| s.trim().to_string()).or_else(|| Some(safe_name.clone())),
        saved_at: Some(chrono::Utc::now().to_rfc3339()),
    };
    let meta_json = serde_json::to_string_pretty(&meta)?;
    atomic_write_file(&target_dir.join("profile_meta.json"), meta_json.as_bytes())?;

    info!("Saved current credentials to profile '{}'", safe_name);
    Ok(true)
}
