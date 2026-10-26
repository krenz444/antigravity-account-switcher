//! System Tray and Context Menu Integration for Antigravity Switchboard.
//! Native Win32 Shell API implementation supporting notification icons,
//! left-click toggle, and right-click context menu actions.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;
use windows_sys::Win32::Foundation::{GetLastError, HWND, LPARAM, LRESULT, POINT, WPARAM};
use windows_sys::Win32::System::Threading::GetCurrentThreadId;
use windows_sys::Win32::UI::Shell::{
    Shell_NotifyIconW, NIF_ICON, NIF_MESSAGE, NIF_TIP, NIM_ADD, NIM_DELETE, NIM_MODIFY,
    NOTIFYICONDATAW,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    AppendMenuW, CreatePopupMenu, CreateWindowExW, DefWindowProcW, DestroyMenu, DestroyWindow,
    DispatchMessageW, GetCursorPos, GetMessageW, GetWindowLongPtrW, LoadIconW, PostMessageW,
    PostQuitMessage, PostThreadMessageW, RegisterClassW, SetForegroundWindow, SetWindowLongPtrW,
    TrackPopupMenu, TranslateMessage, UnregisterClassW, CS_HREDRAW, CS_VREDRAW, GWLP_USERDATA,
    IDI_APPLICATION, MF_SEPARATOR, MF_STRING, MSG, TPM_BOTTOMALIGN, TPM_RETURNCMD,
    TPM_RIGHTBUTTON, WM_CLOSE, WM_COMMAND, WM_DESTROY, WM_LBUTTONUP, WM_QUIT, WM_RBUTTONUP,
    WM_USER, WNDCLASSW,
};

/// Custom window message used for system tray notification callbacks.
pub const WM_TRAY_CALLBACK: u32 = WM_USER + 100;

/// Identifier assigned to the switchboard system tray icon.
pub const TRAY_ICON_ID: u32 = 100;

/// Context menu command identifiers.
pub const IDM_SHOW_SWITCHBOARD: usize = 1001;
pub const IDM_REFRESH_QUOTAS: usize = 1002;
pub const IDM_EXIT: usize = 1003;

static CLASS_COUNTER: AtomicUsize = AtomicUsize::new(0);

/// Events emitted by system tray interactions.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[allow(dead_code)]
pub enum TrayEvent {
    ToggleWindow,
    ShowWindow,
    HideWindow,
    RefreshQuotas,
    Exit,
}

struct TrayContext {
    on_event: Box<dyn Fn(TrayEvent) + Send + 'static>,
}

/// Handle to an active system tray icon and its background message loop.
/// Dropping this handle cleans up the icon, destroys the notification window,
/// and terminates the background message thread.
pub struct TrayHandle {
    pub hwnd: HWND,
    pub thread_id: u32,
    thread_handle: Option<std::thread::JoinHandle<()>>,
    class_name: Vec<u16>,
}

unsafe impl Send for TrayHandle {}
unsafe impl Sync for TrayHandle {}

impl TrayHandle {
    /// Returns the window handle associated with the tray message receiver.
    #[allow(dead_code)]
    pub fn hwnd(&self) -> HWND {
        self.hwnd
    }

    /// Returns the OS thread ID hosting the tray message loop.
    #[allow(dead_code)]
    pub fn thread_id(&self) -> u32 {
        self.thread_id
    }

    /// Updates the tooltip string for the active tray icon.
    #[allow(dead_code)]
    pub fn update_tip(&self, tip: &str) -> bool {
        if self.hwnd.is_null() {
            return false;
        }
        let mut nid: NOTIFYICONDATAW = unsafe { std::mem::zeroed() };
        nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
        nid.hWnd = self.hwnd;
        nid.uID = TRAY_ICON_ID;
        nid.uFlags = NIF_TIP;
        set_tip(&mut nid.szTip, tip);
        unsafe { Shell_NotifyIconW(NIM_MODIFY, &nid) != 0 }
    }
}

impl Drop for TrayHandle {
    fn drop(&mut self) {
        unsafe {
            if !self.hwnd.is_null() {
                // Delete the notification icon
                let mut nid: NOTIFYICONDATAW = std::mem::zeroed();
                nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
                nid.hWnd = self.hwnd;
                nid.uID = TRAY_ICON_ID;
                Shell_NotifyIconW(NIM_DELETE, &nid);

                // Signal the window to close and destroy
                PostMessageW(self.hwnd, WM_CLOSE, 0, 0);
                DestroyWindow(self.hwnd);
            }

            if self.thread_id != 0 {
                // Ensure the background message loop breaks even if window was destroyed
                PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0);
            }
        }

