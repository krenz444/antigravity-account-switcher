//! Antigravity Switchboard - Native Desktop Application
//! Main entry point integrating profile routing, process supervision, multi-provider
//! quota telemetry (Google Cloud Code PA, Claude Code, DeepSeek Platform), and Slint UI.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod claude;
mod deepseek;
mod google_api;
mod hotkey;
mod models;
mod process;
mod router;
mod tray;

use log::{error, info, warn};
use slint::{ComponentHandle, Model, ModelRc, SharedString, VecModel};
use std::error::Error;
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

slint::include_modules!();

static REFRESH_IN_PROGRESS: AtomicBool = AtomicBool::new(false);

/// Synchronizes Slint AppWindow state with fast local profile discovery and process supervision.
fn refresh_ui_state(app: &AppWindow, preferred_selected_id: Option<&str>) {
    let profiles = router::list_profiles();
    let live_email = router::get_live_antigravity_email();
    let active_profile_name = router::get_active_profile_name();
    let ls_running = process::is_language_server_running();
    let client_running = process::is_client_running();

    let mut active_alias = String::from("No Active Account");
    let mut active_email = live_email.clone().unwrap_or_else(|| String::from("No Active Email"));

    let mut slint_accounts = Vec::new();

    for (idx, mut p) in profiles.into_iter().enumerate() {
        if let Some(ref live) = live_email {
            if !live.is_empty() && p.email.eq_ignore_ascii_case(live) {
                p.is_live = true;
            }
        }
        // Fallback: If no live email matched, use active profile tracked in state
        if !p.is_live && (live_email.is_none() || active_alias == "No Active Account") && p.name == active_profile_name {
            p.is_live = true;
        }

        if p.is_live {
            active_alias = if p.alias.is_empty() {
                p.name.clone()
            } else {
                p.alias.clone()
            };
            active_email = p.email.clone();
        }

        let is_selected = match preferred_selected_id {
            Some(id) => p.name == id,
            None => p.is_live || (idx == 0 && live_email.is_none()),
        };

        let status_text = if p.is_live { "Active" } else { "Standby" };

        let data = AccountData {
            id: p.name.clone().into(),
            alias: (if p.alias.is_empty() {
                p.name.clone()
            } else {
                p.alias.clone()
            })
            .into(),
            email: p.email.clone().into(),
            tier: "Pro".into(),
            is_live: p.is_live,
            is_selected,
            session_quota_pct: 100.0,
            session_quota_label: "100%".into(),
            weekly_quota_pct: 100.0,
            weekly_quota_label: "100%".into(),
            reset_countdown: "Full Quota".into(),
            weekly_reset_text: "Full Weekly Quota".into(),
            status_text: status_text.into(),
        };
        slint_accounts.push(data);
    }

    let accounts_model_rc: ModelRc<AccountData> = Rc::new(VecModel::from(slint_accounts)).into();
    app.set_accounts(accounts_model_rc);

    app.set_active_alias(active_alias.into());
    app.set_active_email(active_email.into());

    // Update Client Status on HeroBar
    if ls_running && client_running {
        app.set_client_status("Client Running (LS active)".into());
        app.set_client_connected(true);
    } else if ls_running {
        app.set_client_status("LS Active (Client background)".into());
        app.set_client_connected(true);
    } else if client_running {
        app.set_client_status("Client Running (LS standby)".into());
        app.set_client_connected(true);
    } else {
        app.set_client_status("Client Disconnected".into());
        app.set_client_connected(false);
    }
}

