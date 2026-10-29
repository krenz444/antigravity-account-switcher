slint::include_modules!();

#[path = "../src/models.rs"]
mod models;

#[path = "../src/router.rs"]
mod router;

use std::sync::Mutex;
static TEST_MUTEX: Mutex<()> = Mutex::new(());

#[test]
fn test_paths_and_discovery() {
    let _lock = TEST_MUTEX.lock().unwrap();
    std::env::remove_var("GEMINI_DIR");
    println!("Gemini dir: {:?}", router::gemini_dir());
    println!("Profiles dir: {:?}", router::profiles_dir());
    println!("Active oauth: {:?}", router::active_oauth_path());
    println!("Active accounts: {:?}", router::active_accounts_path());
    println!("App storage: {:?}", router::app_storage_path());
    println!("State file: {:?}", router::state_file_path());

    let live_email = router::get_live_antigravity_email();
    println!("Live email: {:?}", live_email);

    let profiles = router::list_profiles();
    println!("Discovered {} profiles:", profiles.len());
    for p in &profiles {
        println!(" - {} ({}) [live: {}]", p.name, p.email, p.is_live);
    }

    assert!(!profiles.is_empty(), "Profiles should not be empty on GIZMO");
    assert!(profiles.iter().any(|p| p.name == "google_1"));
    assert!(profiles.iter().any(|p| p.name == "google_2"));
    assert!(profiles.iter().any(|p| p.name == "google_3"));
    assert!(profiles.iter().any(|p| p.name == "google_4"));
    assert!(profiles.iter().any(|p| p.name == "google_5"));

    // Invariant: At most one profile can ever be live at any time
    let live_count = profiles.iter().filter(|p| p.is_live).count();
    assert!(
        live_count <= 1,
        "Invariant violated: expected at most 1 live profile, found {}",
        live_count
    );
}

