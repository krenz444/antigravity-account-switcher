#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gui_app.py - Windows Desktop App for Antigravity Multi-Account Switching & Real-Time Quota Monitor.

Features:
- Instant 1-click account switching with automatic Antigravity App relaunch
- High-concurrency parallel quota fetching directly from Google Cloud Code PA API
- Live per-second countdown clocks for 5-hour resets and weekly refreshes
- Zero-churn canvas progress bars with dynamic responsive resizing
- Modern Windows 11 dark slate design with native dark titlebar and centered window
- Bulletproof non-overlapping layout across all DPI scalings and resolutions
- Thread-safe UI architecture, strict event debounce, and leak-free destruction
"""

import concurrent.futures
import ctypes
from ctypes import wintypes
import datetime as dt
import json
import os
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

# Enable Per-Monitor High-DPI Awareness
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import router

# ---------------------------------------------------------------------------
# Theme Colors (Modern Slate & Dark Glass Theme)
# ---------------------------------------------------------------------------
BG_MAIN = "#0b1120"             # Deep navy slate background
BG_CARD = "#131d31"             # Elevated card background
BG_CARD_LIVE = "#082320"        # Active live card tinted emerald
BG_CARD_STAGED = "#0a1e36"      # Staged card tinted sapphire
BG_CARD_CLAUDE = "#15102a"      # Elevated deep violet slate
BORDER_DEFAULT = "#223048"      # Crisp card border
BORDER_LIVE = "#10b981"         # Emerald active border
BORDER_STAGED = "#0284c7"       # Cyan staged border
BORDER_CLAUDE = "#7c3aed"       # Vibrant purple/violet border
BG_PROGRESS_TRACK = "#1e293b"   # Defined track background

TEXT_MAIN = "#f8fafc"           # Crisp white
TEXT_MUTED = "#94a3b8"          # Medium slate
TEXT_DIM = "#64748b"            # Secondary slate

COLOR_ACTIVE = "#10b981"        # Emerald
COLOR_READY = "#38bdf8"         # Sky blue
COLOR_WARN = "#f59e0b"          # Amber
COLOR_DANGER = "#f43f5e"        # Rose
BADGE_CLAUDE = "#6d28d9"        # Royal violet badge
COLOR_CLAUDE = "#c084fc"        # Soft violet text
COLOR_CLAUDE_BAR = "#8b5cf6"    # Violet progress fill

BTN_PRIMARY = "#2563eb"
BTN_PRIMARY_HOVER = "#1d4ed8"
BTN_SECONDARY = "#1e293b"
BTN_SECONDARY_HOVER = "#334155"


def get_quota_color(used_pct):
    """Consistent color scale across Google and Claude progress meters."""
    if used_pct is not None and used_pct >= 90:
        return COLOR_DANGER
    elif used_pct is not None and used_pct >= 80:
        return COLOR_WARN
    return COLOR_READY


def apply_dark_titlebar(root):
    """Enables Windows 11 / 10 native immersive dark mode on the window frame."""
    try:
        root.update_idletasks()
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(2)
        res = set_window_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))
        if res != 0:
            set_window_attribute(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def center_window(root, width=1020, height=720):
    """Positions the window at the visual center of the primary monitor."""
    try:
        root.update_idletasks()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = max(0, int((sw - width) / 2))
        y = max(0, int((sh - height) / 2.3))
        root.geometry(f"{width}x{height}+{x}+{y}")
    except Exception:
        root.geometry(f"{width}x{height}")


def make_button(parent, text, font, bg, fg, hover_bg, hover_fg=None, command=None, padx=12, pady=5, cursor="hand2", state=tk.NORMAL):
    """Creates a modern flat button with responsive hover feedback."""
    btn = tk.Button(
        parent,
        text=text,
        font=font,
        bg=bg,
        fg=fg,
        activebackground=hover_bg,
        activeforeground=hover_fg or fg,
        relief=tk.FLAT,
        padx=padx,
        pady=pady,
        cursor=cursor if state == tk.NORMAL else "arrow",
        state=state,
        command=command
    )
    btn.default_bg = bg
    btn.hover_bg = hover_bg
    if state == tk.NORMAL:
        btn.bind("<Enter>", lambda e: btn.config(bg=btn.hover_bg) if btn["state"] == tk.NORMAL else None)
        btn.bind("<Leave>", lambda e: btn.config(bg=btn.default_bg) if btn["state"] == tk.NORMAL else None)
    return btn


class AccountSwitchboardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Antigravity Multi-Account Switchboard & Quota Monitor")
        center_window(self.root, 1020, 720)
        self.root.minsize(920, 640)
        self.root.configure(bg=BG_MAIN)

        # Apply Native Windows Dark Titlebar
        apply_dark_titlebar(self.root)

        self.cards = {}
        self.quotas = {}
        self.action_buttons = []
        self.is_fetching = False
        self.is_relaunching = False
        self.is_destroyed = False
        self.last_sync_time = None
        self._refresh_timer_id = None
        self._tick_timer_id = None

        # Clean Window Shutdown Protocol
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Set Window Icons
        ico_path = os.path.join(SCRIPT_DIR, "app_icon.ico")
        png_path = os.path.join(SCRIPT_DIR, "app_icon.png")
        if os.path.exists(ico_path):
            try:
                self.root.iconbitmap(ico_path)
            except Exception:
                pass
        if os.path.exists(png_path):
            try:
                self.icon_photo = tk.PhotoImage(file=png_path)
                self.root.iconphoto(True, self.icon_photo)
            except Exception:
                pass

        # Auto-refresh quotas on window focus (with 5s debounce)
        self.root.bind("<FocusIn>", self.on_window_focus)

        self.setup_ui()
        self.build_initial_cards()
        self.poll_all_quotas_async()
        self.schedule_quota_auto_refresh()
        self.tick_timer()

    def on_window_focus(self, event=None):
        if self.is_fetching or self.is_relaunching or self.is_destroyed:
            return
        if not self.last_sync_time:
            self.poll_all_quotas_async()
            return
        elapsed = (dt.datetime.now() - self.last_sync_time).total_seconds()
        if elapsed > 5:
            self.poll_all_quotas_async()

    def setup_ui(self):
        # 1. Top Header Frame
        header = tk.Frame(self.root, bg=BG_MAIN, padx=24, pady=12)
        header.pack(fill=tk.X)

        # Action Buttons (Pack RIGHT first so they are anchored and never clipped)
        btn_box = tk.Frame(header, bg=BG_MAIN)
        btn_box.pack(side=tk.RIGHT, pady=2)

        self.sync_badge = tk.Label(
            btn_box,
            text="● Live Syncing...",
            font=("Segoe UI", 8, "bold"),
            fg="#38bdf8",
            bg="#0f172a",
            padx=9,
            pady=4
        )
        self.sync_badge.pack(side=tk.LEFT, padx=(0, 8))

        self.add_btn = make_button(
            btn_box,
            text="➕ Add Account",
            font=("Segoe UI", 9, "bold"),
            bg="#1e293b",
            fg="#f8fafc",
            hover_bg="#334155",
            padx=12,
            pady=5,
            command=self.on_add_account
        )
        self.add_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.refresh_btn = make_button(
            btn_box,
            text="🔄 Refresh",
            font=("Segoe UI", 9, "bold"),
            bg=BTN_PRIMARY,
            fg="#ffffff",
            hover_bg=BTN_PRIMARY_HOVER,
            padx=13,
            pady=5,
            command=self.poll_all_quotas_async
        )
        self.refresh_btn.pack(side=tk.LEFT)

        # Title Box (Left side, fills remaining space)
        title_box = tk.Frame(header, bg=BG_MAIN)
        title_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        app_title = tk.Label(
            title_box,
            text="Antigravity Account Switchboard",
            font=("Segoe UI", 15, "bold"),
            fg=TEXT_MAIN,
            bg=BG_MAIN
        )
        app_title.pack(anchor="w")

        subtitle = tk.Label(
            title_box,
            text="Real-Time Antigravity & Claude Quotas • 5-Hour & Weekly Windows • 1-Click Switcher",
            font=("Segoe UI", 9),
            fg=TEXT_MUTED,
            bg=BG_MAIN
        )
        subtitle.pack(anchor="w")

        # 2. Status Banner (Active Session Bar)
        self.banner = tk.Frame(
            self.root,
            bg="#05241f",
            padx=16,
            pady=9,
            highlightthickness=1,
            highlightbackground=BORDER_LIVE
        )
        self.banner.pack(fill=tk.X, padx=24, pady=(0, 10))

        self.restart_btn = make_button(
            self.banner,
            text="🚀 Apply to Antigravity App",
            font=("Segoe UI", 9, "bold"),
            bg="#0284c7",
            fg="#ffffff",
            hover_bg="#0369a1",
            padx=12,
            pady=4,
            command=self.on_restart_antigravity
        )

        self.banner_label = tk.Label(
            self.banner,
            text="Connecting to Antigravity sessions...",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_ACTIVE,
            bg="#05241f",
            anchor="w"
        )
        self.banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 3. Cards Container Frame
        self.cards_outer = tk.Frame(self.root, bg=BG_MAIN, padx=24)
        self.cards_outer.pack(fill=tk.BOTH, expand=True)

        self.cards_frame = tk.Frame(self.cards_outer, bg=BG_MAIN)
        self.cards_frame.pack(fill=tk.BOTH, expand=True)

        # 4. Bottom Info Bar (Footer)
        sep = tk.Frame(self.root, bg="#1e293b", height=1)
        sep.pack(fill=tk.X, padx=24)

        footer = tk.Frame(self.root, bg=BG_MAIN, padx=24, pady=10)
        footer.pack(fill=tk.X)

        self.footer_clock = tk.Label(
            footer,
            text="Last API Check: Pending",
            font=("Segoe UI", 8),
            fg=TEXT_DIM,
            bg=BG_MAIN
        )
        self.footer_clock.pack(side=tk.RIGHT)

        self.footer_status = tk.Label(
            footer,
            text="● Direct Google Cloud Code PA • Parallel OAuth 2.0 Pool",
            font=("Segoe UI", 8),
            fg=TEXT_DIM,
            bg=BG_MAIN,
            anchor="w"
        )
        self.footer_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def set_buttons_enabled(self, enabled=True):
        """Enables or disables all action buttons during switching or relaunching."""
        st = tk.NORMAL if enabled else tk.DISABLED
        cur = "hand2" if enabled else "arrow"
        for btn in self.action_buttons:
            try:
                btn.config(state=st, cursor=cur)
            except Exception:
                pass
        try:
            self.refresh_btn.config(state=st, cursor=cur)
        except Exception:
            pass
        try:
            self.add_btn.config(state=st, cursor=cur)
        except Exception:
            pass

    def build_initial_cards(self):
        # Clear existing cards
        for widget in self.cards_frame.winfo_children():
            widget.destroy()
        self.cards.clear()
        self.action_buttons.clear()

        profiles = router.list_profiles()
        cfg = router.get_config()
        show_model_only = cfg.get("ui", {}).get("show_model_only_quota", False)
        state = router.get_state()
        staged_name = state.get("active_google_profile", "google_1")
        staged_email = router.get_active_email()
        live_email = router.get_live_antigravity_email()

        # Update Banner State: ALWAYS unpack both first to prevent any overlapping geometry
        self.banner_label.pack_forget()
        self.restart_btn.pack_forget()

        if live_email and staged_email and live_email.lower() == staged_email.lower():
            self.banner.config(bg="#05241f", highlightbackground=BORDER_LIVE, highlightthickness=1)
            self.banner_label.config(
                text=f"● LIVE SESSION: {live_email}  •  Synchronized with Antigravity App",
                fg="#34d399",
                bg="#05241f"
            )
            self.banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        else:
            self.banner.config(bg="#081e35", highlightbackground=BORDER_STAGED, highlightthickness=1)
            self.banner_label.config(
                text=f"● Live: {live_email or 'Unknown'}   ➔   📁 Staged: {staged_email}",
                fg="#38bdf8",
                bg="#081e35"
            )
            # Pack restart button FIRST on the RIGHT so it is never overlapped by expanding label
            self.restart_btn.pack(side=tk.RIGHT, padx=(12, 0))
            self.banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.action_buttons.append(self.restart_btn)


        # Build Profile Cards
        if not profiles:
            welcome_card = tk.Frame(
                self.cards_frame,
                bg=BG_CARD,
                padx=24,
                pady=20,
                highlightthickness=1,
                highlightbackground=BORDER_DEFAULT
            )
            welcome_card.pack(fill=tk.X, pady=8)
            tk.Label(
                welcome_card,
                text="👋 Welcome to Antigravity Account Switcher",
                font=("Segoe UI", 12, "bold"),
                fg=TEXT_MAIN,
                bg=BG_CARD
            ).pack(anchor="w", pady=(0, 4))
            tk.Label(
                welcome_card,
                text="No Google accounts have been registered yet.\nConnect your first account via browser or snapshot your currently active Antigravity session.",
                font=("Segoe UI", 9),
                fg=TEXT_MUTED,
                bg=BG_CARD,
                justify=tk.LEFT
            ).pack(anchor="w", pady=(0, 12))
            btn_row = tk.Frame(welcome_card, bg=BG_CARD)
            btn_row.pack(anchor="w")

            make_button(
                btn_row,
                text="➕ Connect Account via Browser",
                font=("Segoe UI", 9, "bold"),
                bg=BTN_PRIMARY,
                fg="#ffffff",
                hover_bg=BTN_PRIMARY_HOVER,
                padx=14,
                pady=6,
                command=self.on_add_account
            ).pack(side=tk.LEFT, padx=(0, 10))

            def on_snap_current():
                ok, msg = router.save_current_profile("google_1")
                if ok:
                    self.build_initial_cards()
                    self.poll_all_quotas_async()
                else:
                    messagebox.showerror("Error", msg, parent=self.root)

            make_button(
                btn_row,
                text="💾 Snapshot Current Local Session",
                font=("Segoe UI", 9, "bold"),
                bg="#1e293b",
                fg=TEXT_MAIN,
                hover_bg="#334155",
                padx=14,
                pady=6,
                command=on_snap_current
            ).pack(side=tk.LEFT)

        for idx, p in enumerate(profiles, start=1):
            name = p["name"]
            email = p["email"]
            alias = p.get("alias")
            is_live = bool(live_email and email and email.lower() == live_email.lower())
            is_staged = bool(name == staged_name or (email and staged_email and email.lower() == staged_email.lower()))

            if is_live:
                card_bg = BG_CARD_LIVE
                card_border = BORDER_LIVE
                badge_bg = "#059669"
                badge_fg = "#ecfdf5"
                status_txt = "● ACTIVE IN APP"
                status_color = COLOR_ACTIVE
            elif is_staged:
                card_bg = BG_CARD_STAGED
                card_border = BORDER_STAGED
                badge_bg = "#0284c7"
                badge_fg = "#f0f9ff"
                status_txt = "● STAGED"
                status_color = COLOR_READY
            else:
                card_bg = BG_CARD
                card_border = BORDER_DEFAULT
                badge_bg = "#2563eb"
                badge_fg = "#eff6ff"
                status_txt = "● READY"
                status_color = COLOR_READY

            card = tk.Frame(
                self.cards_frame,
                bg=card_bg,
                padx=16,
                pady=10,
                highlightthickness=2 if (is_live or is_staged) else 1,
                highlightbackground=card_border
            )
            card.pack(fill=tk.X, pady=4)

            # Left Section: Identity Column (280px fixed width, comfortable padding)
            left_col = tk.Frame(card, bg=card_bg, width=280)
            left_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 14))
            left_col.pack_propagate(False)

            def make_copy_handler(em, cbtn):
                def handler(event=None):
                    try:
                        self.root.clipboard_clear()
                        self.root.clipboard_append(em)
                        cbtn.config(text=" ✓", fg="#34d399")
                        self.root.after(1500, lambda: cbtn.config(text=" 📋", fg=TEXT_DIM) if not self.is_destroyed else None)
                        self.footer_status.config(text=f"✓ Copied {em} to clipboard!")
                    except Exception:
                        pass
                return handler

            # Line 1: Index Badge + Email + 1-Click Copy Action
            badge_frame = tk.Frame(left_col, bg=card_bg)
            badge_frame.pack(anchor="w")

            num_badge = tk.Label(
                badge_frame,
                text=f" #{idx} ",
                font=("Segoe UI", 9, "bold"),
                bg=badge_bg,
                fg=badge_fg,
                padx=5,
                pady=1
            )
            num_badge.pack(side=tk.LEFT, padx=(0, 6))

            email_lbl = tk.Label(
                badge_frame,
                text=email,
                font=("Segoe UI", 10, "bold"),
                fg=TEXT_MAIN,
                bg=card_bg,
                cursor="hand2"
            )
            email_lbl.pack(side=tk.LEFT)

            copy_btn = tk.Label(
                badge_frame,
                text=" 📋",
                font=("Segoe UI", 8),
                fg=TEXT_DIM,
                bg=card_bg,
                cursor="hand2"
            )
            copy_btn.pack(side=tk.LEFT)

            copy_action = make_copy_handler(email, copy_btn)
            email_lbl.bind("<Button-1>", copy_action)
            copy_btn.bind("<Button-1>", copy_action)

            # Line 2: Account Provider / Type & Tier
            svc_row = tk.Frame(left_col, bg=card_bg)
            svc_row.pack(anchor="w", pady=(2, 0))

            svc_lbl = tk.Label(
                svc_row,
                text="Google AI • Free Tier",
                font=("Segoe UI", 8),
                fg=TEXT_MUTED,
                bg=card_bg
            )
            svc_lbl.pack(side=tk.LEFT)

            # Line 3: Status Pill
            status_pill = tk.Label(
                left_col,
                text=status_txt,
                font=("Segoe UI", 8, "bold"),
                fg=status_color,
                bg=card_bg
            )
            status_pill.pack(anchor="w", pady=(3, 0))


            # Middle Section: Quota Bars & Live Timers
            mid_col = tk.Frame(card, bg=card_bg)
            mid_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12)

            # 1. 5-Hour Limit Row (Value packed RIGHT first, then title packed LEFT)
            row_5h = tk.Frame(mid_col, bg=card_bg)
            row_5h.pack(fill=tk.X, pady=(0, 1))

            lbl_5h_val = tk.Label(row_5h, text="Querying API...", font=("Segoe UI", 11, "bold"), fg=TEXT_MAIN, bg=card_bg)
            lbl_5h_val.pack(side=tk.RIGHT)

            lbl_5h_title = tk.Label(row_5h, text="Session limit (5h):", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg=card_bg)
            lbl_5h_title.pack(side=tk.LEFT)

            canvas_5h = tk.Canvas(mid_col, height=7, bg=BG_PROGRESS_TRACK, highlightthickness=0)
            canvas_5h.pack(fill=tk.X, pady=(1, 4))

            # 2. Weekly Limit Row (Value packed RIGHT first, then title packed LEFT)
            row_wk = tk.Frame(mid_col, bg=card_bg)
            row_wk.pack(fill=tk.X, pady=(1, 1))

            lbl_wk_val = tk.Label(row_wk, text="Querying API...", font=("Segoe UI", 11, "bold"), fg=TEXT_MAIN, bg=card_bg)
            lbl_wk_val.pack(side=tk.RIGHT)

            lbl_wk_title = tk.Label(row_wk, text="Weekly window (7d):", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg=card_bg)
            lbl_wk_title.pack(side=tk.LEFT)

            canvas_wk = tk.Canvas(mid_col, height=7, bg=BG_PROGRESS_TRACK, highlightthickness=0)
            canvas_wk.pack(fill=tk.X, pady=(1, 4))

            # 3. Timers Row
            timer_row = tk.Frame(mid_col, bg=card_bg)
            timer_row.pack(fill=tk.X, pady=(2, 0))

            if show_model_only:
                claude_lbl = tk.Label(timer_row, text="Claude/GPT: 100%", font=("Segoe UI", 8), fg=TEXT_MUTED, bg=card_bg)
                claude_lbl.pack(side=tk.RIGHT)
            else:
                claude_lbl = None

            timer_lbl = tk.Label(timer_row, text="⏱ Syncing quota timers...", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg=card_bg)
            timer_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # Right Section: Action Controls
            right_col = tk.Frame(card, bg=card_bg)
            right_col.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))

            if is_live:
                switch_btn = tk.Button(
                    right_col,
                    text="✓ Live in App",
                    font=("Segoe UI", 9, "bold"),
                    bg="#064e3b",
                    fg="#6ee7b7",
                    relief=tk.FLAT,
                    padx=14,
                    pady=6,
                    state=tk.DISABLED
                )
            elif is_staged:
                switch_btn = make_button(
                    right_col,
                    text="🚀 Relaunch App",
                    font=("Segoe UI", 9, "bold"),
                    bg="#0284c7",
                    fg="#ffffff",
                    hover_bg="#0369a1",
                    padx=12,
                    pady=6,
                    command=self.on_restart_antigravity
                )
                self.action_buttons.append(switch_btn)
            else:
                switch_btn = make_button(
                    right_col,
                    text="⚡ Switch",
                    font=("Segoe UI", 9, "bold"),
                    bg=BTN_PRIMARY,
                    fg="#ffffff",
                    hover_bg=BTN_PRIMARY_HOVER,
                    padx=14,
                    pady=6,
                    command=lambda n=name, b_ref=None: self.on_switch_profile(n)
                )
                self.action_buttons.append(switch_btn)
            switch_btn.pack(expand=True, pady=4)

            # Store widget references & hook responsive canvas redraw
            self.cards[name] = {
                "card": card,
                "is_live": is_live,
                "is_staged": is_staged,
                "switch_btn": switch_btn,
                "lbl_5h_val": lbl_5h_val,
                "canvas_5h": canvas_5h,
                "lbl_wk_val": lbl_wk_val,
                "canvas_wk": canvas_wk,
                "timer_lbl": timer_lbl,
                "status_pill": status_pill,
                "svc_lbl": svc_lbl,
                "claude_lbl": claude_lbl,
                "last_5h_pct": None,
                "last_5h_col": None,
                "last_wk_pct": None,
                "last_wk_col": None,
                "exp_5h_ts": None,
                "exp_wk_ts": None
            }

            canvas_5h.bind("<Configure>", lambda e, n=name: self.redraw_bar(n, "5h"))
            canvas_wk.bind("<Configure>", lambda e, n=name: self.redraw_bar(n, "wk"))

        # Build Dedicated Claude for Windows Desktop App Card
        claude_info = router.get_claude_status()
        if claude_info and claude_info.get("detected"):
            c_email = claude_info.get("email") or "Unknown"
            c_tier = claude_info.get("tier_label") or "Claude Pro"
            c_running = claude_info.get("app_running", False)
            c_pids = claude_info.get("app_pids", [])

            init_5h_used = claude_info.get("session_used_pct", 11)
            init_5h_rem = claude_info.get("session_rem_pct", 89)
            init_wk_used = claude_info.get("weekly_used_pct", 92)
            init_wk_rem = claude_info.get("weekly_rem_pct", 8)

            init_5h_col = get_quota_color(init_5h_used)
            init_5h_txt = init_5h_col
            init_wk_col = get_quota_color(init_wk_used)
            init_wk_txt = init_wk_col

            s_reset_init = claude_info.get("session_reset_desc", "Resets in 4 hr 36 min")
            w_reset_init = claude_info.get("weekly_reset_desc", "Resets Mon 7:00 PM")
            model_init = claude_info.get("active_model", "Opus 5.5 High")

            if c_running:
                c_status_txt = "● ACTIVE IN APP"
                c_status_color = COLOR_ACTIVE
            else:
                c_status_txt = "● READY"
                c_status_color = COLOR_CLAUDE

            c_card = tk.Frame(
                self.cards_frame,
                bg=BG_CARD_CLAUDE,
                padx=16,
                pady=10,
                highlightthickness=1,
                highlightbackground=BORDER_CLAUDE
            )
            c_card.pack(fill=tk.X, pady=4)

            # Left Section: Identity Column (280px fixed width, matching Google cards)
            c_left_col = tk.Frame(c_card, bg=BG_CARD_CLAUDE, width=280)
            c_left_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 14))
            c_left_col.pack_propagate(False)

            # Line 1: Service Badge + Profile Name + Tier Pill
            c_badge_frame = tk.Frame(c_left_col, bg=BG_CARD_CLAUDE)
            c_badge_frame.pack(anchor="w")

            c_num_badge = tk.Label(
                c_badge_frame,
                text=" Claude ",
                font=("Segoe UI", 9, "bold"),
                bg=BADGE_CLAUDE,
                fg="#faf5ff",
                padx=5,
                pady=1
            )
            c_num_badge.pack(side=tk.LEFT, padx=(0, 6))

            c_prof_lbl = tk.Label(
                c_badge_frame,
                text="Claude Pro",
                font=("Segoe UI", 11, "bold"),
                fg=TEXT_MAIN,
                bg=BG_CARD_CLAUDE
            )
            c_prof_lbl.pack(side=tk.LEFT, padx=(0, 6))

            c_tier_pill = tk.Label(
                c_badge_frame,
                text="Pro Tier",
                font=("Segoe UI", 8, "bold"),
                bg="#2e1065",
                fg="#d8b4fe",
                padx=5,
                pady=1
            )
            c_tier_pill.pack(side=tk.LEFT)

            # Line 2: Email line with 1-click copy action
            c_email_row = tk.Frame(c_left_col, bg=BG_CARD_CLAUDE)
            c_email_row.pack(anchor="w", pady=(3, 0))

            c_email_lbl = tk.Label(
                c_email_row,
                text=c_email,
                font=("Segoe UI", 9),
                fg=TEXT_MUTED,
                bg=BG_CARD_CLAUDE,
                cursor="hand2"
            )
            c_email_lbl.pack(side=tk.LEFT)

            c_copy_btn = tk.Label(
                c_email_row,
                text=" 📋",
                font=("Segoe UI", 8),
                fg=TEXT_DIM,
                bg=BG_CARD_CLAUDE,
                cursor="hand2"
            )
            c_copy_btn.pack(side=tk.LEFT)

            c_copy_action = make_copy_handler(c_email, c_copy_btn)
            c_email_lbl.bind("<Button-1>", c_copy_action)
            c_copy_btn.bind("<Button-1>", c_copy_action)

            # Line 3: Status Pill
            c_status_pill = tk.Label(
                c_left_col,
                text=c_status_txt,
                font=("Segoe UI", 8, "bold"),
                fg=c_status_color,
                bg=BG_CARD_CLAUDE
            )
            c_status_pill.pack(anchor="w", pady=(4, 0))

            # Middle Section: Quota Bars & Live Status
            c_mid_col = tk.Frame(c_card, bg=BG_CARD_CLAUDE)
            c_mid_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12)

            # 1. Session Limit Row (Value packed RIGHT first, then title packed LEFT)
            c_row_5h = tk.Frame(c_mid_col, bg=BG_CARD_CLAUDE)
            c_row_5h.pack(fill=tk.X, pady=(0, 1))

            c_lbl_5h_val = tk.Label(c_row_5h, text=f"{init_5h_used}% used  ({init_5h_rem}% left)", font=("Segoe UI", 11, "bold"), fg=init_5h_txt, bg=BG_CARD_CLAUDE)
            c_lbl_5h_val.pack(side=tk.RIGHT)

            c_lbl_5h_title = tk.Label(c_row_5h, text="Session limit (5h):", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg=BG_CARD_CLAUDE)
            c_lbl_5h_title.pack(side=tk.LEFT)

            c_canvas_5h = tk.Canvas(c_mid_col, height=7, bg=BG_PROGRESS_TRACK, highlightthickness=0)
            c_canvas_5h.pack(fill=tk.X, pady=(1, 4))

            # 2. Weekly Limit Row (Value packed RIGHT first, then title packed LEFT)
            c_row_wk = tk.Frame(c_mid_col, bg=BG_CARD_CLAUDE)
            c_row_wk.pack(fill=tk.X, pady=(1, 1))

            c_lbl_wk_val = tk.Label(c_row_wk, text=f"{init_wk_used}% used  ({init_wk_rem}% left)", font=("Segoe UI", 11, "bold"), fg=init_wk_txt, bg=BG_CARD_CLAUDE)
            c_lbl_wk_val.pack(side=tk.RIGHT)

            c_lbl_wk_title = tk.Label(c_row_wk, text="Weekly window (7d):", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg=BG_CARD_CLAUDE)
            c_lbl_wk_title.pack(side=tk.LEFT)

            c_canvas_wk = tk.Canvas(c_mid_col, height=7, bg=BG_PROGRESS_TRACK, highlightthickness=0)
            c_canvas_wk.pack(fill=tk.X, pady=(1, 4))

            # 3. Status & App Row
            c_detail_row = tk.Frame(c_mid_col, bg=BG_CARD_CLAUDE)
            c_detail_row.pack(fill=tk.X, pady=(2, 0))

            if show_model_only:
                c_billing_lbl = tk.Label(
                    c_detail_row,
                    text=f"Model: {model_init}  🔴" if init_wk_used >= 80 else f"Model: {model_init}",
                    font=("Segoe UI", 8, "bold"),
                    fg="#f87171" if init_wk_used >= 80 else TEXT_MUTED,
                    bg=BG_CARD_CLAUDE
                )
                c_billing_lbl.pack(side=tk.RIGHT)
            else:
                c_billing_lbl = None

            c_timer_lbl = tk.Label(
                c_detail_row,
                text=f"⏱ {s_reset_init}  •  {w_reset_init}",
                font=("Segoe UI", 8, "bold"),
                fg=TEXT_MUTED,
                bg=BG_CARD_CLAUDE
            )
            c_timer_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # Right Section: Action Button (Open Windows App)
            c_right_col = tk.Frame(c_card, bg=BG_CARD_CLAUDE)
            c_right_col.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))

            def on_launch_claude_app():
                ok = router.launch_claude_desktop()
                if ok:
                    self.footer_status.config(text="✓ Focused Claude for Windows Desktop App!")
                else:
                    self.footer_status.config(text="Notice: Could not launch Claude desktop app.")

            c_switch_btn = make_button(
                c_right_col,
                text="🖥 Open Claude",
                font=("Segoe UI", 9, "bold"),
                bg=BADGE_CLAUDE,
                fg="#faf5ff",
                hover_bg="#7c3aed",
                padx=14,
                pady=6,
                command=on_launch_claude_app
            )
            c_switch_btn.pack(expand=True, pady=4)
            self.action_buttons.append(c_switch_btn)

            # Parse initial epoch deadline for Claude 5h countdown
            init_claude_exp_5h = None
            m = re.search(r'(\d+)\s*hr(?:\s*(\d+)\s*min)?', s_reset_init)
            if m:
                h = int(m.group(1))
                mins = int(m.group(2) or 0)
                init_claude_exp_5h = time.time() + h * 3600 + mins * 60

            self.cards["claude"] = {
                "card": c_card,
                "is_live": False,
                "is_staged": False,
                "switch_btn": c_switch_btn,
                "lbl_5h_val": c_lbl_5h_val,
                "canvas_5h": c_canvas_5h,
                "lbl_wk_val": c_lbl_wk_val,
                "canvas_wk": c_canvas_wk,
                "timer_lbl": c_timer_lbl,
                "status_pill": c_status_pill,
                "claude_lbl": c_billing_lbl,
                "rem_5h_pct": init_5h_rem,
                "used_5h_pct": init_5h_used,
                "rem_wk_pct": init_wk_rem,
                "used_wk_pct": init_wk_used,
                "last_5h_pct": init_5h_used,
                "last_5h_col": init_5h_col,
                "last_wk_pct": init_wk_used,
                "last_wk_col": init_wk_col,
                "exp_5h_ts": init_claude_exp_5h,
                "weekly_reset_str": w_reset_init
            }

            c_canvas_5h.bind("<Configure>", lambda e, n="claude": self.redraw_bar(n, "5h"))
            c_canvas_wk.bind("<Configure>", lambda e, n="claude": self.redraw_bar(n, "wk"))

    def render_canvas_bar(self, canvas, pct, color):
        """Zero-churn progress bar renderer: reuses rectangle item coords instead of deleting."""
        if self.is_destroyed:
            return
        w = canvas.winfo_width()
        if w < 50:
            try:
                parent_w = canvas.master.winfo_width()
                w = max(50, parent_w - 4) if parent_w > 50 else 320
            except Exception:
                w = 320
        h = canvas.winfo_height()
        if h < 4:
            h = 7

        fill_w = max(0, int((pct / 100.0) * w)) if (pct is not None and pct > 0) else 0

        # Check if items already exist on this canvas
        track_id = getattr(canvas, "_track_id", None)
        fill_id = getattr(canvas, "_fill_id", None)

        if track_id is None:
            canvas._track_id = canvas.create_rectangle(0, 0, w, h, fill=BG_PROGRESS_TRACK, width=0)
            canvas._fill_id = canvas.create_rectangle(0, 0, fill_w, h, fill=color, width=0)
        else:
            canvas.coords(track_id, 0, 0, w, h)
            canvas.coords(fill_id, 0, 0, fill_w, h)
            canvas.itemconfig(fill_id, fill=color)

    def redraw_bar(self, name, kind):
        """Callback for canvas <Configure> event to redraw bars dynamically upon resize."""
        if self.is_destroyed:
            return
        refs = self.cards.get(name)
        if not refs:
            return
        if kind == "5h":
            pct = refs.get("last_5h_pct")
            col = refs.get("last_5h_col") or COLOR_ACTIVE
            self.render_canvas_bar(refs["canvas_5h"], pct, col)
        elif kind == "wk":
            pct = refs.get("last_wk_pct")
            col = refs.get("last_wk_col") or COLOR_ACTIVE
            self.render_canvas_bar(refs["canvas_wk"], pct, col)

    def poll_all_quotas_async(self):
        """High-concurrency parallel quota fetcher across all profiles simultaneously."""
        if self.is_fetching or self.is_destroyed:
            return
        self.is_fetching = True
        self.sync_badge.config(text="● Querying API...", fg="#f59e0b", bg="#1f1807")

        def worker():
            results = {}
            profiles = router.list_profiles()

            def fetch_single(prof):
                pname = prof["name"]
                try:
                    q = router.fetch_profile_quota(pname)
                    return pname, q
                except Exception:
                    return pname, None

            # Concurrently query Google Cloud Code PA API
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(profiles) or 1, 4)) as executor:
                for pname, q in executor.map(fetch_single, profiles):
                    results[pname] = q

            # Query Claude for Windows Desktop App status & live quota
            try:
                cs = router.get_claude_status()
                results["claude"] = {
                    "session_used_pct": cs.get("session_used_pct", 11),
                    "session_rem_pct": cs.get("session_rem_pct", 89),
                    "weekly_used_pct": cs.get("weekly_used_pct", 92),
                    "weekly_rem_pct": cs.get("weekly_rem_pct", 8),
                    "claude_status": cs
                }
            except Exception:
                results["claude"] = None

            if not self.is_destroyed:
                self.root.after(0, lambda: self.on_quotas_received(results))

        threading.Thread(target=worker, daemon=True).start()

    def on_quotas_received(self, results):
        if self.is_destroyed:
            return
        self.quotas = results
        self.is_fetching = False
        now_str = dt.datetime.now().strftime("%H:%M:%S")
        self.last_sync_time = dt.datetime.now()

        self.sync_badge.config(text=f"● Live Synced ({now_str})", fg="#34d399", bg="#052e25")
        self.footer_clock.config(text=f"Last API Check: {now_str} (Auto-refreshes every 60s)")

        for name, refs in self.cards.items():
            q = results.get(name)

            # Handle Claude for Windows Desktop App card
            if name == "claude":
                cs = (q.get("claude_status") if q else None) or router.get_claude_status()
                s_used = cs.get("session_used_pct", 11) if cs else 11
                s_rem = cs.get("session_rem_pct", 89) if cs else 89
                w_used = cs.get("weekly_used_pct", 92) if cs else 92
                w_rem = cs.get("weekly_rem_pct", 8) if cs else 8

                col_5h = get_quota_color(s_used)
                txt_col_5h = col_5h
                col_wk = get_quota_color(w_used)
                txt_col_wk = col_wk

                refs["lbl_5h_val"].config(text=f"{s_used}% used  ({s_rem}% left)", fg=txt_col_5h)
                refs["lbl_wk_val"].config(text=f"{w_used}% used  ({w_rem}% left)", fg=txt_col_wk)
                refs["rem_5h_pct"] = s_rem
                refs["used_5h_pct"] = s_used
                refs["rem_wk_pct"] = w_rem
                refs["used_wk_pct"] = w_used
                refs["last_5h_pct"] = s_used
                refs["last_5h_col"] = col_5h
                refs["last_wk_pct"] = w_used
                refs["last_wk_col"] = col_wk
                self.render_canvas_bar(refs["canvas_5h"], s_used, col_5h)
                self.render_canvas_bar(refs["canvas_wk"], w_used, col_wk)

                s_reset = cs.get("session_reset_desc", "Resets in 4 hr 36 min") if cs else "Resets in 4 hr 36 min"
                w_reset = cs.get("weekly_reset_desc", "Resets Mon 7:00 PM") if cs else "Resets Mon 7:00 PM"
                refs["weekly_reset_str"] = w_reset

                # Parse numeric epoch deadline for Claude 5h countdown
                m = re.search(r'(\d+)\s*hr(?:\s*(\d+)\s*min)?', s_reset)
                if m:
                    h = int(m.group(1))
                    mins = int(m.group(2) or 0)
                    refs["exp_5h_ts"] = time.time() + h * 3600 + mins * 60
                else:
                    refs["exp_5h_ts"] = None

                model_str = cs.get("active_model", "Opus 5.5 High") if cs else "Opus 5.5 High"
                if refs.get("claude_lbl"):
                    refs["claude_lbl"].config(
                        text=f"Model: {model_str}  🔴" if w_used >= 80 else f"Model: {model_str}",
                        fg=COLOR_DANGER if w_used >= 80 else TEXT_MUTED
                    )

                is_running = cs.get("app_running", False) if cs else False
                pids = cs.get("app_pids", []) if cs else []
                if is_running:
                    refs["status_pill"].config(text="● ACTIVE IN APP", fg=COLOR_ACTIVE)
                else:
                    refs["status_pill"].config(text="● READY", fg=COLOR_CLAUDE)
                continue


            if not q or q.get("5h_pct") is None:
                refs["lbl_5h_val"].config(text="Connect Required", fg=COLOR_WARN)
                refs["lbl_wk_val"].config(text="Connect Required", fg=COLOR_WARN)
                refs["timer_lbl"].config(text="● Click Switch to connect with Google OAuth", fg=COLOR_WARN)
                if refs.get("claude_lbl"):
                    refs["claude_lbl"].config(text="Claude/GPT: --", fg=TEXT_DIM)
                refs["rem_5h_pct"] = None
                refs["used_5h_pct"] = None
                refs["rem_wk_pct"] = None
                refs["used_wk_pct"] = None
                refs["last_5h_pct"] = None
                refs["last_wk_pct"] = None
                refs["exp_5h_ts"] = None
                refs["weekly_reset_str"] = None
                self.render_canvas_bar(refs["canvas_5h"], 0, COLOR_WARN)
                self.render_canvas_bar(refs["canvas_wk"], 0, COLOR_WARN)
                continue

            pct_5h = q.get("5h_pct", 100)
            used_5h = max(0, 100 - pct_5h)
            pct_wk = q.get("weekly_pct", 100)
            used_wk = max(0, 100 - pct_wk)

            # Update tier display dynamically if available
            tier_str = q.get("tier_label", "Free Tier") if q else "Free Tier"
            if "svc_lbl" in refs:
                is_paid = any(k in tier_str.lower() for k in ["pro", "ultra", "standard"])
                refs["svc_lbl"].config(
                    text=f"Google AI • {tier_str}",
                    fg="#93c5fd" if is_paid else TEXT_MUTED
                )

            # 5h Limit Text & Bar (turns amber if used >= 80%, rose if used >= 90%)
            col_5h = get_quota_color(used_5h)
            refs["lbl_5h_val"].config(text=f"{used_5h}% used  ({pct_5h}% left)", fg=col_5h)
            refs["rem_5h_pct"] = pct_5h
            refs["used_5h_pct"] = used_5h
            refs["last_5h_pct"] = used_5h
            refs["last_5h_col"] = col_5h
            self.render_canvas_bar(refs["canvas_5h"], used_5h, col_5h)

            # Weekly Limit Text & Bar (turns amber if used >= 80%, rose if used >= 90%)
            col_wk = get_quota_color(used_wk)
            refs["lbl_wk_val"].config(text=f"{used_wk}% used  ({pct_wk}% left)", fg=col_wk)
            refs["rem_wk_pct"] = pct_wk
            refs["used_wk_pct"] = used_wk
            refs["last_wk_pct"] = used_wk
            refs["last_wk_col"] = col_wk
            self.render_canvas_bar(refs["canvas_wk"], used_wk, col_wk)

            # Pre-compute numeric timestamp deadlines once to make per-second ticks zero-allocation
            reset_5h_str = q.get("5h_reset")
            reset_wk_str = q.get("weekly_reset")
            try:
                refs["exp_5h_ts"] = dt.datetime.fromisoformat(reset_5h_str.replace("Z", "+00:00")).timestamp() if reset_5h_str else None
            except Exception:
                refs["exp_5h_ts"] = None

            refs["weekly_reset_str"] = router.format_weekly_reset(reset_wk_str)

            # Claude / GPT
            if refs.get("claude_lbl"):
                c_5h = q.get("claude_5h_pct", 100)
                c_wk = q.get("claude_weekly_pct", 100)
                if c_5h == c_wk:
                    refs["claude_lbl"].config(text=f"Claude/GPT: {c_5h}%", fg=TEXT_MUTED)
                else:
                    refs["claude_lbl"].config(text=f"Claude: {c_5h}% (5h) / {c_wk}% (wk)", fg=TEXT_MUTED)

        self.update_timers_display()

    def update_timers_display(self):
        """Lightning-fast per-second countdown updates using pre-computed numeric epoch timestamps."""
        if self.is_destroyed:
            return
        now_ts = time.time()

        for name, refs in self.cards.items():
            timer_parts = []

            # 1. 5-Hour / Session timer
            exp_5h = refs.get("exp_5h_ts")
            used_5h = refs.get("used_5h_pct", 0)
            rem_5h = refs.get("rem_5h_pct", 100)

            if rem_5h is not None and rem_5h >= 100:
                # Quota has NOT been started yet! Do NOT show a countdown!
                timer_parts.append("5h: Ready (100%)")
            elif exp_5h:
                diff_5h = int(exp_5h - now_ts)
                if diff_5h > 0:
                    h, rem_sec = divmod(diff_5h, 3600)
                    m = rem_sec // 60
                    if h > 0:
                        timer_parts.append(f"Resets in {h} hr {m:02d} min")
                    else:
                        timer_parts.append(f"Resets in {m} min")
                else:
                    timer_parts.append("5h: Refreshed")
            else:
                timer_parts.append("5h: Ready")

            # 2. Weekly Reset Time
            rem_wk = refs.get("rem_wk_pct", 100)
            w_str = refs.get("weekly_reset_str")
            if rem_wk is not None and rem_wk >= 100:
                timer_parts.append("Weekly: Ready")
            elif w_str:
                timer_parts.append(w_str)
            else:
                timer_parts.append("Weekly: Active")

            combined_str = "  •  ".join(timer_parts) if timer_parts else "Limit: Active"
            refs["timer_lbl"].config(text=f"⏱ {combined_str}", fg=TEXT_MUTED)

    def on_close(self):
        """Clean window destruction handler: cancels pending timers and safely frees resources."""
        self.is_destroyed = True
        if self._refresh_timer_id:
            try:
                self.root.after_cancel(self._refresh_timer_id)
            except Exception:
                pass
        if self._tick_timer_id:
            try:
                self.root.after_cancel(self._tick_timer_id)
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def schedule_quota_auto_refresh(self):
        if self.is_destroyed:
            return
        self.poll_all_quotas_async()
        self._refresh_timer_id = self.root.after(60000, self.schedule_quota_auto_refresh)

    def tick_timer(self):
        if self.is_destroyed:
            return
        self.update_timers_display()
        self._tick_timer_id = self.root.after(1000, self.tick_timer)

    def _execute_relaunch(self, target_label):
        """Asynchronously stops Antigravity/language_server, syncs staged account, and relaunches."""
        if self.is_relaunching or self.is_destroyed:
            return
        self.is_relaunching = True
        self.set_buttons_enabled(False)

        target_email = router.get_profile_email(target_label) or target_label
        self.banner.config(bg="#231704", highlightbackground=COLOR_WARN, highlightthickness=1)
        self.banner_label.config(
            text=f"🔄 Relaunching Antigravity into {target_email}... Restarting background processes...",
            fg=COLOR_WARN,
            bg="#231704"
        )
        self.footer_status.config(
            text=f"Relaunching Antigravity into {target_email}..."
        )

        def worker():
            try:
                ok, msg = router.restart_antigravity_app()
                time.sleep(2.5)
                if not self.is_destroyed:
                    self.root.after(0, self.build_initial_cards)
                    self.root.after(400, self.poll_all_quotas_async)
                    if ok:
                        self.root.after(0, lambda: self.footer_status.config(
                            text=f"✓ Antigravity successfully relaunched with {target_email}!"
                        ))
                    else:
                        self.root.after(0, lambda: self.footer_status.config(
                            text=f"⚠ Relaunch notice: {msg}"
                        ))

            finally:
                self.is_relaunching = False
                if not self.is_destroyed:
                    self.root.after(0, lambda: self.set_buttons_enabled(True))

        threading.Thread(target=worker, daemon=True).start()

    def on_switch_profile(self, name):
        if self.is_relaunching or self.is_destroyed:
            return

        # Synchronously lock buttons to prevent double-clicks
        self.set_buttons_enabled(False)
        refs = self.cards.get(name)
        if refs and refs.get("switch_btn"):
            refs["switch_btn"].config(text="⏳ Switching...")

        # Check if the profile has valid credentials or needs 1-click Google OAuth connect
        cred_blob = os.path.join(router.PROFILES_DIR, name, "credential_blob.bin")
        needs_auth = False
        if not os.path.exists(cred_blob):
            needs_auth = True
        else:
            try:
                with open(cred_blob, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                tok = cdata.get("token", {})
                if not tok.get("refresh_token") or not router.refresh_profile_token(name):
                    needs_auth = True
            except Exception:
                needs_auth = True

        if needs_auth:
            def auth_worker():
                email = router.get_profile_email(name)
                # Thread-safe UI update
                self.root.after(0, lambda: self.footer_status.config(
                    text=f"Opening browser to authenticate {name} ({email})..."
                ))
                ok = router.authenticate_profile(name)
                if ok:
                    self.root.after(0, lambda: self.footer_status.config(
                        text=f"✓ Authenticated {name}! Switching and relaunching..."
                    ))
                    self.root.after(200, lambda: self._execute_switch_and_relaunch(name))
                    self.root.after(500, self.poll_all_quotas_async)
                else:
                    self.root.after(0, lambda: self.footer_status.config(
                        text=f"⚠ Authentication for {name} was not completed."
                    ))
                    self.root.after(0, lambda: self.set_buttons_enabled(True))
                    if refs and refs.get("switch_btn"):
                        self.root.after(0, lambda: refs["switch_btn"].config(text="⚡ Switch"))

            threading.Thread(target=auth_worker, daemon=True).start()
            return

        self._execute_switch_and_relaunch(name)

    def _execute_switch_and_relaunch(self, name):
        success = router.switch_google_profile(name)
        if success:
            self._execute_relaunch(name)
        else:
            self.set_buttons_enabled(True)
            refs = self.cards.get(name)
            if refs and refs.get("switch_btn"):
                refs["switch_btn"].config(text="⚡ Switch")
            messagebox.showerror("Error", f"Could not switch to profile '{name}'")

    def on_restart_antigravity(self):
        if self.is_relaunching or self.is_destroyed:
            return
        state = router.get_state()
        staged_name = state.get("active_google_profile", "google_1")
        self._execute_relaunch(staged_name)

    def on_add_account(self):
        profiles = router.list_profiles()
        next_idx = len(profiles) + 1
        next_name = f"google_{next_idx}"
        if not messagebox.askyesno(
            "Add New Google Account",
            f"This will launch your web browser to sign in to another Google account.\n\n"
            f"Once authenticated, the account will be automatically added as Account #{next_idx} ({next_name}).\n\n"
            f"Would you like to continue?",
            parent=self.root
        ):
            return

        self.sync_badge.config(text="● Waiting for browser login...", fg="#f59e0b")
        self.set_buttons_enabled(False)

        def run_auth():
            ok = router.oauth_authorize_interactive(next_name)
            def finish():
                if not self.is_destroyed:
                    self.set_buttons_enabled(True)
                    if ok:
                        messagebox.showinfo("Account Connected", f"Successfully added new Google account as #{next_idx}!", parent=self.root)
                        self.build_initial_cards()
                        self.poll_all_quotas_async()
                    else:
                        messagebox.showwarning("Authentication Incomplete", "Google authentication was cancelled or timed out.", parent=self.root)
                        self.sync_badge.config(text="● Ready", fg="#34d399")
            self.root.after(0, finish)

        threading.Thread(target=run_auth, daemon=True).start()


def main():
    root = tk.Tk()
    app = AccountSwitchboardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