/// Triggers a full asynchronous multi-provider refresh across Google, Claude, and DeepSeek.
fn trigger_full_refresh(app_weak: slint::Weak<AppWindow>, preferred_selected_id: Option<String>) {
    if REFRESH_IN_PROGRESS
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        info!("Refresh already in progress — skipping redundant trigger");
        return;
    }

    if let Some(app) = app_weak.upgrade() {
        app.set_is_refreshing(true);
        app.set_app_status("Refreshing live quotas & telemetry...".into());
    }

    std::thread::spawn(move || {
        struct RefreshGuard;
        impl Drop for RefreshGuard {
            fn drop(&mut self) {
                REFRESH_IN_PROGRESS.store(false, Ordering::SeqCst);
            }
        }
        let _guard = RefreshGuard;

        let rt = match tokio::runtime::Builder::new_current_thread().enable_all().build() {
            Ok(r) => r,
            Err(e) => {
                error!("Failed to create local tokio runtime for background refresh: {}", e);
                return;
            }
        };

        rt.block_on(async move {
            info!("Executing background multi-provider telemetry synchronization...");

            // 1. Fetch Claude status from local CLI layout
            let claude = claude::get_claude_status();

            // 2. Fetch DeepSeek balance and platform spend via async HTTPS
            let deepseek = deepseek::get_deepseek_status().await;

            // 3. Fetch Google Cloud Code PA quotas for each discovered profile
            let profiles = router::list_profiles();
            let live_email = router::get_live_antigravity_email();
            let active_profile_name = router::get_active_profile_name();
            let ls_running = process::is_language_server_running();
            let client_running = process::is_client_running();

            let mut profile_quotas = Vec::new();
            for p in &profiles {
                let quota = google_api::fetch_profile_quota(&p.name).await;
                profile_quotas.push((p.clone(), quota));
            }

            // 4. Update Slint UI safely on the event loop
            let app_weak_clone = app_weak.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(app) = app_weak_clone.upgrade() {
                    let mut active_alias = String::from("No Active Account");
                    let mut active_email = live_email.clone().unwrap_or_else(|| String::from("No Active Email"));

                    let mut slint_accounts = Vec::new();
                    for (idx, (mut p, quota)) in profile_quotas.into_iter().enumerate() {
                        if let Some(ref live) = live_email {
                            if !live.is_empty() && p.email.eq_ignore_ascii_case(live) {
                                p.is_live = true;
                            }
                        }
                        if !p.is_live && (live_email.is_none() || active_alias == "No Active Account") && p.name == active_profile_name {
                            p.is_live = true;
                        }

                        if p.is_live {
                            active_alias = if p.alias.is_empty() {
                                p.name.clone()
                            } else {
                                p.alias.clone()
                            };
                            active_email = p.email.clone();
                        }

                        let is_selected = match preferred_selected_id.as_deref() {
                            Some(id) => p.name == id,
                            None => p.is_live || (idx == 0 && live_email.is_none()),
                        };

                        let status_text = if p.is_live { "Active" } else { "Standby" };

                        let weekly_reset_str = google_api::format_weekly_reset(&quota.weekly_reset);
                        let reset_countdown_str = if quota.pct_5h >= 100.0 {
                            "Full Quota".to_string()
                        } else {
                            quota.countdown_text.clone()
                        };

                        let data = AccountData {
                            id: p.name.clone().into(),
                            alias: (if p.alias.is_empty() {
                                p.name.clone()
                            } else {
                                p.alias.clone()
                            })
                            .into(),
                            email: p.email.clone().into(),
                            tier: quota.tier_label.clone().into(),
                            is_live: p.is_live,
                            is_selected,
                            session_quota_pct: quota.pct_5h,
                            session_quota_label: format!("{:.0}%", quota.pct_5h).into(),
                            weekly_quota_pct: quota.weekly_pct,
                            weekly_quota_label: format!("{:.0}%", quota.weekly_pct).into(),
                            reset_countdown: reset_countdown_str.into(),
                            weekly_reset_text: weekly_reset_str.into(),
                            status_text: status_text.into(),
                        };
                        slint_accounts.push(data);
                    }

                    let accounts_model_rc: ModelRc<AccountData> = Rc::new(VecModel::from(slint_accounts)).into();
                    app.set_accounts(accounts_model_rc);
                    app.set_active_alias(active_alias.into());
                    app.set_active_email(active_email.into());

                    // Update HeroBar Client Status
                    if ls_running && client_running {
                        app.set_client_status("Client Running (LS active)".into());
                        app.set_client_connected(true);
                    } else if ls_running {
                        app.set_client_status("LS Active (Client background)".into());
                        app.set_client_connected(true);
                    } else if client_running {
                        app.set_client_status("Client Running (LS standby)".into());
                        app.set_client_connected(true);
                    } else {
                        app.set_client_status("Client Disconnected".into());
                        app.set_client_connected(false);
                    }

                    // Update Claude Card
                    app.set_claude_email(if claude.email.is_empty() {
                        "Not Signed In".into()
                    } else {
                        claude.email.into()
                    });
                    app.set_claude_tier(claude.tier_label.into());
                    app.set_claude_session_pct(claude.quota_5h_pct);
                    app.set_claude_session_label(format!("{:.0}%", claude.quota_5h_pct).into());
                    app.set_claude_weekly_pct(claude.quota_weekly_pct);
                    app.set_claude_weekly_label(format!("{:.0}%", claude.quota_weekly_pct).into());
                    app.set_claude_reset(claude.reset_5h_desc.into());

                    let tokens_text = if let Some(ref u) = claude.usage {
                        let total_tokens = u.input_tokens + u.output_tokens;
                        let tok_str = if total_tokens >= 1_000_000 {
                            format!("{:.1}M", total_tokens as f64 / 1_000_000.0)
                        } else if total_tokens >= 1_000 {
                            format!("{:.0}k", total_tokens as f64 / 1_000.0)
                        } else {
                            format!("{}", total_tokens)
                        };
                        format!("{} tokens (${:.2})", tok_str, u.cost_usd)
                    } else {
                        "No usage recorded".to_string()
                    };
                    app.set_claude_tokens(tokens_text.into());
                    app.set_claude_connected(claude.detected);

                    // Update DeepSeek Card
                    app.set_deepseek_balance(deepseek.balances.into());
                    app.set_deepseek_status(if deepseek.signed_in {
                        "Online / Ready".into()
                    } else {
                        "Offline / Signed Out".into()
                    });
                    app.set_deepseek_tier("Pay-as-you-go".into());
                    app.set_deepseek_usage(format!("Month: {}", deepseek.total_spend).into());
                    app.set_deepseek_connected(deepseek.detected && deepseek.signed_in);

                    app.set_is_refreshing(false);
                    app.set_app_status("Quotas synchronized".into());
                    info!("Live telemetry refresh complete: Quotas synchronized.");
                }
            });
        });
    });
}