#[test]
fn test_single_active_profile_invariant() {
    let _lock = TEST_MUTEX.lock().unwrap();
    let temp_dir = std::env::temp_dir().join(format!("test_single_active_{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis()));
    let temp_profiles = temp_dir.join("profiles");
    let test_p1 = temp_profiles.join("google_1");
    let test_p2 = temp_profiles.join("google_2");
    let test_p3 = temp_profiles.join("google_3");

    std::fs::create_dir_all(&test_p1).unwrap();
    std::fs::create_dir_all(&test_p2).unwrap();
    std::fs::create_dir_all(&test_p3).unwrap();

    std::fs::write(test_p1.join("profile_meta.json"), r#"{"name": "google_1", "email": "p1@example.com"}"#).unwrap();
    std::fs::write(test_p2.join("profile_meta.json"), r#"{"name": "google_2", "email": "p2@example.com"}"#).unwrap();
    std::fs::write(test_p3.join("profile_meta.json"), r#"{"name": "google_3", "email": "p3@example.com"}"#).unwrap();

    let mock_storage = temp_dir.join("mock_app_storage.json");
    let mock_state = temp_dir.join("mock_usage_state.json");

    // Scenario: State file points to google_2, but live IDE session is p3@example.com (google_3)
    std::fs::write(&mock_storage, r#"{"jetski.onboarding.lastLoginUsername": "p3@example.com"}"#).unwrap();
    std::fs::write(&mock_state, r#"{"active_google_profile": "google_2"}"#).unwrap();

    std::env::set_var("GEMINI_DIR", &temp_dir);
    std::env::set_var("ANTIGRAVITY_APP_STORAGE", &mock_storage);
    std::env::set_var("ANTIGRAVITY_STATE_FILE", &mock_state);
    std::env::set_var("ANTIGRAVITY_MOCK_CREDENTIALS", "1");

    let discovered = router::list_profiles();
    let live_profiles: Vec<_> = discovered.iter().filter(|p| p.is_live).collect();

    // Verify EXACTLY one profile is marked live (p3 matching live login wins over stale state)
    assert_eq!(live_profiles.len(), 1, "Must have exactly 1 live profile");
    assert_eq!(live_profiles[0].name, "google_3", "Live session email p3 should be the single live profile");

    std::env::remove_var("GEMINI_DIR");
    std::env::remove_var("ANTIGRAVITY_APP_STORAGE");
    std::env::remove_var("ANTIGRAVITY_STATE_FILE");
    std::env::remove_var("ANTIGRAVITY_MOCK_CREDENTIALS");
    let _ = std::fs::remove_dir_all(temp_dir);
}

#[test]
fn test_sanitization_and_validation() {
    assert!(router::is_valid_profile_name("google_1"));
    assert!(router::is_valid_profile_name("acc-backup"));
    assert!(!router::is_valid_profile_name(".."));
    assert!(!router::is_valid_profile_name("../etc/passwd"));
    assert!(!router::is_valid_profile_name("foo/bar"));
    assert!(!router::is_valid_profile_name("foo\\bar"));
    assert!(!router::is_valid_profile_name("con"));
    assert!(!router::is_valid_profile_name("CON"));
    assert!(!router::is_valid_profile_name("nul"));
    assert!(!router::is_valid_profile_name("com1"));
    assert!(!router::is_valid_profile_name("lpt9"));
    assert!(!router::is_valid_profile_name(""));
    assert!(!router::is_valid_profile_name("CON.txt"));

    assert_eq!(router::sanitize_profile_name("google 1"), "google_1");
    assert_eq!(router::sanitize_profile_name("../hack/path"), "hack_path");
    assert_eq!(router::sanitize_profile_name(".."), "google_1");
    assert_eq!(router::sanitize_profile_name("   "), "google_1");
    assert_eq!(router::sanitize_profile_name("con"), "google_1");
    assert_eq!(router::sanitize_profile_name("COM1"), "google_1");
    assert_eq!(router::sanitize_profile_name("NUL"), "google_1");
}

#[test]
fn test_jwt_email_extraction() {
    // Valid minimal JWT payload: {"email": "test.user@domain.com"} -> base64url: eyJlbWFpbCI6ICJ0ZXN0LnVzZXJAZG9tYWluLmNvbSJ9
    let test_jwt = "eyJhbGciOiJSUzI1NiJ9.eyJlbWFpbCI6ICJ0ZXN0LnVzZXJAZG9tYWluLmNvbSJ9.signature";
    let email = router::extract_email_from_jwt(test_jwt);
    assert_eq!(email, Some("test.user@domain.com".to_string()));

    // Test blob extraction with id_token_email
    let blob_json = r#"{"id_token_email":"ericfurphy2@gmail.com","auth_method":"consumer"}"#;
    let blob_email = router::extract_email_from_blob(blob_json.as_bytes());
    assert_eq!(blob_email, Some("ericfurphy2@gmail.com".to_string()));
}

#[test]
fn test_mock_profile_switching() {
    let _lock = TEST_MUTEX.lock().unwrap();
    let temp_dir = std::env::temp_dir().join(format!("test_gemini_{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis()));
    let temp_profiles = temp_dir.join("profiles");
    let test_p1 = temp_profiles.join("google_1");
    let test_p2 = temp_profiles.join("google_2");

    std::fs::create_dir_all(&test_p1).unwrap();
    std::fs::create_dir_all(&test_p2).unwrap();

    std::fs::write(test_p1.join("profile_meta.json"), r#"{"name": "google_1", "email": "p1@example.com", "alias": "Profile One"}"#).unwrap();
    std::fs::write(test_p1.join("google_accounts.json"), r#"{"active": "p1@example.com"}"#).unwrap();
    std::fs::write(test_p1.join("oauth_creds.json"), r#"{"access_token": "token1", "refresh_token": "ref1", "id_token": "id1"}"#).unwrap();

    std::fs::write(test_p2.join("profile_meta.json"), r#"{"name": "google_2", "email": "p2@example.com", "alias": "Profile Two"}"#).unwrap();
    std::fs::write(test_p2.join("google_accounts.json"), r#"{"active": "p2@example.com"}"#).unwrap();
    std::fs::write(test_p2.join("oauth_creds.json"), r#"{"access_token": "token2", "refresh_token": "ref2", "id_token": "id2"}"#).unwrap();

    let mock_storage = temp_dir.join("mock_app_storage.json");
    let mock_state = temp_dir.join("mock_usage_state.json");
    std::fs::write(&mock_storage, r#"{"jetski.onboarding.lastLoginUsername": "p1@example.com"}"#).unwrap();

    // Set isolated test environment variables so host credentials and files are never mutated
    std::env::set_var("GEMINI_DIR", &temp_dir);
    std::env::set_var("ANTIGRAVITY_APP_STORAGE", &mock_storage);
    std::env::set_var("ANTIGRAVITY_STATE_FILE", &mock_state);
    std::env::set_var("ANTIGRAVITY_MOCK_CREDENTIALS", "1");

    let profiles = router::list_profiles();
    assert_eq!(profiles.len(), 2);

    // Switch to p2 by email
    let switch_res = router::switch_google_profile("p2@example.com");
    if let Err(ref e) = switch_res {
        eprintln!("switch_google_profile error: {:?}", e);
    }
    assert!(switch_res.is_ok());

    // Verify active files in temp_dir
    let active_accounts_content = std::fs::read_to_string(temp_dir.join("google_accounts.json")).unwrap();
    assert!(active_accounts_content.contains("p2@example.com"));

    let active_oauth_content = std::fs::read_to_string(temp_dir.join("oauth_creds.json")).unwrap();
    assert!(active_oauth_content.contains("token2"));

    // Verify app_storage was updated in isolated temp file
    let storage_content = std::fs::read_to_string(&mock_storage).unwrap();
    assert!(storage_content.contains("p2@example.com"));

    // Verify state file was updated in isolated temp file
    let state_content = std::fs::read_to_string(&mock_state).unwrap();
    assert!(state_content.contains("google_2"));

    // Verify isolated mock credential blob was written
    let mock_cred_file = temp_dir.join("mock_credential_blob.bin");
    assert!(mock_cred_file.exists());

    // Cleanup temp env vars and files
    std::env::remove_var("GEMINI_DIR");
    std::env::remove_var("ANTIGRAVITY_APP_STORAGE");
    std::env::remove_var("ANTIGRAVITY_STATE_FILE");
    std::env::remove_var("ANTIGRAVITY_MOCK_CREDENTIALS");
    let _ = std::fs::remove_dir_all(temp_dir);
}
