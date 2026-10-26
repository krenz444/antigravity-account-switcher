//! Google Cloud Code PA API & OAuth Engine
//! Native implementation of Antigravity token refresh, quota monitoring, and tier resolution.

#![allow(dead_code)]

use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use chrono::Utc;
use log::{info, warn};
use reqwest::Client;
use serde_json::{json, Value};

use crate::models::QuotaData;

pub const CLIENT_ID_ENCODED: &[u8] = b"kjmkjjljljockw.72))34h2hk69(?hio,.56502n=nji?*t;**)t=55=6?/)?(954.?4.t957";
pub const CLIENT_SECRET_ENCODED: &[u8] = b"\x1d\x15\x19\t\n\x02w\x11ob\x1c\r\x08nbl\x16>\x16\x10k7\x16\x18b)\x02\x19n l+\x1e\x1b<";
pub const XOR_KEY: u8 = 0x5A;

const USER_AGENT: &str = "antigravity/2.23.0";
const OAUTH_TOKEN_URL: &str = "https://oauth2.googleapis.com/token";
const PA_QUOTA_URL: &str = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary";
const PA_LOAD_ASSIST_URL: &str = "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist";

/// Decode obfuscated credentials using byte-wise XOR against a key.
pub fn decode_cred(data: &[u8], key: u8) -> String {
    let decoded: Vec<u8> = data.iter().map(|b| b ^ key).collect();
    String::from_utf8(decoded).unwrap_or_default()
}

/// Decoded Antigravity OAuth Client ID.
pub fn get_client_id() -> String {
    decode_cred(CLIENT_ID_ENCODED, XOR_KEY)
}

/// Decoded Antigravity OAuth Client Secret.
pub fn get_client_secret() -> String {
    decode_cred(CLIENT_SECRET_ENCODED, XOR_KEY)
}

/// Formats a duration in seconds into a human-readable countdown string.
pub fn format_duration_countdown(total_secs: i64) -> String {
    if total_secs <= 0 {
        return "Ready".to_string();
    }

    let hours = total_secs / 3600;
    let mins = (total_secs % 3600) / 60;

    if hours > 0 {
        if mins > 0 {
            format!("Reset: {}h {}m", hours, mins)
        } else {
            format!("Reset: {}h", hours)
        }
    } else if mins > 0 {
        format!("Reset: {}m", mins)
    } else {
        "Reset: <1m".to_string()
    }
}

/// Formats an ISO 8601 / RFC 3339 reset timestamp into a human-readable countdown string.
pub fn format_countdown(reset_time_iso: &str) -> String {
    let trimmed = reset_time_iso.trim();
    if trimmed.is_empty() || trimmed.eq_ignore_ascii_case("ready") || trimmed.eq_ignore_ascii_case("none") {
        return "Ready".to_string();
    }

    let parsed_time = chrono::DateTime::parse_from_rfc3339(trimmed)
        .map(|dt| dt.with_timezone(&Utc))
        .or_else(|_| {
            chrono::NaiveDateTime::parse_from_str(trimmed, "%Y-%m-%dT%H:%M:%S")
                .map(|ndt| chrono::DateTime::<Utc>::from_naive_utc_and_offset(ndt, Utc))
        });

    let target_utc = match parsed_time {
        Ok(t) => t,
        Err(_) => {
            if trimmed.starts_with("Reset") {
                return trimmed.to_string();
            }
            return "Ready".to_string();
        }
    };

    let now_utc = Utc::now();
    let diff = target_utc.signed_duration_since(now_utc);
    format_duration_countdown(diff.num_seconds())
}

/// Formats a weekly reset timestamp (e.g. "2026-11-02T19:00:00Z") into a readable reset target.
pub fn format_weekly_reset(reset_iso: &str) -> String {
    let trimmed = reset_iso.trim();
    if trimmed.is_empty() || trimmed.eq_ignore_ascii_case("ready") || trimmed.eq_ignore_ascii_case("none") {
        return "Resets weekly".to_string();
    }
    if trimmed.starts_with("Resets ") {
        return trimmed.to_string();
    }

    let parsed_time = chrono::DateTime::parse_from_rfc3339(trimmed)
        .map(|dt| dt.with_timezone(&chrono::Local))
        .or_else(|_| {
            chrono::NaiveDateTime::parse_from_str(trimmed, "%Y-%m-%dT%H:%M:%S")
                .map(|ndt| {
                    let utc = chrono::DateTime::<Utc>::from_naive_utc_and_offset(ndt, Utc);
                    utc.with_timezone(&chrono::Local)
                })
        });

    if let Ok(local_dt) = parsed_time {
        return local_dt.format("Resets %a %I:%M %p").to_string();
    }

    "Resets weekly".to_string()
}