fn main() -> Result<(), Box<dyn Error>> {
    // 0. Process CLI utility commands (save/snapshot/list/help)
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 {
        #[cfg(windows)]
        unsafe {
            #[link(name = "kernel32")]
            extern "system" {
                fn AttachConsole(dw_process_id: u32) -> i32;
            }
            AttachConsole(0xFFFFFFFF);
        }

        let cmd = args[1].to_lowercase();
        if cmd == "save" || cmd == "snapshot" || cmd == "--save" || cmd == "--snapshot" {
            let name = args.get(2).map(|s| s.as_str()).unwrap_or("google_4");
            let alias = args.get(3).map(|s| s.as_str());
            match router::save_current_profile(name, alias) {
                Ok(_) => {
                    println!("[OK] Successfully captured active Google account as profile '{}' (alias: {:?})", name, alias);
                    return Ok(());
                }
                Err(e) => {
                    eprintln!("[ERROR] Failed to save profile '{}': {}", name, e);
                    return Err(e);
                }
            }
        } else if cmd == "list" || cmd == "--list" {
            let profiles = router::list_profiles();
            println!("Discovered {} saved profile(s):", profiles.len());
            for p in profiles {
                let status = if p.is_live { "ACTIVE" } else { "standby" };
                println!("  - [{}] {} ({}) [{}]", p.name, p.alias, p.email, status);
            }
            return Ok(());
        } else if cmd == "help" || cmd == "--help" || cmd == "-h" {
            println!("Antigravity Switchboard v2.0.0");
            println!("Usage:");
            println!("  antigravity-switchboard.exe                   # Launch native desktop GUI");
            println!("  antigravity-switchboard.exe list              # List all discovered profiles");
            println!("  antigravity-switchboard.exe save <name> [alias] # Snapshot active account into a profile slot");
            return Ok(());
        }
    }

    // 1. Initialize logger
    if std::env::var("RUST_LOG").is_err() {
        std::env::set_var("RUST_LOG", "info");
    }
    env_logger::init();
    info!("Starting Antigravity Switchboard v2.0.0 (Native Slint Desktop)");

    // 2. Ensure single-instance execution
    let _single_instance = match hotkey::acquire_single_instance("Global\\AntigravitySwitchboardV2_SingleInstance") {
        Some(guard) => guard,
        None => {
            info!("Existing Antigravity Switchboard instance is already running. Restoring and focusing window.");
            hotkey::focus_existing_window("Antigravity Switchboard");
            return Ok(());
        }
    };

    // 3. Instantiate main AppWindow
    let app = AppWindow::new()?;

    // 4. Intercept window close requests on [X] to minimize cleanly to system tray
    app.window().on_close_requested(move || {
        info!("Window close requested — hiding to system tray");
        slint::CloseRequestResponse::HideWindow
    });

    // 5. Query router and process modules, populating accounts and HeroBar immediately
    info!("Performing startup profile discovery and process supervision checks...");
    refresh_ui_state(&app, None);
    app.set_app_status("Switchboard Operational".into());

    // 6. Trigger initial asynchronous live quota synchronization across all providers
    trigger_full_refresh(app.as_weak(), None);

    // 7. Setup 10-minute auto-refresh timer loop using Slint Timer
    let app_weak_timer = app.as_weak();
    let refresh_timer = slint::Timer::default();
    refresh_timer.start(
        slint::TimerMode::Repeated,
        Duration::from_secs(600),
        move || {
            info!("Timer Event: 10-minute auto-refresh triggered");
            trigger_full_refresh(app_weak_timer.clone(), None);
        },
    );

    // 8. Setup global hotkey listener (Ctrl+Alt+S) to toggle window visibility
    let app_weak_hotkey = app.as_weak();
    let _hotkey_handle = match hotkey::start_hotkey_listener(move || {
        info!("Global hotkey Ctrl+Alt+S pressed — toggling Switchboard window");
        let app_weak = app_weak_hotkey.clone();
        let _ = slint::invoke_from_event_loop(move || {
            if let Some(app) = app_weak.upgrade() {
                if app.window().is_visible() {
                    let _ = app.hide();
                } else {
                    let _ = app.show();
                    hotkey::focus_existing_window("Antigravity Switchboard");
                }
            }
        });
    }) {
        Ok(h) => Some(h),
        Err(e) => {
            warn!("Failed to register global hotkey (Ctrl+Alt+S): {}", e);
            None
        }
    };

    // 9. Setup system tray icon with context menu and click-to-toggle
    let app_weak_tray = app.as_weak();
    let _tray_handle = match tray::start_tray("Antigravity Switchboard", move |event| {
        info!("System tray event received: {:?}", event);
        let app_weak = app_weak_tray.clone();
        match event {
            tray::TrayEvent::ToggleWindow => {
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(app) = app_weak.upgrade() {
                        if app.window().is_visible() {
                            let _ = app.hide();
                        } else {
                            let _ = app.show();
                            hotkey::focus_existing_window("Antigravity Switchboard");
                        }
                    }
                });
            }
            tray::TrayEvent::ShowWindow => {
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(app) = app_weak.upgrade() {
                        let _ = app.show();
                        hotkey::focus_existing_window("Antigravity Switchboard");
                    }
                });
            }
            tray::TrayEvent::HideWindow => {
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(app) = app_weak.upgrade() {
                        let _ = app.hide();
                    }
                });
            }
            tray::TrayEvent::RefreshQuotas => {
                trigger_full_refresh(app_weak, None);
            }
            tray::TrayEvent::Exit => {
                let _ = slint::invoke_from_event_loop(|| {
                    let _ = slint::quit_event_loop();
                });
            }
        }
    }) {
        Ok(h) => Some(h),
        Err(e) => {
            warn!("Failed to initialize system tray icon: {}", e);
            None
        }
    };

    // 6. Wire UI callbacks with router and process supervision
    let app_weak = app.as_weak();
    app.on_refresh_clicked(move || {
        info!("UI Event: refresh_clicked triggered — full multi-provider synchronization");
        trigger_full_refresh(app_weak.clone(), None);
    });

    let app_weak = app.as_weak();
    app.on_relaunch_client_clicked(move || {
        info!("UI Event: relaunch_client_clicked triggered — restarting Antigravity Client language server");
        match process::restart_language_server() {
            Ok(count) => {
                info!("Restarted {} language_server.exe instance(s)", count);
            }
            Err(e) => {
                warn!("Error restarting language server: {}", e);
            }
        }
        if let Some(app) = app_weak.upgrade() {
            refresh_ui_state(&app, None);
            app.set_app_status("Antigravity Client language server restarted".into());
        }
    });

    let app_weak = app.as_weak();
    app.on_switch_account(move |id: SharedString| {
        info!("UI Event: switch_account triggered for id: {}", id);
        let id_str = id.to_string();

        // 1. Call router::switch_google_profile(&id)
        match router::switch_google_profile(&id_str) {
            Ok(true) => {
                info!("Successfully switched to profile '{}'", id_str);
            }
            Ok(false) => {
                warn!("Profile '{}' switch returned false", id_str);
            }
            Err(e) => {
                error!("Error switching to profile '{}': {}", id_str, e);
            }
        }

        // 2. Call process::restart_language_server()
        match process::restart_language_server() {
            Ok(count) => {
                info!("Restarted {} language_server.exe process(es)", count);
            }
            Err(e) => {
                warn!("Error restarting language server: {}", e);
            }
        }

        // 3. Trigger immediate full refresh so new live account and its quota are updated
        trigger_full_refresh(app_weak.clone(), Some(id_str));
    });

    let app_weak = app.as_weak();
    app.on_select_account(move |id: SharedString| {
        info!("UI Event: select_account clicked for id: {}", id);
        if let Some(app) = app_weak.upgrade() {
            let accounts_model = app.get_accounts();
            let mut updated = Vec::new();
            for i in 0..accounts_model.row_count() {
                if let Some(mut acc) = accounts_model.row_data(i) {
                    acc.is_selected = acc.id == id;
                    updated.push(acc);
                }
            }
            app.set_accounts(Rc::new(VecModel::from(updated)).into());
        }
    });

    let app_weak = app.as_weak();
    app.on_claude_action_clicked(move || {
        info!("UI Event: claude_action_clicked (sync Claude quotas)");
        trigger_full_refresh(app_weak.clone(), None);
    });

    let app_weak = app.as_weak();
    app.on_deepseek_action_clicked(move || {
        info!("UI Event: deepseek_action_clicked (manage credit / balance check)");
        trigger_full_refresh(app_weak.clone(), None);
    });

    // 7. Run main Slint event loop
    info!("Running main Slint event loop...");
    app.run()?;

    info!("Antigravity Switchboard exited cleanly.");
    Ok(())
}
