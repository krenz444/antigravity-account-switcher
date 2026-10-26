slint::include_modules!();

#[path = "../src/models.rs"]
mod models;

#[path = "../src/router.rs"]
mod router;

#[path = "../src/process.rs"]
mod process;

#[path = "../src/google_api.rs"]
mod google_api;

#[test]
fn test_oauth_credentials_decoding() {
    let client_id = google_api::get_client_id();
    let client_secret = google_api::get_client_secret();

    assert!(client_id.starts_with("1071006060591-"));
    assert!(client_id.ends_with(".apps.googleusercontent.com"));
    assert!(client_secret.starts_with("GOCSPX-"));
    assert_eq!(client_secret.len(), 35);
}

#[test]
fn test_countdown_formatter() {
    assert_eq!(google_api::format_countdown(""), "Ready");
    assert_eq!(google_api::format_countdown("Ready"), "Ready");
    assert_eq!(google_api::format_countdown("none"), "Ready");
    assert_eq!(google_api::format_countdown("2020-01-01T00:00:00Z"), "Ready");

    // Duration-based deterministic checks
    assert_eq!(google_api::format_duration_countdown(0), "Ready");
    assert_eq!(google_api::format_duration_countdown(-100), "Ready");
    assert_eq!(google_api::format_duration_countdown(30), "Reset: <1m");
    assert_eq!(google_api::format_duration_countdown(45 * 60), "Reset: 45m");
    assert_eq!(google_api::format_duration_countdown(2 * 3600 + 15 * 60), "Reset: 2h 15m");
    assert_eq!(google_api::format_duration_countdown(3 * 3600), "Reset: 3h");

    // Future timestamp countdown check
    let future_time = chrono::Utc::now() + chrono::Duration::hours(2) + chrono::Duration::minutes(15);
    let iso_str = future_time.to_rfc3339();
    let res = google_api::format_countdown(&iso_str);
    assert!(res.starts_with("Reset: 2h") || res.starts_with("Reset: 1h 59m"));
}

#[test]
fn test_weekly_reset_formatter() {
    assert_eq!(google_api::format_weekly_reset(""), "Resets weekly");
    assert_eq!(google_api::format_weekly_reset("ready"), "Resets weekly");
    assert_eq!(google_api::format_weekly_reset("none"), "Resets weekly");
    assert_eq!(google_api::format_weekly_reset("Resets Mon 7:00 PM"), "Resets Mon 7:00 PM");

    let formatted = google_api::format_weekly_reset("2026-11-02T19:00:00Z");
    assert!(formatted.starts_with("Resets "));
}

#[test]
fn test_parse_quota_summary_mock() {
    let mock_json = serde_json::json!({
        "response": {
            "groups": [
                {
                    "displayName": "Gemini Models",
                    "buckets": [
                        {
                            "bucketId": "gemini-weekly",
                            "window": "weekly",
                            "remainingFraction": 0.85,
                            "resetTime": "2026-11-01T18:00:00Z",
                            "description": "Weekly bucket"
                        },
                        {
                            "bucketId": "gemini-5h",
                            "window": "5h",
                            "remainingFraction": 0.42,
                            "resetTime": "2026-10-26T22:00:00Z",
                            "description": "5h bucket"
                        }
                    ]
                },
                {
                    "displayName": "Claude and GPT models",
                    "buckets": [
                        {
                            "bucketId": "3p-weekly",
                            "window": "weekly",
                            "remainingFraction": 0.90
                        },
                        {
                            "bucketId": "3p-5h",
                            "window": "5h",
                            "remainingFraction": 0.75
                        }
                    ]
                }
            ]
        }
    });

    let quota = google_api::parse_quota_summary(&mock_json);
    assert_eq!(quota.pct_5h, 42.0);
    assert_eq!(quota.weekly_pct, 85.0);
    assert_eq!(quota.reset_5h, "2026-10-26T22:00:00Z");
    assert_eq!(quota.desc_5h, "5h bucket");
    assert_eq!(quota.weekly_reset, "2026-11-01T18:00:00Z");
    assert_eq!(quota.claude_5h_pct, 75.0);
    assert_eq!(quota.claude_weekly_pct, 90.0);
    assert_eq!(quota.tier_label, "Pro");
}

#[test]
fn test_parse_tier_from_json() {
    let pro_mock = serde_json::json!({
        "response": {
            "paidTier": {
                "id": "g1-pro-tier",
                "name": "Google AI Pro"
            }
        }
    });
    let (id, label) = google_api::parse_tier_from_json(&pro_mock);
    assert_eq!(id, "g1-pro-tier");
    assert_eq!(label, "Google AI Pro");

    let ultra_mock = serde_json::json!({
        "paidTier": {
            "id": "g1-ultra-tier",
            "name": "Google AI Ultra"
        }
    });
    let (id_u, label_u) = google_api::parse_tier_from_json(&ultra_mock);
    assert_eq!(id_u, "g1-ultra-tier");
    assert_eq!(label_u, "Google AI Ultra");

    let free_mock = serde_json::json!({
        "response": {
            "currentTier": {
                "id": "free-tier",
                "name": "Antigravity"
            }
        }
    });
    let (id_f, label_f) = google_api::parse_tier_from_json(&free_mock);
    assert_eq!(id_f, "free-tier");
    assert_eq!(label_f, "Free Tier");
}

#[tokio::test]
async fn test_in_process_language_server_discovery() {
    if crate::process::is_language_server_running() {
        let conn_opt = google_api::discover_language_server().await;
        if let Some(conn) = conn_opt {
            println!("In-process discovery succeeded: port {}, token len {}", conn.port, conn.csrf_token.len());
            assert!(conn.port > 0);
            assert!(!conn.csrf_token.is_empty());
        }
    }
}

#[tokio::test]
async fn test_live_profile_quota_fetch_if_available() {
    let profiles = router::list_profiles();
    if let Some(p) = profiles.first() {
        let q = google_api::fetch_profile_quota(&p.name).await;
        println!("Quota fetched for profile '{}':", p.name);
        println!("  Tier: {}", q.tier_label);
        println!("  Session Quota: {}% (Reset: {})", q.pct_5h, q.reset_5h);
        println!("  Weekly Quota: {}% (Reset: {})", q.weekly_pct, q.weekly_reset);
        println!("  Status: {}", q.status_text);
        println!("  Countdown: {}", q.countdown_text);
        assert!(!q.status_text.is_empty());
    }
}