/// Resolves the filesystem directory for a given profile name.
pub fn resolve_profile_dir(profile_name: &str) -> Option<PathBuf> {
    let p_dir = crate::router::profiles_dir();
    let direct = p_dir.join(profile_name);
    if direct.is_dir() {
        return Some(direct);
    }
    let sanitized = p_dir.join(crate::router::sanitize_profile_name(profile_name));
    if sanitized.is_dir() {
        return Some(sanitized);
    }
    if profile_name.chars().all(|c| c.is_ascii_digit()) {
        let cand = p_dir.join(format!("google_{}", profile_name));
        if cand.is_dir() {
            return Some(cand);
        }
    }
    if let Ok(entries) = fs::read_dir(&p_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                if let Some(dirname) = path.file_name().and_then(|n| n.to_str()) {
                    if dirname.eq_ignore_ascii_case(profile_name) {
                        return Some(path);
                    }
                }
            }
        }
    }
    None
}

/// Retrieves stored email for a profile directory from metadata or credential files.
pub fn get_profile_email(profile_dir: &Path) -> Option<String> {
    let meta_file = profile_dir.join("profile_meta.json");
    if meta_file.exists() {
        if let Ok(content) = fs::read_to_string(&meta_file) {
            if let Ok(val) = serde_json::from_str::<Value>(&content) {
                if let Some(email) = val.get("email").and_then(|v| v.as_str()) {
                    let trimmed = email.trim();
                    if !trimmed.is_empty() && trimmed != "Unknown" {
                        return Some(trimmed.to_string());
                    }
                }
            }
        }
    }

    let acc_file = profile_dir.join("google_accounts.json");
    if acc_file.exists() {
        if let Ok(content) = fs::read_to_string(&acc_file) {
            if let Ok(val) = serde_json::from_str::<Value>(&content) {
                if let Some(email) = val.get("active").and_then(|v| v.as_str()) {
                    let trimmed = email.trim();
                    if !trimmed.is_empty() && trimmed != "Unknown" {
                        return Some(trimmed.to_string());
                    }
                }
            }
        }
    }

    let blob_file = profile_dir.join("credential_blob.bin");
    if blob_file.exists() {
        if let Ok(blob) = fs::read(&blob_file) {
            if let Some(email) = crate::router::extract_email_from_blob(&blob) {
                return Some(email);
            }
        }
    }

    None
}

/// Reads the cached access token from `credential_blob.bin` or `oauth_creds.json`.
pub fn get_profile_access_token(profile_dir: &Path) -> Option<String> {
    let blob_file = profile_dir.join("credential_blob.bin");
    if blob_file.exists() {
        if let Ok(content) = fs::read_to_string(&blob_file) {
            if let Ok(val) = serde_json::from_str::<Value>(&content) {
                if let Some(tok) = val.get("token").and_then(|t| t.get("access_token")).and_then(|v| v.as_str()) {
                    if !tok.trim().is_empty() {
                        return Some(tok.trim().to_string());
                    }
                }
                if let Some(tok) = val.get("access_token").and_then(|v| v.as_str()) {
                    if !tok.trim().is_empty() {
                        return Some(tok.trim().to_string());
                    }
                }
            }
        }
    }

    let oauth_file = profile_dir.join("oauth_creds.json");
    if oauth_file.exists() {
        if let Ok(content) = fs::read_to_string(&oauth_file) {
            if let Ok(val) = serde_json::from_str::<Value>(&content) {
                if let Some(tok) = val.get("access_token").and_then(|v| v.as_str()) {
                    if !tok.trim().is_empty() {
                        return Some(tok.trim().to_string());
                    }
                }
            }
        }
    }

    None
}

