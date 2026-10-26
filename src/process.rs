//! Antigravity Client Process Supervision
//! Native process management and credential recycling for Antigravity Client
//! using `sysinfo` v0.31.

use log::{info, warn};
use std::error::Error;
use std::path::{Path, PathBuf};
use std::process::Command;
use sysinfo::{ProcessesToUpdate, System};

/// Checks if any Antigravity Client `language_server.exe` process is currently active.
pub fn is_language_server_running() -> bool {
    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All);
    sys.processes().values().any(|proc| {
        let name = proc.name().to_string_lossy();
        name.eq_ignore_ascii_case("language_server.exe") || name.eq_ignore_ascii_case("language_server")
    })
}

/// Checks if the main `antigravity.exe` client process is currently running.
pub fn is_client_running() -> bool {
    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All);
    sys.processes().values().any(|proc| {
        let name = proc.name().to_string_lossy();
        name.eq_ignore_ascii_case("antigravity.exe") || name.eq_ignore_ascii_case("antigravity")
    })
}

/// Discovers active `language_server.exe` PIDs for diagnostics.
#[allow(dead_code)]
pub fn get_language_server_pids() -> Vec<u32> {
    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All);
    sys.processes()
        .iter()
        .filter_map(|(pid, proc)| {
            let name = proc.name().to_string_lossy();
            if name.eq_ignore_ascii_case("language_server.exe") || name.eq_ignore_ascii_case("language_server") {
                Some(pid.as_u32())
            } else {
                None
            }
        })
        .collect()
}

/// Discovers active `antigravity.exe` PID if running.
#[allow(dead_code)]
pub fn get_client_pid() -> Option<u32> {
    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All);
    sys.processes()
        .iter()
        .find_map(|(pid, proc)| {
            let name = proc.name().to_string_lossy();
            if name.eq_ignore_ascii_case("antigravity.exe") || name.eq_ignore_ascii_case("antigravity") {
                Some(pid.as_u32())
            } else {
                None
            }
        })
}

/// Finds the executable path for `antigravity.exe` on this machine.
#[allow(dead_code)]
pub fn find_antigravity_executable() -> Option<PathBuf> {
    // 1. Inspect running process if available
    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All);
    for proc in sys.processes().values() {
        let name = proc.name().to_string_lossy();
        if name.eq_ignore_ascii_case("antigravity.exe") || name.eq_ignore_ascii_case("antigravity") {
            if let Some(exe) = proc.exe() {
                if exe.exists() {
                    return Some(exe.to_path_buf());
                }
            }
        }
    }

    // 2. Inspect standard Windows user installation
    if let Ok(local_app_data) = std::env::var("LOCALAPPDATA") {
        let path = Path::new(&local_app_data).join("Programs").join("Antigravity").join("Antigravity.exe");
        if path.exists() {
            return Some(path);
        }
    }

    // 3. Inspect Program Files
    if let Ok(prog_files) = std::env::var("ProgramFiles") {
        let path = Path::new(&prog_files).join("Antigravity").join("Antigravity.exe");
        if path.exists() {
            return Some(path);
        }
    }

    None
}

/// Terminates all running `language_server.exe` processes.
/// The Antigravity Client automatically respawns `language_server.exe` with updated credentials.
/// Returns the number of terminated processes.
pub fn restart_language_server() -> Result<usize, Box<dyn Error>> {
    info!("Scanning for language_server.exe instances to terminate...");
    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All);

    let mut terminated = 0;
    for (pid, proc) in sys.processes() {
        let name = proc.name().to_string_lossy();
        if name.eq_ignore_ascii_case("language_server.exe") || name.eq_ignore_ascii_case("language_server") {
            info!("Terminating language_server.exe process (PID: {})...", pid);
            if proc.kill() {
                terminated += 1;
            } else {
                warn!("Failed to terminate language_server.exe process (PID: {})", pid);
            }
        }
    }

    info!(
        "Terminated {} language_server.exe process(es). Antigravity Client will respawn it with active credentials.",
        terminated
    );
    Ok(terminated)
}

/// Restarts the Antigravity Client:
/// 1. Terminates `language_server.exe`.
/// 2. If `antigravity.exe` is running, terminates it and relaunches.
/// 3. If not running, launches executable if found.
#[allow(dead_code)]
pub fn restart_antigravity_client() -> Result<(), Box<dyn Error>> {
    info!("Executing Antigravity Client restart sequence...");

    // 1. Terminate language server
    let _ = restart_language_server()?;

    // 2. Discover executable path before terminating client
    let exe_path = find_antigravity_executable();

    // 3. Terminate running Antigravity Client instances
    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All);
    let mut was_running = false;

    for (pid, proc) in sys.processes() {
        let name = proc.name().to_string_lossy();
        if name.eq_ignore_ascii_case("antigravity.exe") || name.eq_ignore_ascii_case("antigravity") {
            info!("Terminating Antigravity Client process (PID: {})...", pid);
            proc.kill();
            was_running = true;
        }
    }

    // 4. Relaunch if path is known
    if let Some(path) = exe_path {
        info!("Relaunching Antigravity Client from {:?}", path);
        std::thread::sleep(std::time::Duration::from_millis(300));
        Command::new(path).spawn()?;
    } else if was_running {
        warn!("Could not locate Antigravity.exe path on disk to relaunch.");
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_process_queries_dont_panic() {
        let ls_running = is_language_server_running();
        let client_running = is_client_running();
        let _ = get_language_server_pids();
        let _ = get_client_pid();
        let _ = find_antigravity_executable();
        println!("Antigravity Language Server running: {}", ls_running);
        println!("Antigravity Client running: {}", client_running);
    }
}
