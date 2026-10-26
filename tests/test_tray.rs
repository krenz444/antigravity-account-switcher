#[path = "../src/tray.rs"]
mod tray;

use std::sync::mpsc;
use std::time::Duration;
use tray::{
    start_tray, TrayEvent, IDM_EXIT, IDM_REFRESH_QUOTAS, IDM_SHOW_SWITCHBOARD, TRAY_ICON_ID,
    WM_TRAY_CALLBACK,
};
use windows_sys::Win32::Foundation::{LPARAM, WPARAM};
use windows_sys::Win32::UI::WindowsAndMessaging::{PostMessageW, WM_COMMAND, WM_LBUTTONUP};

#[test]
fn test_tray_events() {
    let events = vec![
        TrayEvent::ToggleWindow,
        TrayEvent::ShowWindow,
        TrayEvent::HideWindow,
        TrayEvent::RefreshQuotas,
        TrayEvent::Exit,
    ];

    // Verify variants and debug representation
    assert_eq!(format!("{:?}", TrayEvent::ToggleWindow), "ToggleWindow");
    assert_eq!(format!("{:?}", TrayEvent::ShowWindow), "ShowWindow");
    assert_eq!(format!("{:?}", TrayEvent::HideWindow), "HideWindow");
    assert_eq!(format!("{:?}", TrayEvent::RefreshQuotas), "RefreshQuotas");
    assert_eq!(format!("{:?}", TrayEvent::Exit), "Exit");

    // Verify equality, clone, copy
    for e in &events {
        let cloned = *e;
        assert_eq!(*e, cloned);
    }

    // Verify pattern matching exhaustiveness
    for e in events {
        match e {
            TrayEvent::ToggleWindow => {}
            TrayEvent::ShowWindow => {}
            TrayEvent::HideWindow => {}
            TrayEvent::RefreshQuotas => {}
            TrayEvent::Exit => {}
        }
    }
}

#[test]
fn test_tray_lifecycle() {
    // Spawns start_tray, verifies handle creation, and drops cleanly without hanging
    let res = start_tray("Antigravity Switchboard", |_| {});
    assert!(res.is_ok(), "Failed to start tray: {:?}", res.err());

    let handle = res.unwrap();
    assert!(!handle.hwnd().is_null(), "Tray window HWND should not be null");
    assert!(handle.thread_id() > 0, "Tray thread ID should be positive");

    // Verify update_tip helper
    let _ = handle.update_tip("Updated Tooltip");

    // Drop handle cleanly
    drop(handle);
}

#[test]
fn test_tray_message_dispatch() {
    let (tx, rx) = mpsc::channel();
    let res = start_tray("Antigravity Switchboard Dispatch Test", move |evt| {
        let _ = tx.send(evt);
    });
    assert!(res.is_ok(), "Failed to start tray: {:?}", res.err());
    let handle = res.unwrap();

    unsafe {
        // 1. Simulate tray left-click (WM_LBUTTONUP)
        let post1 = PostMessageW(
            handle.hwnd(),
            WM_TRAY_CALLBACK,
            TRAY_ICON_ID as WPARAM,
            WM_LBUTTONUP as LPARAM,
        );
        assert_ne!(post1, 0, "PostMessageW WM_LBUTTONUP failed");
        let recv1 = rx.recv_timeout(Duration::from_secs(2));
        assert_eq!(recv1.unwrap(), TrayEvent::ToggleWindow);

        // 2. Simulate menu command: Show Switchboard
        let post2 = PostMessageW(handle.hwnd(), WM_COMMAND, IDM_SHOW_SWITCHBOARD as WPARAM, 0);
        assert_ne!(post2, 0, "PostMessageW IDM_SHOW_SWITCHBOARD failed");
        let recv2 = rx.recv_timeout(Duration::from_secs(2));
        assert_eq!(recv2.unwrap(), TrayEvent::ShowWindow);

        // 3. Simulate menu command: Refresh Quotas
        let post3 = PostMessageW(handle.hwnd(), WM_COMMAND, IDM_REFRESH_QUOTAS as WPARAM, 0);
        assert_ne!(post3, 0, "PostMessageW IDM_REFRESH_QUOTAS failed");
        let recv3 = rx.recv_timeout(Duration::from_secs(2));
        assert_eq!(recv3.unwrap(), TrayEvent::RefreshQuotas);

        // 4. Simulate menu command: Exit
        let post4 = PostMessageW(handle.hwnd(), WM_COMMAND, IDM_EXIT as WPARAM, 0);
        assert_ne!(post4, 0, "PostMessageW IDM_EXIT failed");
        let recv4 = rx.recv_timeout(Duration::from_secs(2));
        assert_eq!(recv4.unwrap(), TrayEvent::Exit);
    }

    drop(handle);
}