/// Reads the refresh token from `credential_blob.bin` or `oauth_creds.json`.
pub fn get_profile_refresh_token(profile_dir: &Path) -> Option<String> {
    let blob_file = profile_dir.join("credential_blob.bin");
    if blob_file.exists() {
        if let Ok(content) = fs::read_to_string(&blob_file) {
            if let Ok(val) = serde_json::from_str::<Value>(&content) {
                if let Some(rt) = val.get("token").and_then(|t| t.get("refresh_token")).and_then(|v| v.as_str()) {
                    if !rt.trim().is_empty() {
                        return Some(rt.trim().to_string());
                    }
                }
                if let Some(rt) = val.get("refresh_token").and_then(|v| v.as_str()) {
                    if !rt.trim().is_empty() {
                        return Some(rt.trim().to_string());
                    }
                }
            }
        }
    }

    let oauth_file = profile_dir.join("oauth_creds.json");
    if oauth_file.exists() {
        if let Ok(content) = fs::read_to_string(&oauth_file) {
            if let Ok(val) = serde_json::from_str::<Value>(&content) {
                if let Some(rt) = val.get("refresh_token").and_then(|v| v.as_str()) {
                    if !rt.trim().is_empty() {
                        return Some(rt.trim().to_string());
                    }
                }
            }
        }
    }

    None
}

/// Refreshes the OAuth access token for a profile using Antigravity client credentials.
pub async fn refresh_profile_token(profile_name: &str) -> Result<String, Box<dyn Error>> {
    let target_dir = resolve_profile_dir(profile_name)
        .ok_or_else(|| format!("Profile directory for '{}' not found", profile_name))?;

    let refresh_token = get_profile_refresh_token(&target_dir)
        .ok_or_else(|| format!("No refresh_token found for profile '{}'", profile_name))?;

    info!("Refreshing OAuth token for profile '{}'...", profile_name);

    let client = Client::builder()
        .timeout(Duration::from_secs(10))
        .build()?;

    let params = [
        ("client_id", get_client_id()),
        ("client_secret", get_client_secret()),
        ("grant_type", "refresh_token".to_string()),
        ("refresh_token", refresh_token),
    ];

    let res = client
        .post(OAUTH_TOKEN_URL)
        .form(&params)
        .send()
        .await?;

    if !res.status().is_success() {
        let status = res.status();
        let body = res.text().await.unwrap_or_default();
        return Err(format!("OAuth token refresh HTTP {}: {}", status, body).into());
    }

    let json_res: Value = res.json().await?;
    let new_access_token = json_res
        .get("access_token")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "OAuth response missing access_token")?
        .to_string();

    let new_refresh_token = json_res.get("refresh_token").and_then(|v| v.as_str());
    let expires_in = json_res.get("expires_in").and_then(|v| v.as_i64()).unwrap_or(3600);

    // Update credential_blob.bin
    let cred_file = target_dir.join("credential_blob.bin");
    let mut blob_val = if cred_file.exists() {
        fs::read_to_string(&cred_file)
            .ok()
            .and_then(|s| serde_json::from_str::<Value>(&s).ok())
            .unwrap_or_else(|| json!({}))
    } else {
        json!({})
    };

    if !blob_val.is_object() {
        blob_val = json!({});
    }

    if !blob_val.get("token").map(|v| v.is_object()).unwrap_or(false) {
        blob_val["token"] = json!({});
    }

    blob_val["token"]["access_token"] = Value::String(new_access_token.clone());
    if let Some(rt) = new_refresh_token {
        blob_val["token"]["refresh_token"] = Value::String(rt.to_string());
    }
    let exp_dt = Utc::now() + chrono::Duration::seconds(expires_in);
    blob_val["token"]["expiry"] = Value::String(exp_dt.to_rfc3339());

    let updated_bytes = serde_json::to_vec_pretty(&blob_val)?;
    crate::router::atomic_write_file(&cred_file, &updated_bytes)?;

    // Also update oauth_creds.json if present
    let oauth_file = target_dir.join("oauth_creds.json");
    if oauth_file.exists() {
        if let Ok(content) = fs::read_to_string(&oauth_file) {
            if let Ok(mut oauth_val) = serde_json::from_str::<Value>(&content) {
                oauth_val["access_token"] = Value::String(new_access_token.clone());
                if let Some(rt) = new_refresh_token {
                    oauth_val["refresh_token"] = Value::String(rt.to_string());
                }
                oauth_val["expiry_date"] = Value::String(exp_dt.to_rfc3339());
                if let Ok(updated_oauth) = serde_json::to_vec_pretty(&oauth_val) {
                    let _ = crate::router::atomic_write_file(&oauth_file, &updated_oauth);
                }
            }
        }
    }

    info!("Successfully refreshed OAuth token for profile '{}'", profile_name);
    Ok(new_access_token)
}