        // Wait for the background thread to exit cleanly
        if let Some(handle) = self.thread_handle.take() {
            let _ = handle.join();
        }

        // Unregister the custom window class
        if !self.class_name.is_empty() {
            unsafe {
                UnregisterClassW(self.class_name.as_ptr(), std::ptr::null_mut());
            }
        }
    }
}

/// Starts the system tray integration on a dedicated background OS thread.
pub fn start_tray<F>(
    tip: &str,
    on_event: F,
) -> Result<TrayHandle, Box<dyn std::error::Error + Send + Sync>>
where
    F: Fn(TrayEvent) + Send + 'static,
{
    let (tx, rx) = std::sync::mpsc::channel();
    let tip_owned = tip.to_string();

    let thread_handle = std::thread::Builder::new()
        .name("tray_thread".into())
        .spawn(move || {
            let res = init_tray_window(&tip_owned, Box::new(on_event));
            match res {
                Ok((hwnd, thread_id, class_name)) => {
                    let _ = tx.send(Ok((hwnd as isize, thread_id, class_name)));
                    run_message_loop();
                }
                Err(e) => {
                    let _ = tx.send(Err(e));
                }
            }
        })?;

    match rx.recv_timeout(Duration::from_secs(5)) {
        Ok(Ok((hwnd_raw, thread_id, class_name))) => Ok(TrayHandle {
            hwnd: hwnd_raw as HWND,
            thread_id,
            thread_handle: Some(thread_handle),
            class_name,
        }),
        Ok(Err(e)) => {
            let _ = thread_handle.join();
            Err(e)
        }
        Err(e) => Err(format!("Timed out waiting for tray initialization: {}", e).into()),
    }
}

fn to_wstring(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

fn set_tip(buf: &mut [u16; 128], tip: &str) {
    let mut count = 0;
    for c in tip.encode_utf16() {
        if count >= 127 {
            break;
        }
        buf[count] = c;
        count += 1;
    }
    buf[count] = 0;
}

fn init_tray_window(
    tip: &str,
    on_event: Box<dyn Fn(TrayEvent) + Send + 'static>,
) -> Result<(HWND, u32, Vec<u16>), Box<dyn std::error::Error + Send + Sync>> {
    let instance_id = CLASS_COUNTER.fetch_add(1, Ordering::SeqCst);
    let class_name_str = format!("AntigravitySwitchboardTray_{}_{}", std::process::id(), instance_id);
    let class_name = to_wstring(&class_name_str);

    unsafe {
        let mut wc: WNDCLASSW = std::mem::zeroed();
        wc.style = CS_HREDRAW | CS_VREDRAW;
        wc.lpfnWndProc = Some(wndproc);
        wc.lpszClassName = class_name.as_ptr();

        let atom = RegisterClassW(&wc);
        if atom == 0 {
            let err = GetLastError();
            return Err(format!("RegisterClassW failed (error: {})", err).into());
        }

        let window_name = to_wstring("AntigravitySwitchboardTrayReceiver");
        let hwnd = CreateWindowExW(
            0,
            class_name.as_ptr(),
            window_name.as_ptr(),
            0,
            0,
            0,
            0,
            0,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null(),
        );

        if hwnd.is_null() {
            let err = GetLastError();
            UnregisterClassW(class_name.as_ptr(), std::ptr::null_mut());
            return Err(format!("CreateWindowExW failed (error: {})", err).into());
        }

        // Store tray callback context in user data
        let ctx = Box::new(TrayContext { on_event });
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, Box::into_raw(ctx) as isize);

        // Load application icon
        let icon = LoadIconW(std::ptr::null_mut(), IDI_APPLICATION);

        // Register notification icon with Shell
        let mut nid: NOTIFYICONDATAW = std::mem::zeroed();
        nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
        nid.hWnd = hwnd;
        nid.uID = TRAY_ICON_ID;
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
        nid.uCallbackMessage = WM_TRAY_CALLBACK;
        nid.hIcon = icon;
        set_tip(&mut nid.szTip, tip);

        let res = Shell_NotifyIconW(NIM_ADD, &nid);
        if res == 0 {
            // Note: In non-interactive desktops or background processes where explorer tray
            // is not hosted, NIM_ADD returns 0. The window and callbacks remain active.
            log::warn!("Shell_NotifyIconW(NIM_ADD) returned 0 (explorer tray may not be active in this session)");
        }

        let thread_id = GetCurrentThreadId();
        Ok((hwnd, thread_id, class_name))
    }
}

