//! Integration and unit tests for SingleInstanceGuard and HotkeyHandle.

#[path = "../src/hotkey.rs"]
mod hotkey;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

#[test]
fn test_single_instance_acquisition() {
    let mutex_name = "Local\\TestSwitchboard_Worker1_Unique";

    // 1. First acquire succeeds
    let guard1 = hotkey::acquire_single_instance(mutex_name);
    assert!(
        guard1.is_some(),
        "First acquire for unique mutex should succeed"
    );

    // 2. Second acquire with the same name fails while guard1 is alive
    let guard2 = hotkey::acquire_single_instance(mutex_name);
    assert!(
        guard2.is_none(),
        "Second acquire while first guard is active should return None"
    );

    // 3. Drop guard1 to release mutex handle
    drop(guard1);

    // 4. Third acquire succeeds now that guard1 was dropped
    let guard3 = hotkey::acquire_single_instance(mutex_name);
    assert!(
        guard3.is_some(),
        "Third acquire after dropping first guard should succeed"
    );
}

#[test]
fn test_hotkey_lifecycle() {
    let flag = Arc::new(AtomicBool::new(false));
    let flag_clone = Arc::clone(&flag);

    let handle_res = hotkey::start_hotkey_listener(move || {
        flag_clone.store(true, Ordering::SeqCst);
    });

    assert!(
        handle_res.is_ok(),
        "Hotkey listener should spawn and initialize successfully"
    );
    let handle = handle_res.unwrap();
    assert!(
        handle.thread_id() > 0,
        "Hotkey listener should report a valid OS thread ID"
    );

    // Allow the background thread event loop to run briefly
    std::thread::sleep(Duration::from_millis(50));

    // Drop handle: should post WM_QUIT and join background thread cleanly
    drop(handle);
}

#[test]
fn test_focus_existing_window_nonexistent() {
    // Should safely execute Win32 FindWindowW without crash or panic when window is not found
    hotkey::focus_existing_window("__Antigravity_NonExistent_Test_Window_99999__");
}
