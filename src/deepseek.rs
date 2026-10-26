//! DeepSeek Platform Balance and Account Telemetry
//!
//! Reads DeepSeek Harness session tokens from `~/.dsh/.credentials.yaml`
//! and queries the DeepSeek account platform API for balance and lifetime spend.

use log::{debug, info, warn};
use reqwest::header::{HeaderMap, HeaderValue, ACCEPT, USER_AGENT};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

use crate::models::DeepSeekStatus;
use crate::router::home_dir;

pub const DEFAULT_DEEPSEEK_ORIGIN: &str = "https://platform.deepseek.com";
pub const DEEPSEEK_SUMMARY_PATH: &str = "/api/v0/users/get_user_summary";

/// Locates the DeepSeek Harness credentials YAML path.
pub fn deepseek_credentials_path() -> PathBuf {
    home_dir().join(".dsh").join(".credentials.yaml")
}

/// Parses a DeepSeek platform grant token from credentials YAML content.
/// Scans for `token: "..."` within `records: ... payload:` or fallback token lines.
pub fn parse_deepseek_token(content: &str) -> Option<String> {
    let mut in_records = false;
    let mut in_default_account = false;
    let mut in_payload = false;

    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('#') || trimmed.is_empty() {
            continue;
        }

        let indent = line.len() - line.trim_start().len();

        if indent == 0 {
            in_records = trimmed.starts_with("records:");
            in_default_account = false;
            in_payload = false;
            continue;
        }

        if in_records {
            if trimmed.contains("deepseek-account-platform/default") {
                in_default_account = true;
                in_payload = false;
                continue;
            } else if indent <= 2 && !trimmed.starts_with("deepseek-") {
                in_default_account = false;
                in_payload = false;
            }

            if in_default_account {
                if trimmed.starts_with("payload:") {
                    in_payload = true;
                    continue;
                }

                if in_payload && trimmed.starts_with("token:") {
                    let val = trimmed.trim_start_matches("token:").trim();
                    let cleaned = val.trim_matches(|c| c == '"' || c == '\'');
                    if !cleaned.is_empty() {
                        return Some(cleaned.to_string());
                    }
                }
            }
        }
    }

    // Fallback: search across any section for `token: <val>`
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("token:") {
            let val = trimmed.trim_start_matches("token:").trim();
            let cleaned = val.trim_matches(|c| c == '"' || c == '\'');
            if !cleaned.is_empty() && cleaned.len() > 10 {
                return Some(cleaned.to_string());
            }
        }
    }

    None
}

/// Reads the DeepSeek grant token from disk if present.
pub fn read_deepseek_grant() -> Option<String> {
    let path = deepseek_credentials_path();
    if !path.exists() {
        return None;
    }
    match fs::read_to_string(&path) {
        Ok(content) => parse_deepseek_token(&content),
        Err(e) => {
            warn!("Failed to read DeepSeek credentials from {}: {}", path.display(), e);
            None
        }
    }
}

/// Helper to format currency and amount as a standard display string.
fn format_amount(amount_val: Option<&Value>, currency: Option<&str>) -> Option<String> {
    let curr = currency.unwrap_or("USD");
    if let Some(val) = amount_val {
        if let Some(s) = val.as_str() {
            if let Ok(f) = s.parse::<f64>() {
                return Some(format!("${:.2} {}", f, curr));
            }
            return Some(format!("${} {}", s, curr));
        } else if let Some(f) = val.as_f64() {
            return Some(format!("${:.2} {}", f, curr));
        }
    }
    None
}

