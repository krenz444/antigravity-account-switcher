//! Claude Code Status and Telemetry Reader
//!
//! Inspects local Claude Code CLI credentials, subscription tier, and token
//! usage metrics from `~/.claude.json` and `~/.claude/.credentials.json`.

use log::{debug, warn};
use serde_json::Value;
use std::fs;
use std::path::Path;

use crate::models::{ClaudeStatus, ClaudeUsage};
use crate::router::home_dir;

/// Formats a human-readable subscription tier label from raw rate limit or subscription strings.
pub fn format_claude_tier_label(subscription_type: Option<&str>, rate_limit_tier: Option<&str>) -> String {
    if let Some(rlt) = rate_limit_tier {
        match rlt {
            "default_claude_max_20x" => return "Claude Max (20x)".to_string(),
            "default_claude_max_5x" => return "Claude Max (5x)".to_string(),
            "default_claude_ai" => return "Claude Pro".to_string(),
            "default_raven" => return "Claude Free".to_string(),
            "default_raven_enterprise" => return "Claude Enterprise".to_string(),
            _ => {}
        }
    }
    if let Some(st) = subscription_type {
        let st_lower = st.to_lowercase();
        if st_lower == "max" || st_lower.contains("max") {
            return "Claude Max".to_string();
        } else if st_lower == "pro" || st_lower == "claude_pro" || st_lower.contains("pro") {
            return "Claude Pro".to_string();
        } else if matches!(st_lower.as_str(), "free" | "starter" | "raven") {
            return "Claude Free".to_string();
        } else if st_lower.contains("enterprise") {
            return "Claude Enterprise".to_string();
        }
    }
    "Claude Pro".to_string()
}

/// Aggregates token counts and costs from a parsed `lastModelUsage` object map.
pub fn aggregate_model_usage(last_model_usage: &Value) -> (ClaudeUsage, usize) {
    let mut usage = ClaudeUsage::default();
    let mut model_count = 0;

    let Some(models_map) = last_model_usage.as_object() else {
        return (usage, 0);
    };

    for (_model_id, m_val) in models_map {
        let Some(m_obj) = m_val.as_object() else {
            continue;
        };

        let input_tokens = m_obj.get("inputTokens")
            .or_else(|| m_obj.get("input_tokens"))
            .and_then(|v| v.as_u64())
            .unwrap_or(0);

        let output_tokens = m_obj.get("outputTokens")
            .or_else(|| m_obj.get("output_tokens"))
            .and_then(|v| v.as_u64())
            .unwrap_or(0);

        let cache_read = m_obj.get("cacheReadInputTokens")
            .or_else(|| m_obj.get("cacheReadTokens"))
            .or_else(|| m_obj.get("cache_read_tokens"))
            .and_then(|v| v.as_u64())
            .unwrap_or(0);

        let cache_write = m_obj.get("cacheCreationInputTokens")
            .or_else(|| m_obj.get("cacheWriteTokens"))
            .or_else(|| m_obj.get("cache_write_tokens"))
            .and_then(|v| v.as_u64())
            .unwrap_or(0);

        let cost_usd = m_obj.get("costUSD")
            .or_else(|| m_obj.get("cost_usd"))
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);

        usage.input_tokens += input_tokens;
        usage.output_tokens += output_tokens;
        usage.cache_read_tokens += cache_read;
        usage.cache_write_tokens += cache_write;
        usage.cost_usd += cost_usd;
        model_count += 1;
    }

    (usage, model_count)
}