/// Parses Google Cloud Code PA API `RetrieveUserQuotaSummary` JSON response.
pub fn parse_quota_summary(val: &Value) -> QuotaData {
    let mut quota = QuotaData::default();
    let root = if let Some(resp) = val.get("response") {
        resp
    } else {
        val
    };

    if let Some(groups) = root.get("groups").and_then(|g| g.as_array()) {
        for grp in groups {
            let display_name = grp.get("displayName").and_then(|v| v.as_str()).unwrap_or("");
            if display_name.contains("Gemini") {
                if let Some(buckets) = grp.get("buckets").and_then(|b| b.as_array()) {
                    for b in buckets {
                        let bid = b.get("bucketId").and_then(|v| v.as_str()).unwrap_or("");
                        let window = b.get("window").and_then(|v| v.as_str()).unwrap_or("");
                        let b_name = b.get("displayName").and_then(|v| v.as_str()).unwrap_or("").to_lowercase();
                        let frac = b.get("remainingFraction").and_then(|v| v.as_f64()).unwrap_or(0.0);
                        let pct = (frac * 100.0).round() as f32;
                        let reset_time = b.get("resetTime").and_then(|v| v.as_str()).unwrap_or("");
                        let desc = b.get("description").and_then(|v| v.as_str()).unwrap_or("");

                        if bid == "gemini-5h" || window == "5h" || b_name.contains("5-hour") {
                            quota.pct_5h = pct;
                            quota.reset_5h = if reset_time.is_empty() { "Ready".to_string() } else { reset_time.to_string() };
                            quota.desc_5h = desc.to_string();
                        } else if bid == "gemini-weekly" || window == "weekly" || b_name.contains("weekly") {
                            quota.weekly_pct = pct;
                            quota.weekly_reset = if reset_time.is_empty() { "Ready".to_string() } else { reset_time.to_string() };
                            quota.weekly_desc = desc.to_string();
                        }
                    }
                }
            } else if display_name.contains("Claude") || display_name.contains("GPT") {
                if let Some(buckets) = grp.get("buckets").and_then(|b| b.as_array()) {
                    for b in buckets {
                        let bid = b.get("bucketId").and_then(|v| v.as_str()).unwrap_or("");
                        let window = b.get("window").and_then(|v| v.as_str()).unwrap_or("");
                        let frac = b.get("remainingFraction").and_then(|v| v.as_f64()).unwrap_or(1.0);
                        let pct = (frac * 100.0).round() as f32;

                        if bid == "3p-5h" || window == "5h" {
                            quota.claude_5h_pct = pct;
                        } else if bid == "3p-weekly" || window == "weekly" {
                            quota.claude_weekly_pct = pct;
                        }
                    }
                }
            }
        }
    }

    if quota.pct_5h >= 100.0 {
        quota.countdown_text = "Full Quota".to_string();
    } else {
        quota.countdown_text = format_countdown(&quota.reset_5h);
    }

    quota
}

