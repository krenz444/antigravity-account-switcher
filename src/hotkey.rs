//! Global Hotkey and Single-Instance Mutex Subsystem
//!
//! Provides Windows OS-level single-instance enforcement via named kernel mutexes,
//! window focusing for already-running instances, and a dedicated background OS thread
//! for global hotkey registration (`Ctrl+Alt+S`) and message loop dispatching.

use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::sync::mpsc;
use std::thread;

use windows_sys::Win32::Foundation::{
    CloseHandle, ERROR_ALREADY_EXISTS, GetLastError, HANDLE, HWND,
};
use windows_sys::Win32::System::Threading::{CreateMutexW, GetCurrentThreadId};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    RegisterHotKey, UnregisterHotKey, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    FindWindowW, GetMessageW, PeekMessageW, PostThreadMessageW, SetForegroundWindow, ShowWindow,
    MSG, PM_NOREMOVE, SW_RESTORE, WM_HOTKEY, WM_QUIT,
};

/// Hotkey identifier registered with Windows
pub const HOTKEY_ID: i32 = 1;

/// RAII guard holding a Windows named mutex handle.
///
/// When dropped, automatically calls `CloseHandle` to release the mutex ownership,
/// allowing subsequent application processes or restart loops to acquire it.
pub struct SingleInstanceGuard {
    handle: HANDLE,
}

unsafe impl Send for SingleInstanceGuard {}
unsafe impl Sync for SingleInstanceGuard {}

impl Drop for SingleInstanceGuard {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            unsafe {
                CloseHandle(self.handle);
            }
        }
    }
}

/// Attempts to acquire a single-instance named kernel mutex.
///
/// # Arguments
/// * `name` - Mutex name, typically prefixed with `Local\\` for per-session scoping.
///
/// # Returns
/// * `Some(SingleInstanceGuard)` if the mutex was newly created and acquired.
/// * `None` if an existing instance already holds the mutex or creation fails.
pub fn acquire_single_instance(name: &str) -> Option<SingleInstanceGuard> {
    let wide_name: Vec<u16> = OsStr::new(name)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    unsafe {
        let handle = CreateMutexW(std::ptr::null(), 0, wide_name.as_ptr());
        if handle.is_null() {
            return None;
        }

        if GetLastError() == ERROR_ALREADY_EXISTS {
            CloseHandle(handle);
            return None;
        }

        Some(SingleInstanceGuard { handle })
    }
}

/// Finds an existing window by its title, restores it if minimized, and brings it to foreground.
///
/// # Arguments
/// * `title` - Exact title text of the target window.
pub fn focus_existing_window(title: &str) {
    let wide_title: Vec<u16> = OsStr::new(title)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    unsafe {
        let hwnd: HWND = FindWindowW(std::ptr::null(), wide_title.as_ptr());
        if !hwnd.is_null() {
            ShowWindow(hwnd, SW_RESTORE);
            SetForegroundWindow(hwnd);
        }
    }
}

/// RAII handle managing the background OS thread running the global hotkey message loop.
///
/// When dropped, posts `WM_QUIT` to the thread's message queue and joins the thread,
/// ensuring hermetic lifecycle management and zero leaked background threads.
pub struct HotkeyHandle {
    thread_id: u32,
    join_handle: Option<thread::JoinHandle<()>>,
}

impl HotkeyHandle {
    /// Returns the OS thread ID of the hotkey message loop.
    #[allow(dead_code)]
    pub fn thread_id(&self) -> u32 {
        self.thread_id
    }
}

impl Drop for HotkeyHandle {
    fn drop(&mut self) {
        unsafe {
            PostThreadMessageW(
                self.thread_id,
                WM_QUIT,
                0 as usize,
                0 as isize,
            );
        }
        if let Some(handle) = self.join_handle.take() {
            let _ = handle.join();
        }
    }
}

/// Starts a dedicated background OS thread that registers the global `Ctrl+Alt+S` hotkey
/// and dispatches callbacks whenever triggered.
///
/// # Arguments
/// * `on_hotkey` - Closure invoked on each hotkey press.
///
/// # Returns
/// * `Ok(HotkeyHandle)` on successful initialization of thread and queue.
/// * `Err(...)` if thread communication or synchronization fails.
pub fn start_hotkey_listener<F>(
    on_hotkey: F,
) -> Result<HotkeyHandle, Box<dyn std::error::Error + Send + Sync>>
where
    F: Fn() + Send + 'static,
{
    let (tx, rx) = mpsc::channel();

    let join_handle = thread::spawn(move || {
        let thread_id = unsafe { GetCurrentThreadId() };

        // Force creation of the thread message queue before signaling caller
        let mut msg: MSG = unsafe { std::mem::zeroed() };
        unsafe {
            PeekMessageW(
                &mut msg,
                std::ptr::null_mut(),
                0,
                0,
                PM_NOREMOVE,
            );
        }

        let modifiers = (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT) as u32;
        let vk_s = 0x53u32; // 'S' virtual key

        let reg_ok = unsafe {
            RegisterHotKey(
                std::ptr::null_mut(),
                HOTKEY_ID,
                modifiers,
                vk_s,
            )
        };

        if reg_ok == 0 {
            let err = unsafe { GetLastError() };
            log::warn!("RegisterHotKey for Ctrl+Alt+S failed with error code: {}", err);
        } else {
            log::info!("Global hotkey Ctrl+Alt+S registered successfully (ID: {})", HOTKEY_ID);
        }

        // Notify caller that message queue and registration attempt are complete
        let _ = tx.send(thread_id);

        unsafe {
            while GetMessageW(&mut msg, std::ptr::null_mut(), 0, 0) > 0 {
                if msg.message == WM_HOTKEY && msg.wParam == HOTKEY_ID as usize {
                    on_hotkey();
                }
            }
        }

        if reg_ok != 0 {
            unsafe {
                UnregisterHotKey(std::ptr::null_mut(), HOTKEY_ID);
            }
        }
    });

    let thread_id = rx.recv()?;
    Ok(HotkeyHandle {
        thread_id,
        join_handle: Some(join_handle),
    })
}