/// Reads live plan usage from Claude Desktop's local database (`plan-usage-history.json`).
/// Returns `(remaining_5h_pct, remaining_weekly_pct, reset_desc)`.
pub fn read_claude_plan_usage(local_app_data_path: &Path) -> Option<(f32, f32, String)> {
    let claude_data_dir = local_app_data_path.join("Claude-Data");
    if !claude_data_dir.exists() {
        return None;
    }

    let entries = fs::read_dir(&claude_data_dir).ok()?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            let usage_file = path.join("plan-usage-history.json");
            if usage_file.exists() {
                if let Ok(content) = fs::read_to_string(&usage_file) {
                    if let Ok(val) = serde_json::from_str::<Value>(&content) {
                        if let Some(samples) = val.get("samples").and_then(|s| s.as_array()) {
                            let latest = samples.iter().max_by_key(|s| {
                                s.get("t").and_then(|v| v.as_u64()).unwrap_or(0)
                            });

                            if let Some(s) = latest {
                                if let Some(u) = s.get("u") {
                                    let fh_used = u.get("fh").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32;
                                    let sd_used = u.get("sd").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32;
                                    let remaining_5h = (100.0 - fh_used).clamp(0.0, 100.0);
                                    let remaining_weekly = (100.0 - sd_used).clamp(0.0, 100.0);
                                    let reset_desc = if remaining_5h >= 100.0 {
                                        "Ready".to_string()
                                    } else {
                                        "Active".to_string()
                                    };
                                    return Some((remaining_5h, remaining_weekly, reset_desc));
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    None
}

/// Reads live Claude Code account, subscription tier, and usage metrics from disk.
pub fn get_claude_status() -> ClaudeStatus {
    get_claude_status_from_paths(
        &home_dir().join(".claude.json"),
        &home_dir().join(".claude").join(".credentials.json"),
        &crate::router::local_app_data_dir(),
    )
}

/// Reads Claude status from explicit file paths (useful for unit testing and mocks).
pub fn get_claude_status_from_paths(
    claude_json_path: &Path,
    cred_path: &Path,
    local_app_data_path: &Path,
) -> ClaudeStatus {
    let mut status = ClaudeStatus {
        detected: false,
        email: String::new(),
        tier_label: "Claude Pro".to_string(),
        session_used_pct: 0.0,
        weekly_used_pct: 0.0,
        quota_5h_pct: 100.0,
        quota_weekly_pct: 100.0,
        reset_5h_desc: "Ready".to_string(),
        reset_weekly_desc: "Ready".to_string(),
        usage: None,
    };

    let mut subscription_type: Option<String> = None;
    let mut rate_limit_tier: Option<String> = None;

    // 1. Account identity and subscription tier from ~/.claude.json
    if claude_json_path.exists() {
        match fs::read_to_string(claude_json_path) {
            Ok(content) => match serde_json::from_str::<Value>(&content) {
                Ok(cj) => {
                    if let Some(oa) = cj.get("oauthAccount").and_then(|v| v.as_object()) {
                        status.detected = true;
                        if let Some(email) = oa.get("emailAddress").and_then(|v| v.as_str()) {
                            if !email.is_empty() {
                                status.email = email.to_string();
                            }
                        }
                        if let Some(rlt) = oa
                            .get("organizationRateLimitTier")
                            .or_else(|| oa.get("userRateLimitTier"))
                            .and_then(|v| v.as_str())
                        {
                            if !rlt.is_empty() {
                                rate_limit_tier = Some(rlt.to_string());
                            }
                        }
                        if let Some(st) = oa
                            .get("organizationType")
                            .or_else(|| oa.get("billingType"))
                            .and_then(|v| v.as_str())
                        {
                            if !st.is_empty() {
                                subscription_type = Some(st.to_string());
                            }
                        }
                    }

                    // Aggregate lastModelUsage across all registered projects
                    let mut total_usage = ClaudeUsage::default();
                    let mut found_usage = false;

                    if let Some(projects) = cj.get("projects").and_then(|v| v.as_object()) {
                        for (_proj_dir, proj_val) in projects {
                            if let Some(lmu) = proj_val.get("lastModelUsage") {
                                let (u, count) = aggregate_model_usage(lmu);
                                if count > 0 {
                                    total_usage.input_tokens += u.input_tokens;
                                    total_usage.output_tokens += u.output_tokens;
                                    total_usage.cache_read_tokens += u.cache_read_tokens;
                                    total_usage.cache_write_tokens += u.cache_write_tokens;
                                    total_usage.cost_usd += u.cost_usd;
                                    found_usage = true;
                                }
                            }
                        }
                    }

                    if found_usage {
                        status.usage = Some(total_usage);
                    }
                }
                Err(e) => warn!("Failed to parse {}: {}", claude_json_path.display(), e),
            },
            Err(e) => warn!("Failed to read {}: {}", claude_json_path.display(), e),
        }
    }

    // 2. Fallback / live OAuth tokens from ~/.claude/.credentials.json
    // Only trust .credentials.json tier if it has an active, non-empty access token or if no tier was found in ~/.claude.json
    if cred_path.exists() {
        match fs::read_to_string(cred_path) {
            Ok(content) => match serde_json::from_str::<Value>(&content) {
                Ok(creds) => {
                    if let Some(oauth) = creds.get("claudeAiOauth").and_then(|v| v.as_object()) {
                        let has_valid_token = oauth
                            .get("accessToken")
                            .and_then(|v| v.as_str())
                            .map(|s| !s.trim().is_empty())
                            .unwrap_or(false);

                        if has_valid_token || rate_limit_tier.is_none() {
                            status.detected = true;
                            if let Some(rlt) = oauth.get("rateLimitTier").and_then(|v| v.as_str()) {
                                if !rlt.is_empty() {
                                    rate_limit_tier = Some(rlt.to_string());
                                }
                            }
                            if let Some(st) = oauth.get("subscriptionType").and_then(|v| v.as_str()) {
                                if !st.is_empty() {
                                    subscription_type = Some(st.to_string());
                                }
                            }
                        }
                    }
                }
                Err(e) => warn!("Failed to parse {}: {}", cred_path.display(), e),
            },
            Err(e) => warn!("Failed to read {}: {}", cred_path.display(), e),
        }
    }

    status.tier_label = format_claude_tier_label(
        subscription_type.as_deref(),
        rate_limit_tier.as_deref(),
    );

    // 3. Read live plan usage meters from local database
    if let Some((rem_5h, rem_weekly, reset_desc)) = read_claude_plan_usage(local_app_data_path) {
        status.session_used_pct = 100.0 - rem_5h;
        status.weekly_used_pct = 100.0 - rem_weekly;
        status.quota_5h_pct = rem_5h;
        status.quota_weekly_pct = rem_weekly;
        status.reset_5h_desc = reset_desc;
    }

    // Check if Claude process is active
    if is_claude_process_running() {
        if status.reset_5h_desc == "Ready" {
            status.reset_5h_desc = "Active".to_string();
        }
    }

    debug!(
        "Discovered Claude status: detected={}, email={}, tier={}, 5h={:.0}%, weekly={:.0}%",
        status.detected, status.email, status.tier_label, status.quota_5h_pct, status.quota_weekly_pct
    );

    status
}

/// Checks if any `claude.exe` or `claude` desktop or CLI process is currently active.
pub fn is_claude_process_running() -> bool {
    let mut sys = sysinfo::System::new();
    sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
    sys.processes().values().any(|proc| {
        let name = proc.name().to_string_lossy();
        name.eq_ignore_ascii_case("claude.exe") || name.eq_ignore_ascii_case("claude")
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_claude_tier_label() {
        assert_eq!(
            format_claude_tier_label(Some("max"), Some("default_claude_max_20x")),
            "Claude Max (20x)"
        );
        assert_eq!(
            format_claude_tier_label(Some("max"), Some("default_claude_max_5x")),
            "Claude Max (5x)"
        );
        assert_eq!(
            format_claude_tier_label(Some("pro"), Some("default_claude_ai")),
            "Claude Pro"
        );
        assert_eq!(
            format_claude_tier_label(Some("free"), Some("default_raven")),
            "Claude Free"
        );
        assert_eq!(
            format_claude_tier_label(None, Some("default_raven_enterprise")),
            "Claude Enterprise"
        );
        assert_eq!(format_claude_tier_label(Some("max"), None), "Claude Max");
        assert_eq!(format_claude_tier_label(Some("pro"), None), "Claude Pro");
        assert_eq!(format_claude_tier_label(Some("free"), None), "Claude Free");
    }

    #[test]
    fn test_aggregate_model_usage() {
        let json_data = serde_json::json!({
            "claude-opus-4-8": {
                "inputTokens": 1000,
                "outputTokens": 200,
                "cacheReadInputTokens": 5000,
                "cacheCreationInputTokens": 300,
                "costUSD": 1.25
            },
            "claude-haiku-4-5": {
                "inputTokens": 4000,
                "outputTokens": 800,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "costUSD": 0.15
            }
        });

        let (usage, count) = aggregate_model_usage(&json_data);
        assert_eq!(count, 2);
        assert_eq!(usage.input_tokens, 5000);
        assert_eq!(usage.output_tokens, 1000);
        assert_eq!(usage.cache_read_tokens, 5000);
        assert_eq!(usage.cache_write_tokens, 300);
        assert!((usage.cost_usd - 1.40).abs() < 1e-6);
    }

    #[test]
    fn test_mock_claude_status_from_paths() {
        let temp_dir = std::env::temp_dir().join(format!("claude_test_{}", std::process::id()));
        let _ = fs::create_dir_all(&temp_dir);

        let json_path = temp_dir.join(".claude.json");
        let cred_path = temp_dir.join(".credentials.json");

        let claude_json_content = serde_json::json!({
            "oauthAccount": {
                "emailAddress": "dev.test@anthropic.com",
                "displayName": "Dev Test",
                "accountUuid": "uuid-12345",
                "billingType": "stripe"
            },
            "projects": {
                "test-project": {
                    "lastModelUsage": {
                        "claude-3-7-sonnet": {
                            "inputTokens": 2500,
                            "outputTokens": 500,
                            "costUSD": 0.45
                        }
                    }
                }
            }
        });

        let cred_content = serde_json::json!({
            "claudeAiOauth": {
                "accessToken": "sk-ant-test-token-123",
                "rateLimitTier": "default_claude_max_20x",
                "subscriptionType": "max"
            }
        });

        fs::write(&json_path, claude_json_content.to_string()).unwrap();
        fs::write(&cred_path, cred_content.to_string()).unwrap();

        let status = get_claude_status_from_paths(&json_path, &cred_path, &temp_dir);
        assert!(status.detected);
        assert_eq!(status.email, "dev.test@anthropic.com");
        assert_eq!(status.tier_label, "Claude Max (20x)");
        assert!(status.usage.is_some());
        let u = status.usage.unwrap();
        assert_eq!(u.input_tokens, 2500);
        assert_eq!(u.output_tokens, 500);
        assert!((u.cost_usd - 0.45).abs() < 1e-6);

        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn test_oauth_account_pro_tier_precedence_and_plan_usage() {
        let temp_dir = std::env::temp_dir().join(format!("claude_pro_test_{}", std::process::id()));
        let _ = fs::create_dir_all(&temp_dir);

        let json_path = temp_dir.join(".claude.json");
        let cred_path = temp_dir.join(".credentials.json");

        // Real structure from ~/.claude.json
        let claude_json_content = serde_json::json!({
            "oauthAccount": {
                "emailAddress": "dropshipmk4@gmail.com",
                "organizationType": "claude_pro",
                "organizationRateLimitTier": "default_claude_ai",
                "billingType": "stripe_subscription"
            }
        });

        // Stale .credentials.json with empty token
        let cred_content = serde_json::json!({
            "claudeAiOauth": {
                "accessToken": "",
                "refreshToken": "",
                "rateLimitTier": "default_claude_max_20x",
                "subscriptionType": "max"
            }
        });

        // Mock Claude Desktop plan-usage-history.json
        let claude_data_dir = temp_dir.join("Claude-Data").join("claude_mock_instance");
        let _ = fs::create_dir_all(&claude_data_dir);
        let plan_usage_content = serde_json::json!({
            "version": 2,
            "samples": [
                {
                    "t": 1793130600000_u64,
                    "org": "93e4f26c-cbac-493c-b684-3f505f2ac139",
                    "u": {
                        "fh": 0,
                        "sd": 28
                    }
                }
            ]
        });
        fs::write(claude_data_dir.join("plan-usage-history.json"), plan_usage_content.to_string()).unwrap();

        fs::write(&json_path, claude_json_content.to_string()).unwrap();
        fs::write(&cred_path, cred_content.to_string()).unwrap();

        let status = get_claude_status_from_paths(&json_path, &cred_path, &temp_dir);
        assert!(status.detected);
        assert_eq!(status.email, "dropshipmk4@gmail.com");
        // Must correctly resolve to Claude Pro despite stale default_claude_max_20x in creds
        assert_eq!(status.tier_label, "Claude Pro");
        // Quota: 100 - 0 = 100% for 5h, 100 - 28 = 72% for weekly
        assert_eq!(status.quota_5h_pct, 100.0);
        assert_eq!(status.quota_weekly_pct, 72.0);
        assert_eq!(status.reset_5h_desc, "Ready");

        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn test_live_claude_status_does_not_panic() {
        let status = get_claude_status();
        println!("Live Claude status detected: {}, tier: {}, 5h={:.0}%, weekly={:.0}%", 
            status.detected, status.tier_label, status.quota_5h_pct, status.quota_weekly_pct);
    }
}