/// Parses subscription tier identification from `loadCodeAssist` or `GetLoadCodeAssist` JSON.
pub fn parse_tier_from_json(val: &Value) -> (String, String) {
    let root = if let Some(resp) = val.get("response") {
        resp
    } else {
        val
    };

    if let Some(paid) = root.get("paidTier").and_then(|p| p.as_object()) {
        if let Some(id) = paid.get("id").and_then(|v| v.as_str()) {
            if !id.is_empty() {
                let name = paid.get("name").and_then(|v| v.as_str()).unwrap_or("Google AI Pro");
                let label = match id {
                    "g1-ultra-tier" => "Google AI Ultra".to_string(),
                    "g1-pro-tier" => "Google AI Pro".to_string(),
                    _ => name.to_string(),
                };
                return (id.to_string(), label);
            }
        }
    }

    if let Some(cur) = root.get("currentTier").and_then(|c| c.as_object()) {
        let id = cur.get("id").and_then(|v| v.as_str()).unwrap_or("free-tier");
        let label = match id {
            "g1-ultra-tier" => "Google AI Ultra".to_string(),
            "g1-pro-tier" => "Google AI Pro".to_string(),
            "standard-tier" => "Enterprise Standard".to_string(),
            _ => "Free Tier".to_string(),
        };
        return (id.to_string(), label);
    }

    ("free-tier".to_string(), "Free Tier".to_string())
}

#[derive(Debug, Clone)]
pub struct LanguageServerConn {
    pub port: u16,
    pub csrf_token: String,
}

static LS_CACHE: Mutex<Option<(LanguageServerConn, Instant)>> = Mutex::new(None);

#[cfg(windows)]
fn get_process_listening_ports_win32(target_pid: u32) -> Vec<u16> {
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct MIB_TCPROW_OWNER_PID {
        dw_state: u32,
        dw_local_addr: u32,
        dw_local_port: u32,
        dw_remote_addr: u32,
        dw_remote_port: u32,
        dw_owning_pid: u32,
    }

    #[repr(C)]
    struct MIB_TCPTABLE_OWNER_PID {
        dw_num_entries: u32,
        table: [MIB_TCPROW_OWNER_PID; 1],
    }

    #[link(name = "iphlpapi")]
    extern "system" {
        fn GetExtendedTcpTable(
            p_tcp_table: *mut std::ffi::c_void,
            pdw_size: *mut u32,
            b_order: i32,
            ul_af: u32,
            table_class: i32,
            reserved: u32,
        ) -> u32;
    }

    let mut size: u32 = 0;
    unsafe {
        GetExtendedTcpTable(std::ptr::null_mut(), &mut size, 0, 2, 5, 0);
    }

    if size == 0 {
        return Vec::new();
    }

    let mut buf = vec![0u8; size as usize];
    let ret = unsafe {
        GetExtendedTcpTable(buf.as_mut_ptr() as *mut std::ffi::c_void, &mut size, 0, 2, 5, 0)
    };
    if ret != 0 {
        return Vec::new();
    }

    let table_ptr = buf.as_ptr() as *const MIB_TCPTABLE_OWNER_PID;
    let num_entries = unsafe { (*table_ptr).dw_num_entries };
    let rows_ptr = unsafe { std::ptr::addr_of!((*table_ptr).table) as *const MIB_TCPROW_OWNER_PID };

    let mut found_ports = Vec::new();
    for i in 0..num_entries as usize {
        let row = unsafe { *rows_ptr.add(i) };
        if row.dw_owning_pid == target_pid && row.dw_state == 2 {
            let port = u16::from_be(row.dw_local_port as u16);
            if !found_ports.contains(&port) {
                found_ports.push(port);
            }
        }
    }

    found_ports
}