fn run_message_loop() {
    unsafe {
        let mut msg: MSG = std::mem::zeroed();
        while GetMessageW(&mut msg, std::ptr::null_mut(), 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}

unsafe fn dispatch_event(hwnd: HWND, event: TrayEvent) {
    let ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut TrayContext;
    if !ptr.is_null() {
        let ctx = &*ptr;
        if let Err(e) = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            (ctx.on_event)(event);
        })) {
            log::error!("Tray event callback panicked: {:?}", e);
        }
    }
}

unsafe extern "system" fn wndproc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        WM_TRAY_CALLBACK => {
            let event_msg = (lparam & 0xFFFF) as u32;
            match event_msg {
                WM_LBUTTONUP => {
                    dispatch_event(hwnd, TrayEvent::ToggleWindow);
                    0
                }
                WM_RBUTTONUP => {
                    SetForegroundWindow(hwnd);

                    let hmenu = CreatePopupMenu();
                    if !hmenu.is_null() {
                        let show_str = to_wstring("Show Switchboard");
                        let refresh_str = to_wstring("Refresh Quotas");
                        let exit_str = to_wstring("Exit");

                        AppendMenuW(hmenu, MF_STRING, IDM_SHOW_SWITCHBOARD, show_str.as_ptr());
                        AppendMenuW(hmenu, MF_STRING, IDM_REFRESH_QUOTAS, refresh_str.as_ptr());
                        AppendMenuW(hmenu, MF_SEPARATOR, 0, std::ptr::null());
                        AppendMenuW(hmenu, MF_STRING, IDM_EXIT, exit_str.as_ptr());

                        let mut pt = POINT { x: 0, y: 0 };
                        GetCursorPos(&mut pt);

                        let cmd = TrackPopupMenu(
                            hmenu,
                            TPM_RIGHTBUTTON | TPM_BOTTOMALIGN | TPM_RETURNCMD,
                            pt.x,
                            pt.y,
                            0,
                            hwnd,
                            std::ptr::null(),
                        );

                        match cmd as usize {
                            IDM_SHOW_SWITCHBOARD => dispatch_event(hwnd, TrayEvent::ShowWindow),
                            IDM_REFRESH_QUOTAS => dispatch_event(hwnd, TrayEvent::RefreshQuotas),
                            IDM_EXIT => dispatch_event(hwnd, TrayEvent::Exit),
                            _ => {}
                        }

                        DestroyMenu(hmenu);
                        PostMessageW(hwnd, 0, 0, 0); // WM_NULL per Win32 tray menu guidelines
                    }
                    0
                }
                _ => DefWindowProcW(hwnd, msg, wparam, lparam),
            }
        }
        WM_COMMAND => {
            let id = (wparam & 0xFFFF) as usize;
            match id {
                IDM_SHOW_SWITCHBOARD => {
                    dispatch_event(hwnd, TrayEvent::ShowWindow);
                    0
                }
                IDM_REFRESH_QUOTAS => {
                    dispatch_event(hwnd, TrayEvent::RefreshQuotas);
                    0
                }
                IDM_EXIT => {
                    dispatch_event(hwnd, TrayEvent::Exit);
                    0
                }
                _ => DefWindowProcW(hwnd, msg, wparam, lparam),
            }
        }
        WM_CLOSE => {
            let mut nid: NOTIFYICONDATAW = std::mem::zeroed();
            nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
            nid.hWnd = hwnd;
            nid.uID = TRAY_ICON_ID;
            Shell_NotifyIconW(NIM_DELETE, &nid);
            DestroyWindow(hwnd);
            0
        }
        WM_DESTROY => {
            let ptr = SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0) as *mut TrayContext;
            if !ptr.is_null() {
                drop(Box::from_raw(ptr));
            }
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}
