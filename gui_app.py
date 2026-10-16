#!/usr/bin/env python3
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
import datetime as dt
import json
import os
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox


# Enable Per-Monitor High-DPI Awareness with multi-tier fallback
def enable_high_dpi_awareness():
    """Enables Per-Monitor v2 High-DPI awareness with graceful multi-tier fallbacks."""
    user32 = getattr(ctypes.windll, 'user32', None)
    if user32 and hasattr(user32, 'SetProcessDpiAwarenessContext'):
        try:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)):
                return True
        except Exception:
            pass

    shcore = getattr(ctypes.windll, 'shcore', None)
    if shcore and hasattr(shcore, 'SetProcessDpiAwareness'):
        try:
            PROCESS_PER_MONITOR_DPI_AWARE = 2
            if shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE) == 0:
                return True
        except Exception:
            pass

    if shcore and hasattr(shcore, 'SetProcessDpiAwareness'):
        try:
            PROCESS_SYSTEM_DPI_AWARE = 1
            if shcore.SetProcessDpiAwareness(PROCESS_SYSTEM_DPI_AWARE) == 0:
                return True
        except Exception:
            pass

    if user32 and hasattr(user32, 'SetProcessDPIAware'):
        try:
            return bool(user32.SetProcessDPIAware())
        except Exception:
            pass

    return False

enable_high_dpi_awareness()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import router

# ---------------------------------------------------------------------------
# Modern Aesthetic Themes & Color Engine
# ---------------------------------------------------------------------------