/// Discovers running Antigravity `language_server.exe` port and CSRF token purely in-process.
/// Zero command lines or shell popups are ever invoked.
pub async fn discover_language_server() -> Option<LanguageServerConn> {
    if !crate::process::is_language_server_running() {
        return None;
    }

    // Check fast cache (valid for 8 seconds)
    if let Ok(guard) = LS_CACHE.lock() {
        if let Some((ref conn, instant)) = *guard {
            if instant.elapsed() < Duration::from_secs(8) {
                return Some(conn.clone());
            }
        }
    }

    // Discover PID and CSRF token in memory via sysinfo
    use sysinfo::{ProcessRefreshKind, RefreshKind, System, UpdateKind};
    let sys = System::new_with_specifics(
        RefreshKind::new().with_processes(
            ProcessRefreshKind::new().with_cmd(UpdateKind::Always)
        )
    );

    let mut target_pid: Option<u32> = None;
    let mut csrf_token: Option<String> = None;

    for (pid, proc) in sys.processes() {
        let name = proc.name().to_string_lossy();
        if name.eq_ignore_ascii_case("language_server.exe") || name.eq_ignore_ascii_case("language_server") {
            let cmd_args = proc.cmd();
            for i in 0..cmd_args.len() {
                let arg = cmd_args[i].to_string_lossy();
                if arg == "--csrf_token" && i + 1 < cmd_args.len() {
                    target_pid = Some(pid.as_u32());
                    csrf_token = Some(cmd_args[i + 1].to_string_lossy().to_string());
                    break;
                } else if arg.starts_with("--csrf_token=") {
                    target_pid = Some(pid.as_u32());
                    csrf_token = Some(arg["--csrf_token=".len()..].to_string());
                    break;
                }
            }
            if csrf_token.is_some() {
                break;
            }
        }
    }

    let pid = target_pid?;
    let csrf = csrf_token?;

    // Query listening ports natively via Win32 FFI (zero command lines, zero popups)
    #[cfg(windows)]
    let ports = get_process_listening_ports_win32(pid);
    #[cfg(not(windows))]
    let ports: Vec<u16> = Vec::new();

    let client = Client::builder()
        .danger_accept_invalid_certs(true)
        .timeout(Duration::from_millis(1500))
        .build()
        .ok()?;

    // Probe candidate ports to verify live LanguageServerService endpoint
    for port in ports {
        let url = format!(
            "https://127.0.0.1:{}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
            port
        );
        let resp = client
            .post(&url)
            .header("Content-Type", "application/json")
            .header("x-codeium-csrf-token", &csrf)
            .body("{}")
            .send()
            .await;

        if let Ok(r) = resp {
            if r.status().is_success() {
                let conn = LanguageServerConn {
                    port,
                    csrf_token: csrf.clone(),
                };
                if let Ok(mut guard) = LS_CACHE.lock() {
                    *guard = Some((conn.clone(), Instant::now()));
                }
                return Some(conn);
            }
        }
    }

    None
}

/// Queries local LanguageServerService for live quota summary.
pub async fn fetch_live_quota_ls(conn: &LanguageServerConn) -> Result<QuotaData, Box<dyn Error>> {
    let client = Client::builder()
        .danger_accept_invalid_certs(true)
        .timeout(Duration::from_secs(3))
        .build()?;

    let url = format!(
        "https://127.0.0.1:{}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
        conn.port
    );

    let res = client
        .post(&url)
        .header("Content-Type", "application/json")
        .header("x-codeium-csrf-token", &conn.csrf_token)
        .body("{}")
        .send()
        .await?;

    if !res.status().is_success() {
        return Err(format!("LanguageServer HTTP {}", res.status()).into());
    }

    let json_data: Value = res.json().await?;
    let mut quota = parse_quota_summary(&json_data);

    // Also query local GetLoadCodeAssist for tier
    let lca_url = format!(
        "https://127.0.0.1:{}/exa.language_server_pb.LanguageServerService/GetLoadCodeAssist",
        conn.port
    );
    if let Ok(lca_res) = client
        .post(&lca_url)
        .header("Content-Type", "application/json")
        .header("x-codeium-csrf-token", &conn.csrf_token)
        .body("{}")
        .send()
        .await
    {
        if lca_res.status().is_success() {
            if let Ok(lca_data) = lca_res.json::<Value>().await {
                let (_, tier_label) = parse_tier_from_json(&lca_data);
                quota.tier_label = tier_label;
            }
        }
    }

    quota.status_text = "Available".to_string();
    Ok(quota)
}