/// Queries DeepSeek platform telemetry using a provided token and base URL.
pub async fn fetch_deepseek_status_with_token(
    token: &str,
    base_url: &str,
) -> Result<DeepSeekStatus, Box<dyn std::error::Error + Send + Sync>> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(12))
        .build()?;

    let mut headers = HeaderMap::new();
    headers.insert(
        "x-dsh-auth-token",
        HeaderValue::from_str(token).map_err(|e| format!("Invalid token header: {}", e))?,
    );
    headers.insert("x-client-platform", HeaderValue::from_static("web"));
    headers.insert("x-client-locale", HeaderValue::from_static("en_US"));
    headers.insert("x-client-version", HeaderValue::from_static("1"));
    headers.insert(ACCEPT, HeaderValue::from_static("application/json"));
    headers.insert(
        USER_AGENT,
        HeaderValue::from_static("ai-os-account-router/1.0"),
    );

    let url = format!("{}{}", base_url.trim_end_matches('/'), DEEPSEEK_SUMMARY_PATH);
    debug!("Sending DeepSeek user summary request to {}", url);

    let resp = client.get(&url).headers(headers).send().await?;
    let status_code = resp.status();

    if status_code.as_u16() == 401 || status_code.as_u16() == 403 {
        warn!("DeepSeek authentication rejected with status: {}", status_code);
        return Ok(DeepSeekStatus {
            detected: true,
            signed_in: false,
            email: String::new(),
            balances: "$0.00 USD".to_string(),
            total_spend: "$0.00".to_string(),
        });
    }

    if !status_code.is_success() {
        return Err(format!("DeepSeek API returned HTTP {}", status_code).into());
    }

    let payload: Value = resp.json().await?;
    let mut status = DeepSeekStatus {
        detected: true,
        signed_in: true,
        email: String::new(),
        balances: "$0.00 USD".to_string(),
        total_spend: "$0.00".to_string(),
    };

    let biz_data = payload
        .get("data")
        .and_then(|d| d.get("biz_data"))
        .and_then(|b| b.as_object());

    if let Some(biz) = biz_data {
        // 1. Normal wallets (recharge balance)
        let mut balance_strs = Vec::new();
        if let Some(wallets) = biz.get("normal_wallets").and_then(|w| w.as_array()) {
            for w in wallets {
                let curr = w.get("currency").and_then(|c| c.as_str());
                let bal = w.get("balance");
                if let Some(fmt) = format_amount(bal, curr) {
                    balance_strs.push(fmt);
                }
            }
        }
        if !balance_strs.is_empty() {
            status.balances = balance_strs.join(", ");
        }

        // 2. Total lifetime costs / spend
        let mut spend_strs = Vec::new();
        let spend_arr = biz.get("total_spend").or_else(|| biz.get("total_costs"));
        if let Some(costs) = spend_arr.and_then(|c| c.as_array()) {
            for c in costs {
                let curr = c.get("currency").and_then(|curr_str| curr_str.as_str());
                let amount = c.get("amount");
                if let Some(fmt) = format_amount(amount, curr) {
                    spend_strs.push(fmt);
                }
            }
        }
        if !spend_strs.is_empty() {
            status.total_spend = spend_strs.join(", ");
        }
    }

    info!(
        "DeepSeek status resolved: balance={}, spend={}",
        status.balances, status.total_spend
    );

    Ok(status)
}

/// Reads DeepSeek status from disk and executes live API telemetry query asynchronously.
pub async fn get_deepseek_status() -> DeepSeekStatus {
    let grant = match read_deepseek_grant() {
        Some(t) => t,
        None => {
            debug!("No DeepSeek Harness grant found in ~/.dsh/.credentials.yaml");
            return DeepSeekStatus {
                detected: false,
                signed_in: false,
                email: String::new(),
                balances: "Not Signed In".to_string(),
                total_spend: "$0.00".to_string(),
            };
        }
    };

    let base_origin = std::env::var("DEEPSEEK_PLATFORM_ORIGIN")
        .unwrap_or_else(|_| DEFAULT_DEEPSEEK_ORIGIN.to_string());

    match fetch_deepseek_status_with_token(&grant, &base_origin).await {
        Ok(status) => status,
        Err(e) => {
            warn!("DeepSeek API query error: {}", e);
            DeepSeekStatus {
                detected: true,
                signed_in: true,
                email: String::new(),
                balances: "Network Error".to_string(),
                total_spend: "$0.00".to_string(),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_deepseek_token_nested() {
        let sample_yaml = r#"
version: 1
records:
  client-connection/browser-session:
    kind: session
    payload:
      secret: "abc"
  deepseek-account-platform/default:
    kind: grant
    payload:
      version: 1
      token: "test_secret_token_12345"
      issuer: "https://platform.deepseek.com"
"#;
        let token = parse_deepseek_token(sample_yaml);
        assert_eq!(token, Some("test_secret_token_12345".to_string()));
    }

    #[test]
    fn test_parse_deepseek_token_unquoted() {
        let sample_yaml = r#"
records:
  deepseek-account-platform/default:
    payload:
      token: dsh_live_token_unquoted_xyz
"#;
        let token = parse_deepseek_token(sample_yaml);
        assert_eq!(token, Some("dsh_live_token_unquoted_xyz".to_string()));
    }

    #[test]
    fn test_format_amount() {
        let s_val = serde_json::Value::String("8.16".to_string());
        assert_eq!(format_amount(Some(&s_val), Some("USD")), Some("$8.16 USD".to_string()));

        let n_val = serde_json::json!(12.50);
        assert_eq!(format_amount(Some(&n_val), Some("USD")), Some("$12.50 USD".to_string()));

        let invalid = serde_json::Value::Null;
        assert_eq!(format_amount(Some(&invalid), Some("USD")), None);
        assert_eq!(format_amount(None, Some("USD")), None);
    }

    #[tokio::test]
    async fn test_live_deepseek_status_does_not_panic() {
        let status = get_deepseek_status().await;
        println!(
            "Live DeepSeek detected: {}, signed_in: {}, balance: {}",
            status.detected, status.signed_in, status.balances
        );
    }
}