THEMES = {
    "modern_obsidian": {
        "name": "Modern Obsidian",
        "icon": "✨",
        "bg_main": "#080c14",
        "bg_card": "#0f1728",
        "bg_card_live": "#07211d",
        "bg_card_staged": "#091b33",
        "bg_card_claude": "#16102b",
        "border_default": "#1d283a",
        "border_live": "#10b981",
        "border_staged": "#0ea5e9",
        "border_claude": "#8b5cf6",
        "bg_progress_track": "#172033",
        "text_main": "#f8fafc",
        "text_muted": "#94a3b8",
        "text_dim": "#64748b",
        "color_active": "#10b981",
        "color_ready": "#38bdf8",
        "color_warn": "#f59e0b",
        "color_danger": "#f43f5e",
        "badge_claude": "#7c3aed",
        "color_claude": "#c084fc",
        "color_claude_bar": "#8b5cf6",
        "btn_primary": "#2563eb",
        "btn_primary_hover": "#1d4ed8",
        "btn_secondary": "#1e293b",
        "btn_secondary_hover": "#334155",
        "banner_live_bg": "#05241f",
        "banner_staged_bg": "#081e35",
        "sync_badge_bg": "#0f172a",
        "sync_badge_fg": "#38bdf8",
        "footer_sep": "#1a2436",
    },
    "tokyo_night": {
        "name": "Tokyo Night",
        "icon": "🌸",
        "bg_main": "#1a1b26",
        "bg_card": "#24283b",
        "bg_card_live": "#1b2d35",
        "bg_card_staged": "#1f2d48",
        "bg_card_claude": "#272042",
        "border_default": "#323854",
        "border_live": "#73daca",
        "border_staged": "#7dcfff",
        "border_claude": "#bb9af7",
        "bg_progress_track": "#292e42",
        "text_main": "#c0caf5",
        "text_muted": "#9aa5ce",
        "text_dim": "#565f89",
        "color_active": "#73daca",
        "color_ready": "#7dcfff",
        "color_warn": "#e0af68",
        "color_danger": "#f7768e",
        "badge_claude": "#bb9af7",
        "color_claude": "#bb9af7",
        "color_claude_bar": "#9d7cd8",
        "btn_primary": "#7aa2f7",
        "btn_primary_hover": "#5d8cf5",
        "btn_secondary": "#292e42",
        "btn_secondary_hover": "#3b4261",
        "banner_live_bg": "#1b2d35",
        "banner_staged_bg": "#1f2d48",
        "sync_badge_bg": "#24283b",
        "sync_badge_fg": "#7dcfff",
        "footer_sep": "#2f3549",
    },
    "cyberpunk_neon": {
        "name": "Cyberpunk Neon",
        "icon": "⚡",
        "bg_main": "#06060a",
        "bg_card": "#0e111a",
        "bg_card_live": "#051f1a",
        "bg_card_staged": "#091a30",
        "bg_card_claude": "#1c0d28",
        "border_default": "#1e2438",
        "border_live": "#00ffcc",
        "border_staged": "#00b4d8",
        "border_claude": "#f72585",
        "bg_progress_track": "#151928",
        "text_main": "#ffffff",
        "text_muted": "#38bdf8",
        "text_dim": "#64748b",
        "color_active": "#00ffcc",
        "color_ready": "#00b4d8",
        "color_warn": "#ffbe0b",
        "color_danger": "#f72585",
        "badge_claude": "#f72585",
        "color_claude": "#ff70a6",
        "color_claude_bar": "#f72585",
        "btn_primary": "#7209b7",
        "btn_primary_hover": "#560bad",
        "btn_secondary": "#151928",
        "btn_secondary_hover": "#262d47",
        "banner_live_bg": "#051f1a",
        "banner_staged_bg": "#091a30",
        "sync_badge_bg": "#111625",
        "sync_badge_fg": "#00ffcc",
        "footer_sep": "#1c2236",
    },
    "catppuccin_mocha": {
        "name": "Catppuccin Mocha",
        "icon": "🍵",
        "bg_main": "#11111b",
        "bg_card": "#1e1e2e",
        "bg_card_live": "#1b292b",
        "bg_card_staged": "#1c253b",
        "bg_card_claude": "#261e38",
        "border_default": "#313244",
        "border_live": "#a6e3a1",
        "border_staged": "#89b4fa",
        "border_claude": "#cba6f7",
        "bg_progress_track": "#313244",
        "text_main": "#cdd6f4",
        "text_muted": "#bac2de",
        "text_dim": "#6c7086",
        "color_active": "#a6e3a1",
        "color_ready": "#89b4fa",
        "color_warn": "#fab387",
        "color_danger": "#f38ba8",
        "badge_claude": "#cba6f7",
        "color_claude": "#cba6f7",
        "color_claude_bar": "#b4befe",
        "btn_primary": "#89b4fa",
        "btn_primary_hover": "#74c7ec",
        "btn_secondary": "#313244",
        "btn_secondary_hover": "#45475a",
        "banner_live_bg": "#1b292b",
        "banner_staged_bg": "#1c253b",
        "sync_badge_bg": "#181825",
        "sync_badge_fg": "#89b4fa",
        "footer_sep": "#27273a",
    },
    "nordic_frost": {
        "name": "Nordic Frost",
        "icon": "❄️",
        "bg_main": "#242933",
        "bg_card": "#2e3440",
        "bg_card_live": "#2b3d41",
        "bg_card_staged": "#2b3648",
        "bg_card_claude": "#373147",
        "border_default": "#434c5e",
        "border_live": "#a3be8c",
        "border_staged": "#88c0d0",
        "border_claude": "#b48ead",
        "bg_progress_track": "#3b4252",
        "text_main": "#eceff4",
        "text_muted": "#d8dee9",
        "text_dim": "#7b88a1",
        "color_active": "#a3be8c",
        "color_ready": "#88c0d0",
        "color_warn": "#ebcb8b",
        "color_danger": "#bf616a",
        "badge_claude": "#b48ead",
        "color_claude": "#b48ead",
        "color_claude_bar": "#88c0d0",
        "btn_primary": "#5e81ac",
        "btn_primary_hover": "#81a1c1",
        "btn_secondary": "#3b4252",
        "btn_secondary_hover": "#434c5e",
        "banner_live_bg": "#2b3d41",
        "banner_staged_bg": "#2b3648",
        "sync_badge_bg": "#2e3440",
        "sync_badge_fg": "#88c0d0",
        "footer_sep": "#3b4252",
    },
    "dark_slate": {
        "name": "Dark Slate",
        "icon": "🌌",
        "bg_main": "#0b1120",
        "bg_card": "#131d31",
        "bg_card_live": "#082320",
        "bg_card_staged": "#0a1e36",
        "bg_card_claude": "#15102a",
        "border_default": "#223048",
        "border_live": "#10b981",
        "border_staged": "#0284c7",
        "border_claude": "#7c3aed",
        "bg_progress_track": "#1e293b",
        "text_main": "#f8fafc",
        "text_muted": "#94a3b8",
        "text_dim": "#64748b",
        "color_active": "#10b981",
        "color_ready": "#38bdf8",
        "color_warn": "#f59e0b",
        "color_danger": "#f43f5e",
        "badge_claude": "#6d28d9",
        "color_claude": "#c084fc",
        "color_claude_bar": "#8b5cf6",
        "btn_primary": "#2563eb",
        "btn_primary_hover": "#1d4ed8",
        "btn_secondary": "#1e293b",
        "btn_secondary_hover": "#334155",
        "banner_live_bg": "#05241f",
        "banner_staged_bg": "#081e35",
        "sync_badge_bg": "#0f172a",
        "sync_badge_fg": "#38bdf8",
        "footer_sep": "#1e293b",
    }
}

DEFAULT_THEME = "modern_obsidian"
CURRENT_THEME = DEFAULT_THEME


def get_theme_palette(theme_name=None):
    """Retrieves full color palette dictionary for a given theme name."""
    key = theme_name or CURRENT_THEME
    return THEMES.get(key, THEMES[DEFAULT_THEME])