/// Queries Google Cloud Code API to determine the exact subscription tier.
pub async fn fetch_profile_tier(profile_name: &str, access_token: Option<&str>) -> (String, String) {
    let token = if let Some(tok) = access_token {
        tok.to_string()
    } else {
        match refresh_profile_token(profile_name).await {
            Ok(tok) => tok,
            Err(_) => return ("free-tier".to_string(), "Free Tier".to_string()),
        }
    };

    let client = match Client::builder().timeout(Duration::from_secs(5)).build() {
        Ok(c) => c,
        Err(_) => return ("free-tier".to_string(), "Free Tier".to_string()),
    };

    let resp = client
        .post(PA_LOAD_ASSIST_URL)
        .header("Content-Type", "application/json")
        .header("Authorization", format!("Bearer {}", token))
        .header("User-Agent", USER_AGENT)
        .body("{}")
        .send()
        .await;

    if let Ok(r) = resp {
        if r.status().is_success() {
            if let Ok(data) = r.json::<Value>().await {
                return parse_tier_from_json(&data);
            }
        }
    }

    ("free-tier".to_string(), "Free Tier".to_string())
}

/// Fetches real-time quota for a specific profile directly from Google API or local LS.
pub async fn fetch_profile_quota(profile_name: &str) -> QuotaData {
    let target_dir = match resolve_profile_dir(profile_name) {
        Some(d) => d,
        None => {
            let mut q = QuotaData::default();
            q.status_text = "Profile Not Found".to_string();
            return q;
        }
    };

    let profile_email = get_profile_email(&target_dir);
    let live_email = crate::router::get_live_antigravity_email();

    let is_live_profile = match (&profile_email, &live_email) {
        (Some(pe), Some(le)) => !pe.is_empty() && pe.eq_ignore_ascii_case(le),
        _ => false,
    };

    // 1. If profile is live and LanguageServerService is active, query local LS
    if is_live_profile && crate::process::is_language_server_running() {
        if let Some(conn) = discover_language_server().await {
            if let Ok(quota) = fetch_live_quota_ls(&conn).await {
                return quota;
            }
        }
    }

    // 2. Query Google Cloud Code API directly
    let mut access_token = get_profile_access_token(&target_dir);
    if access_token.is_none() {
        access_token = refresh_profile_token(profile_name).await.ok();
    }

    let token = match access_token {
        Some(t) => t,
        None => {
            let mut q = QuotaData::default();
            q.status_text = "Auth Required".to_string();
            return q;
        }
    };

    let client = match Client::builder().timeout(Duration::from_secs(6)).build() {
        Ok(c) => c,
        Err(_) => {
            let mut q = QuotaData::default();
            q.status_text = "Network Error".to_string();
            return q;
        }
    };

    let query_pa = |tok: &str| {
        client
            .post(PA_QUOTA_URL)
            .header("Content-Type", "application/json")
            .header("Authorization", format!("Bearer {}", tok))
            .header("User-Agent", USER_AGENT)
            .body("{}")
    };

    let mut resp = query_pa(&token).send().await;

    // Retry once on 401 or 403
    let mut final_token = token.clone();
    if let Ok(ref r) = resp {
        if r.status() == reqwest::StatusCode::UNAUTHORIZED || r.status() == reqwest::StatusCode::FORBIDDEN {
            info!("Received {} for '{}', attempting token refresh...", r.status(), profile_name);
            if let Ok(new_tok) = refresh_profile_token(profile_name).await {
                final_token = new_tok.clone();
                resp = query_pa(&final_token).send().await;
            }
        }
    }

    match resp {
        Ok(r) => {
            let status = r.status();
            if status.is_success() {
                if let Ok(json_data) = r.json::<Value>().await {
                    let mut quota = parse_quota_summary(&json_data);
                    let (_, tier_label) = fetch_profile_tier(profile_name, Some(&final_token)).await;
                    quota.tier_label = tier_label;
                    quota.status_text = "Available".to_string();
                    return quota;
                }
            } else if status == reqwest::StatusCode::TOO_MANY_REQUESTS {
                let mut q = QuotaData::default();
                q.status_text = "Rate Limited".to_string();
                return q;
            } else if status == reqwest::StatusCode::UNAUTHORIZED || status == reqwest::StatusCode::FORBIDDEN {
                let mut q = QuotaData::default();
                q.status_text = "Auth Required".to_string();
                return q;
            } else {
                let mut q = QuotaData::default();
                q.status_text = format!("HTTP {}", status);
                return q;
            }
        }
        Err(e) => {
            warn!("Network request to Google PA API failed: {}", e);
            let mut q = QuotaData::default();
            q.status_text = "Offline".to_string();
            return q;
        }
    }

    QuotaData::default()
}