def apply_theme_globals(theme_name=None):
    """Updates module-level color constants to maintain backward compatibility with external imports."""
    global CURRENT_THEME, BG_MAIN, BG_CARD, BG_CARD_LIVE, BG_CARD_STAGED, BG_CARD_CLAUDE
    global BORDER_DEFAULT, BORDER_LIVE, BORDER_STAGED, BORDER_CLAUDE, BG_PROGRESS_TRACK
    global TEXT_MAIN, TEXT_MUTED, TEXT_DIM, COLOR_ACTIVE, COLOR_READY, COLOR_WARN, COLOR_DANGER
    global BADGE_CLAUDE, COLOR_CLAUDE, COLOR_CLAUDE_BAR, BTN_PRIMARY, BTN_PRIMARY_HOVER
    global BTN_SECONDARY, BTN_SECONDARY_HOVER

    palette = get_theme_palette(theme_name)
    CURRENT_THEME = theme_name if theme_name in THEMES else DEFAULT_THEME

    BG_MAIN = palette["bg_main"]
    BG_CARD = palette["bg_card"]
    BG_CARD_LIVE = palette["bg_card_live"]
    BG_CARD_STAGED = palette["bg_card_staged"]
    BG_CARD_CLAUDE = palette["bg_card_claude"]
    BORDER_DEFAULT = palette["border_default"]
    BORDER_LIVE = palette["border_live"]
    BORDER_STAGED = palette["border_staged"]
    BORDER_CLAUDE = palette["border_claude"]
    BG_PROGRESS_TRACK = palette["bg_progress_track"]

    TEXT_MAIN = palette["text_main"]
    TEXT_MUTED = palette["text_muted"]
    TEXT_DIM = palette["text_dim"]

    COLOR_ACTIVE = palette["color_active"]
    COLOR_READY = palette["color_ready"]
    COLOR_WARN = palette["color_warn"]
    COLOR_DANGER = palette["color_danger"]
    BADGE_CLAUDE = palette["badge_claude"]
    COLOR_CLAUDE = palette["color_claude"]
    COLOR_CLAUDE_BAR = palette["color_claude_bar"]

    BTN_PRIMARY = palette["btn_primary"]
    BTN_PRIMARY_HOVER = palette["btn_primary_hover"]
    BTN_SECONDARY = palette["btn_secondary"]
    BTN_SECONDARY_HOVER = palette["btn_secondary_hover"]
    return palette

# Initialize globals with modern obsidian default
apply_theme_globals(DEFAULT_THEME)


def get_quota_color(used_pct):
    """Consistent color scale across Google and Claude progress meters."""
    if used_pct is not None and used_pct >= 90:
        return COLOR_DANGER
    elif used_pct is not None and used_pct >= 80:
        return COLOR_WARN
    return COLOR_READY


def set_titlebar_color(root, hex_color=None):
    """Enables Windows 11 / 10 native immersive dark mode and synchronizes title bar caption color."""
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        if not hwnd:
            hwnd = root.winfo_id()

        # DWMWA_USE_IMMERSIVE_DARK_MODE (20 on Windows 11, 19 on Windows 10 1809+)
        value = ctypes.c_int(2)
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)) != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))

        # DWMWA_CAPTION_COLOR = 35 (Windows 11 Build 22000+)
        if hex_color and len(hex_color) == 7 and hex_color.startswith("#"):
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            color_ref = ctypes.c_uint32((b << 16) | (g << 8) | r)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 35, ctypes.byref(color_ref), ctypes.sizeof(color_ref)
            )
    except Exception:
        pass


def apply_dark_titlebar(root):
    """Legacy alias for backward compatibility."""
    set_titlebar_color(root, BG_MAIN)


def restore_window_geometry(root, saved_geom=None, default_width=1020, default_height=720):
    """Restores saved window width, height, and position, or centers with default dimensions."""
    try:
        root.update_idletasks()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()

        w = default_width
        h = default_height
        x = None
        y = None
        maximized = False

        if saved_geom and isinstance(saved_geom, dict):
            w = saved_geom.get("width", default_width)
            h = saved_geom.get("height", default_height)
            x = saved_geom.get("x")
            y = saved_geom.get("y")
            maximized = saved_geom.get("maximized", False)

        # Enforce minimum size and screen boundary clamping
        w = max(920, min(int(w), sw))
        h = max(640, min(int(h), sh))

        # Check if saved coordinates fall within active visible desktop space
        if x is None or y is None or x + w < 100 or x > sw - 100 or y < 0 or y > sh - 100:
            x = max(0, int((sw - w) / 2))
            y = max(0, int((sh - h) / 2.3))

        root.geometry(f"{w}x{h}+{x}+{y}")
        if maximized:
            try:
                root.state("zoomed")
            except Exception:
                pass
    except Exception:
        root.geometry(f"{default_width}x{default_height}")


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

        # Load configurable defaults and persistent runtime window geometry
        cfg = router.get_config()
        ui_cfg = cfg.get("ui", {})
        default_w = ui_cfg.get("default_width", 1020)
        default_h = ui_cfg.get("default_height", 720)

        theme_name = ui_cfg.get("theme", DEFAULT_THEME)
        self.theme_key = theme_name if theme_name in THEMES else DEFAULT_THEME
        self.theme = get_theme_palette(self.theme_key)
        apply_theme_globals(self.theme_key)

        state = router.get_state()
        saved_geom = state.get("window_geometry")

        self.last_normal_width = saved_geom.get("width") if saved_geom else default_w
        self.last_normal_height = saved_geom.get("height") if saved_geom else default_h
        self.last_normal_x = saved_geom.get("x") if saved_geom else None
        self.last_normal_y = saved_geom.get("y") if saved_geom else None

        self.root.title("Antigravity Multi-Account Switchboard & Quota Monitor")
        self.root.minsize(920, 640)
        restore_window_geometry(self.root, saved_geom, default_w, default_h)
        self.root.configure(bg=self.theme["bg_main"])

        # Track window resize & movement so normal width/position are always remembered
        self.root.bind("<Configure>", self.on_window_configure, add="+")

        # Apply Native Windows Dark Titlebar with active theme color
        set_titlebar_color(self.root, self.theme["bg_main"])

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
        t = self.theme
        # 1. Top Header Frame
        self.header = tk.Frame(self.root, bg=t["bg_main"], padx=24, pady=12)
        self.header.pack(fill=tk.X)

        # Action Buttons (Pack RIGHT first so they are anchored and never clipped)
        self.btn_box = tk.Frame(self.header, bg=t["bg_main"])
        self.btn_box.pack(side=tk.RIGHT, pady=2)

        self.theme_btn = make_button(
            self.btn_box,
            text=f"{t['icon']} {t['name']} ▾",
            font=("Segoe UI", 9, "bold"),
            bg=t["btn_secondary"],
            fg=t["text_main"],
            hover_bg=t["btn_secondary_hover"],
            padx=11,
            pady=5,
            command=self.on_toggle_theme_menu
        )
        self.theme_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.sync_badge = tk.Label(
            self.btn_box,
            text="● Live Syncing...",
            font=("Segoe UI", 8, "bold"),
            fg=t["sync_badge_fg"],
            bg=t["sync_badge_bg"],
            padx=9,
            pady=4
        )
        self.sync_badge.pack(side=tk.LEFT, padx=(0, 8))

        self.add_btn = make_button(
            self.btn_box,
            text="➕ Add Account",
            font=("Segoe UI", 9, "bold"),
            bg=t["btn_secondary"],
            fg=t["text_main"],
            hover_bg=t["btn_secondary_hover"],
            padx=12,
            pady=5,
            command=self.on_add_account
        )
        self.add_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.refresh_btn = make_button(
            self.btn_box,
            text="🔄 Refresh",
            font=("Segoe UI", 9, "bold"),
            bg=t["btn_primary"],
            fg="#ffffff",
            hover_bg=t["btn_primary_hover"],
            padx=13,
            pady=5,
            command=self.poll_all_quotas_async
        )
        self.refresh_btn.pack(side=tk.LEFT)

        # Title Box (Left side, fills remaining space)
        self.title_box = tk.Frame(self.header, bg=t["bg_main"])
        self.title_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.app_title = tk.Label(
            self.title_box,
            text="Antigravity Account Switchboard",
            font=("Segoe UI", 15, "bold"),
            fg=t["text_main"],
            bg=t["bg_main"]
        )
        self.app_title.pack(anchor="w")

        self.subtitle = tk.Label(
            self.title_box,
            text="Real-Time Antigravity & Claude Quotas • 5-Hour & Weekly Windows • 1-Click Switcher",
            font=("Segoe UI", 9),
            fg=t["text_muted"],
            bg=t["bg_main"]
        )
        self.subtitle.pack(anchor="w")

        # 2. Status Banner (Active Session Bar)
        self.banner = tk.Frame(
            self.root,
            bg=t["banner_live_bg"],
            padx=16,
            pady=9,
            highlightthickness=1,
            highlightbackground=t["border_live"]
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
            fg=t["color_active"],
            bg=t["banner_live_bg"],
            anchor="w"
        )
        self.banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 3. Cards Container Frame
        self.cards_outer = tk.Frame(self.root, bg=t["bg_main"], padx=24)
        self.cards_outer.pack(fill=tk.BOTH, expand=True)

        self.cards_frame = tk.Frame(self.cards_outer, bg=t["bg_main"])
        self.cards_frame.pack(fill=tk.BOTH, expand=True)

        # 4. Bottom Info Bar (Footer)
        self.footer_sep = tk.Frame(self.root, bg=t["footer_sep"], height=1)
        self.footer_sep.pack(fill=tk.X, padx=24)

        self.footer = tk.Frame(self.root, bg=t["bg_main"], padx=24, pady=10)
        self.footer.pack(fill=tk.X)

        self.footer_clock = tk.Label(
            self.footer,
            text="Last API Check: Pending",
            font=("Segoe UI", 8),
            fg=t["text_dim"],
            bg=t["bg_main"]
        )
        self.footer_clock.pack(side=tk.RIGHT)

        self.footer_status = tk.Label(
            self.footer,
            text="● Direct Google Cloud Code PA • Parallel OAuth 2.0 Pool",
            font=("Segoe UI", 8),
            fg=t["text_dim"],
            bg=t["bg_main"],
            anchor="w"
        )
        self.footer_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def on_toggle_theme_menu(self):
        """Displays modern theme picker dropdown popup."""
        menu = tk.Menu(
            self.root,
            tearoff=0,
            bg=self.theme["bg_card"],
            fg=self.theme["text_main"],
            activebackground=self.theme["btn_primary"],
            activeforeground="#ffffff",
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            bd=1
        )
        for t_key, t_val in THEMES.items():
            prefix = "✓ " if t_key == self.theme_key else "   "
            lbl = f"{prefix}{t_val['icon']} {t_val['name']}"
            menu.add_command(label=lbl, command=lambda k=t_key: self.set_theme(k))

        try:
            bx = self.theme_btn.winfo_rootx()
            by = self.theme_btn.winfo_rooty() + self.theme_btn.winfo_height() + 2
            menu.tk_popup(bx, by)
        except Exception:
            pass

    def set_theme(self, theme_key):
        """Applies new theme, persists to config.json, and re-renders cards."""
        if theme_key not in THEMES or self.is_destroyed:
            return
        self.theme_key = theme_key
        self.theme = get_theme_palette(theme_key)
        apply_theme_globals(theme_key)
        router.set_theme(theme_key)
        self.restyle_ui()
        self.build_initial_cards()
        if self.quotas:
            self.on_quotas_received(self.quotas)
        self.footer_status.config(text=f"✓ Applied aesthetic theme: {self.theme['name']}")

    def restyle_ui(self):
        """Dynamically applies current theme palette to all static container widgets."""
        t = self.theme
        self.root.configure(bg=t["bg_main"])
        set_titlebar_color(self.root, t["bg_main"])

        if hasattr(self, "header"):
            self.header.config(bg=t["bg_main"])
        if hasattr(self, "title_box"):
            self.title_box.config(bg=t["bg_main"])
        if hasattr(self, "app_title"):
            self.app_title.config(bg=t["bg_main"], fg=t["text_main"])
        if hasattr(self, "subtitle"):
            self.subtitle.config(bg=t["bg_main"], fg=t["text_muted"])
        if hasattr(self, "btn_box"):
            self.btn_box.config(bg=t["bg_main"])

        if hasattr(self, "theme_btn"):
            self.theme_btn.config(
                text=f"{t['icon']} {t['name']} ▾",
                bg=t["btn_secondary"],
                fg=t["text_main"],
                activebackground=t["btn_secondary_hover"],
                activeforeground=t["text_main"]
            )
            self.theme_btn.default_bg = t["btn_secondary"]
            self.theme_btn.hover_bg = t["btn_secondary_hover"]

        if hasattr(self, "sync_badge"):
            self.sync_badge.config(bg=t["sync_badge_bg"], fg=t["sync_badge_fg"])

        if hasattr(self, "add_btn"):
            self.add_btn.config(
                bg=t["btn_secondary"],
                fg=t["text_main"],
                activebackground=t["btn_secondary_hover"],
                activeforeground=t["text_main"]
            )
            self.add_btn.default_bg = t["btn_secondary"]
            self.add_btn.hover_bg = t["btn_secondary_hover"]

        if hasattr(self, "refresh_btn"):
            self.refresh_btn.config(
                bg=t["btn_primary"],
                fg="#ffffff",
                activebackground=t["btn_primary_hover"],
                activeforeground="#ffffff"
            )
            self.refresh_btn.default_bg = t["btn_primary"]
            self.refresh_btn.hover_bg = t["btn_primary_hover"]

        if hasattr(self, "cards_outer"):
            self.cards_outer.config(bg=t["bg_main"])
        if hasattr(self, "cards_frame"):
            self.cards_frame.config(bg=t["bg_main"])

        if hasattr(self, "footer_sep"):
            self.footer_sep.config(bg=t["footer_sep"])
        if hasattr(self, "footer"):
            self.footer.config(bg=t["bg_main"])
        if hasattr(self, "footer_clock"):
            self.footer_clock.config(bg=t["bg_main"], fg=t["text_dim"])
        if hasattr(self, "footer_status"):
            self.footer_status.config(bg=t["bg_main"], fg=t["text_dim"])

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
        try:
            self.theme_btn.config(state=st, cursor=cur)
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
            self.banner.config(bg=self.theme["banner_live_bg"], highlightbackground=self.theme["border_live"], highlightthickness=1)
            self.banner_label.config(
                text=f"● LIVE SESSION: {live_email}  •  Synchronized with Antigravity App",
                fg=self.theme["color_active"],
                bg=self.theme["banner_live_bg"]
            )
            self.banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        else:
            self.banner.config(bg=self.theme["banner_staged_bg"], highlightbackground=self.theme["border_staged"], highlightthickness=1)
            self.banner_label.config(
                text=f"● Live: {live_email or 'Unknown'}   ➔   📁 Staged: {staged_email}",
                fg=self.theme["color_ready"],
                bg=self.theme["banner_staged_bg"]
            )
            # Pack restart button FIRST on the RIGHT so it is never overlapped by expanding label
            self.restart_btn.pack(side=tk.RIGHT, padx=(12, 0))
            self.banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.action_buttons.append(self.restart_btn)


        # Build Profile Cards
        if not profiles:
            welcome_card = tk.Frame(
                self.cards_frame,
                bg=self.theme["bg_card"],
                padx=24,
                pady=20,
                highlightthickness=1,
                highlightbackground=self.theme["border_default"]
            )
            welcome_card.pack(fill=tk.X, pady=8)
            tk.Label(
                welcome_card,
                text="👋 Welcome to Antigravity Account Switcher",
                font=("Segoe UI", 12, "bold"),
                fg=self.theme["text_main"],
                bg=self.theme["bg_card"]
            ).pack(anchor="w", pady=(0, 4))
            tk.Label(
                welcome_card,
                text="No Google accounts have been registered yet.\nConnect your first account via browser or snapshot your currently active Antigravity session.",
                font=("Segoe UI", 9),
                fg=self.theme["text_muted"],
                bg=self.theme["bg_card"],
                justify=tk.LEFT
            ).pack(anchor="w", pady=(0, 12))
            btn_row = tk.Frame(welcome_card, bg=self.theme["bg_card"])
            btn_row.pack(anchor="w")

            make_button(
                btn_row,
                text="➕ Connect Account via Browser",
                font=("Segoe UI", 9, "bold"),
                bg=self.theme["btn_primary"],
                fg="#ffffff",
                hover_bg=self.theme["btn_primary_hover"],
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
                bg=self.theme["btn_secondary"],
                fg=self.theme["text_main"],
                hover_bg=self.theme["btn_secondary_hover"],
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
                card_bg = self.theme["bg_card_live"]
                card_border = self.theme["border_live"]
                badge_bg = self.theme["color_active"]
                badge_fg = "#041f1a" if self.theme_key == "cyberpunk_neon" else "#ecfdf5"
                status_txt = "● ACTIVE IN APP"
                status_color = self.theme["color_active"]
            elif is_staged:
                card_bg = self.theme["bg_card_staged"]
                card_border = self.theme["border_staged"]
                badge_bg = self.theme["color_ready"]
                badge_fg = "#051626" if self.theme_key == "cyberpunk_neon" else "#f0f9ff"
                status_txt = "● STAGED"
                status_color = self.theme["color_ready"]
            else:
                card_bg = self.theme["bg_card"]
                card_border = self.theme["border_default"]
                badge_bg = self.theme["btn_primary"]
                badge_fg = "#eff6ff"
                status_txt = "● READY"
                status_color = self.theme["color_ready"]

            card = tk.Frame(
                self.cards_frame,
                bg=card_bg,
                padx=16,
                pady=10,
                highlightthickness=2 if (is_live or is_staged) else 1,
                highlightbackground=card_border
            )
            card.pack(fill=tk.X, pady=4)

            # Subtle modern hover elevation for non-highlighted cards
            if not is_live and not is_staged:
                card.bind("<Enter>", lambda e, c=card: c.config(highlightbackground=self.theme["border_staged"]) if not self.is_destroyed else None)
                card.bind("<Leave>", lambda e, c=card: c.config(highlightbackground=self.theme["border_default"]) if not self.is_destroyed else None)

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
                        self.root.after(1500, lambda: cbtn.config(text=" 📋", fg=self.theme["text_dim"]) if not self.is_destroyed else None)
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
                fg=self.theme["text_main"],
                bg=card_bg,
                cursor="hand2"
            )
            email_lbl.pack(side=tk.LEFT)

            copy_btn = tk.Label(
                badge_frame,
                text=" 📋",
                font=("Segoe UI", 8),
                fg=self.theme["text_dim"],
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
                fg=self.theme["text_muted"],
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

            lbl_5h_val = tk.Label(row_5h, text="Querying API...", font=("Segoe UI", 11, "bold"), fg=self.theme["text_main"], bg=card_bg)
            lbl_5h_val.pack(side=tk.RIGHT)

            lbl_5h_title = tk.Label(row_5h, text="Session limit (5h):", font=("Segoe UI", 8, "bold"), fg=self.theme["text_muted"], bg=card_bg)
            lbl_5h_title.pack(side=tk.LEFT)

            canvas_5h = tk.Canvas(mid_col, height=7, bg=self.theme["bg_progress_track"], highlightthickness=0)
            canvas_5h.pack(fill=tk.X, pady=(1, 4))

            # 2. Weekly Limit Row (Value packed RIGHT first, then title packed LEFT)
            row_wk = tk.Frame(mid_col, bg=card_bg)
            row_wk.pack(fill=tk.X, pady=(1, 1))

            lbl_wk_val = tk.Label(row_wk, text="Querying API...", font=("Segoe UI", 11, "bold"), fg=self.theme["text_main"], bg=card_bg)
            lbl_wk_val.pack(side=tk.RIGHT)

            lbl_wk_title = tk.Label(row_wk, text="Weekly window (7d):", font=("Segoe UI", 8, "bold"), fg=self.theme["text_muted"], bg=card_bg)
            lbl_wk_title.pack(side=tk.LEFT)

            canvas_wk = tk.Canvas(mid_col, height=7, bg=self.theme["bg_progress_track"], highlightthickness=0)
            canvas_wk.pack(fill=tk.X, pady=(1, 4))

            # 3. Timers Row
            timer_row = tk.Frame(mid_col, bg=card_bg)
            timer_row.pack(fill=tk.X, pady=(2, 0))

            if show_model_only:
                claude_lbl = tk.Label(timer_row, text="Claude/GPT: 100%", font=("Segoe UI", 8), fg=self.theme["text_muted"], bg=card_bg)
                claude_lbl.pack(side=tk.RIGHT)
            else:
                claude_lbl = None

            timer_lbl = tk.Label(timer_row, text="⏱ Syncing quota timers...", font=("Segoe UI", 8, "bold"), fg=self.theme["text_muted"], bg=card_bg)
            timer_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # Right Section: Action Controls
            right_col = tk.Frame(card, bg=card_bg)
            right_col.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))

            if is_live:
                switch_btn = tk.Button(
                    right_col,
                    text="✓ Live in App",
                    font=("Segoe UI", 9, "bold"),
                    bg=self.theme["bg_card_live"],
                    fg=self.theme["color_active"],
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
                    bg=self.theme["btn_primary"],
                    fg="#ffffff",
                    hover_bg=self.theme["btn_primary_hover"],
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
                bg=self.theme["bg_card_claude"],
                padx=16,
                pady=10,
                highlightthickness=2,
                highlightbackground=self.theme["border_claude"]
            )
            c_card.pack(fill=tk.X, pady=4)

            # Left Section: Identity Column (280px fixed width, matching Google cards)
            c_left_col = tk.Frame(c_card, bg=self.theme["bg_card_claude"], width=280)
            c_left_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 14))
            c_left_col.pack_propagate(False)

            # Line 1: Service Badge + Profile Name + Tier Pill
            c_badge_frame = tk.Frame(c_left_col, bg=self.theme["bg_card_claude"])
            c_badge_frame.pack(anchor="w")

            c_num_badge = tk.Label(
                c_badge_frame,
                text=" Claude ",
                font=("Segoe UI", 9, "bold"),
                bg=self.theme["badge_claude"],
                fg="#faf5ff",
                padx=5,
                pady=1
            )
            c_num_badge.pack(side=tk.LEFT, padx=(0, 6))

            c_prof_lbl = tk.Label(
                c_badge_frame,
                text="Claude Pro",
                font=("Segoe UI", 11, "bold"),
                fg=self.theme["text_main"],
                bg=self.theme["bg_card_claude"]
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
            c_email_row = tk.Frame(c_left_col, bg=self.theme["bg_card_claude"])
            c_email_row.pack(anchor="w", pady=(3, 0))

            c_email_lbl = tk.Label(
                c_email_row,
                text=c_email,
                font=("Segoe UI", 9),
                fg=self.theme["text_muted"],
                bg=self.theme["bg_card_claude"],
                cursor="hand2"
            )
            c_email_lbl.pack(side=tk.LEFT)

            c_copy_btn = tk.Label(
                c_email_row,
                text=" 📋",
                font=("Segoe UI", 8),
                fg=self.theme["text_dim"],
                bg=self.theme["bg_card_claude"],
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
                bg=self.theme["bg_card_claude"]
            )
            c_status_pill.pack(anchor="w", pady=(4, 0))

            # Middle Section: Quota Bars & Live Status
            c_mid_col = tk.Frame(c_card, bg=self.theme["bg_card_claude"])
            c_mid_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12)

            # 1. Session Limit Row (Value packed RIGHT first, then title packed LEFT)
            c_row_5h = tk.Frame(c_mid_col, bg=self.theme["bg_card_claude"])
            c_row_5h.pack(fill=tk.X, pady=(0, 1))

            c_lbl_5h_val = tk.Label(c_row_5h, text=f"{init_5h_used}% used  ({init_5h_rem}% left)", font=("Segoe UI", 11, "bold"), fg=init_5h_txt, bg=self.theme["bg_card_claude"])
            c_lbl_5h_val.pack(side=tk.RIGHT)

            c_lbl_5h_title = tk.Label(c_row_5h, text="Session limit (5h):", font=("Segoe UI", 8, "bold"), fg=self.theme["text_muted"], bg=self.theme["bg_card_claude"])
            c_lbl_5h_title.pack(side=tk.LEFT)

            c_canvas_5h = tk.Canvas(c_mid_col, height=7, bg=self.theme["bg_progress_track"], highlightthickness=0)
            c_canvas_5h.pack(fill=tk.X, pady=(1, 4))

            # 2. Weekly Limit Row (Value packed RIGHT first, then title packed LEFT)
            c_row_wk = tk.Frame(c_mid_col, bg=self.theme["bg_card_claude"])
            c_row_wk.pack(fill=tk.X, pady=(1, 1))

            c_lbl_wk_val = tk.Label(c_row_wk, text=f"{init_wk_used}% used  ({init_wk_rem}% left)", font=("Segoe UI", 11, "bold"), fg=init_wk_txt, bg=self.theme["bg_card_claude"])
            c_lbl_wk_val.pack(side=tk.RIGHT)

            c_lbl_wk_title = tk.Label(c_row_wk, text="Weekly window (7d):", font=("Segoe UI", 8, "bold"), fg=self.theme["text_muted"], bg=self.theme["bg_card_claude"])
            c_lbl_wk_title.pack(side=tk.LEFT)

            c_canvas_wk = tk.Canvas(c_mid_col, height=7, bg=self.theme["bg_progress_track"], highlightthickness=0)
            c_canvas_wk.pack(fill=tk.X, pady=(1, 4))

            # 3. Status & App Row
            c_detail_row = tk.Frame(c_mid_col, bg=self.theme["bg_card_claude"])
            c_detail_row.pack(fill=tk.X, pady=(2, 0))

            if show_model_only:
                c_billing_lbl = tk.Label(
                    c_detail_row,
                    text=f"Model: {model_init}  🔴" if init_wk_used >= 80 else f"Model: {model_init}",
                    font=("Segoe UI", 8, "bold"),
                    fg="#f87171" if init_wk_used >= 80 else self.theme["text_muted"],
                    bg=self.theme["bg_card_claude"]
                )
                c_billing_lbl.pack(side=tk.RIGHT)
            else:
                c_billing_lbl = None

            c_timer_lbl = tk.Label(
                c_detail_row,
                text=f"⏱ {s_reset_init}  •  {w_reset_init}",
                font=("Segoe UI", 8, "bold"),
                fg=self.theme["text_muted"],
                bg=self.theme["bg_card_claude"]
            )
            c_timer_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # Right Section: Action Button (Open Windows App)
            c_right_col = tk.Frame(c_card, bg=self.theme["bg_card_claude"])
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
                bg=self.theme["badge_claude"],
                fg="#faf5ff",
                hover_bg=self.theme["border_claude"],
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

        track_bg = self.theme.get("bg_progress_track", BG_PROGRESS_TRACK)
        try:
            canvas.config(bg=track_bg)
        except Exception:
            pass

        if track_id is None:
            canvas._track_id = canvas.create_rectangle(0, 0, w, h, fill=track_bg, width=0)
            canvas._fill_id = canvas.create_rectangle(0, 0, fill_w, h, fill=color, width=0)
        else:
            canvas.coords(track_id, 0, 0, w, h)
            canvas.itemconfig(track_id, fill=track_bg)
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
        self.sync_badge.config(text="● Querying API...", fg=self.theme["color_warn"], bg=self.theme["bg_card"])

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

        self.sync_badge.config(text=f"● Live Synced ({now_str})", fg=self.theme["color_active"], bg=self.theme["bg_card_live"])
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


            if not q:
                refs["lbl_5h_val"].config(text="Query Failed", fg=COLOR_WARN)
                refs["lbl_wk_val"].config(text="Query Failed", fg=COLOR_WARN)
                refs["timer_lbl"].config(text="● Could not query quota", fg=COLOR_WARN)
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

            if q.get("offline"):
                refs["lbl_5h_val"].config(text="Offline", fg=COLOR_WARN)
                refs["lbl_wk_val"].config(text="Offline", fg=COLOR_WARN)
                refs["timer_lbl"].config(text="● Network offline / Unreachable", fg=COLOR_WARN)
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

            if q.get("rate_limited"):
                refs["lbl_5h_val"].config(text="Rate Limited", fg=COLOR_DANGER)
                refs["lbl_wk_val"].config(text="Rate Limited", fg=COLOR_DANGER)
                refs["timer_lbl"].config(text="● 429 Too Many Requests (Backing off)", fg=COLOR_DANGER)
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
                self.render_canvas_bar(refs["canvas_5h"], 0, COLOR_DANGER)
                self.render_canvas_bar(refs["canvas_wk"], 0, COLOR_DANGER)
                continue

            if q.get("auth_required") or q.get("5h_pct") is None:
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
                    fg=self.theme["color_ready"] if is_paid else self.theme["text_muted"]
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

    def on_window_configure(self, event):
        """Continuously tracks normal window geometry so width and position are always remembered."""
        if self.is_destroyed:
            return
        if event.widget == self.root:
            try:
                if self.root.state() == "normal":
                    w = self.root.winfo_width()
                    h = self.root.winfo_height()
                    x = self.root.winfo_x()
                    y = self.root.winfo_y()
                    if w >= 200 and h >= 200:
                        self.last_normal_width = w
                        self.last_normal_height = h
                        self.last_normal_x = x
                        self.last_normal_y = y
            except Exception:
                pass

    def on_close(self):
        """Clean window destruction handler: remembers window geometry, cancels pending timers, and safely frees resources."""
        # Persist window width, height, and desktop position
        try:
            state = router.get_state()
            w = self.last_normal_width or self.root.winfo_width()
            h = self.last_normal_height or self.root.winfo_height()
            x = self.last_normal_x if self.last_normal_x is not None else self.root.winfo_x()
            y = self.last_normal_y if self.last_normal_y is not None else self.root.winfo_y()
            is_max = False
            try:
                is_max = (self.root.state() == "zoomed")
            except Exception:
                pass

            if w >= 200 and h >= 200:
                state["window_geometry"] = {
                    "width": int(w),
                    "height": int(h),
                    "x": int(x),
                    "y": int(y),
                    "maximized": bool(is_max)
                }
                router.save_state(state)
        except Exception:
            pass

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

        self.sync_badge.config(text="● Waiting for browser login...", fg=self.theme["color_warn"])
        self.set_buttons_enabled(False)

        def run_auth():
            ok = router.authenticate_profile(next_name)
            def finish():
                if not self.is_destroyed:
                    self.set_buttons_enabled(True)
                    if ok:
                        messagebox.showinfo("Account Connected", f"Successfully added new Google account as #{next_idx}!", parent=self.root)
                        self.build_initial_cards()
                        self.poll_all_quotas_async()
                    else:
                        messagebox.showwarning("Authentication Incomplete", "Google authentication was cancelled or timed out.", parent=self.root)
                        self.sync_badge.config(text="● Ready", fg=self.theme["color_active"])
            self.root.after(0, finish)

        threading.Thread(target=run_auth, daemon=True).start()


def main():
    root = tk.Tk()
    app = AccountSwitchboardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
