# Antigravity Multi-Account Switcher & Real-Time Quota Monitor

[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue?logo=windows)](https://www.microsoft.com/windows)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Antigravity: 2.23.0+](https://img.shields.io/badge/Antigravity-2.23.0%2B-10b981)](https://antigravity.google/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A high-performance Windows desktop switchboard and CLI tool for developers operating with multiple **Google AI Pro / Antigravity** accounts and **Claude for Windows**.

Enables **<10 millisecond zero-browser session swapping**, live **per-second countdowns** for 5-hour throttles and weekly quota caps, direct **Google Cloud Code PA API** rate-limit telemetry, and unified desktop quota tracking.

---

## 🚀 Key Features

* **⚡ Zero-Downtime Session Swapping (<10ms)**:
  Swap active Google accounts across the Antigravity App (v2.23.0+), Antigravity IDE, `agy` CLI, and Gemini CLI without logging out or waiting through repetitive browser OAuth redirects.
* **📊 Direct Ground-Truth Google Quota Telemetry**:
  Queries `https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary` asynchronously per profile using live OAuth bearer tokens. Zero estimates or simulated mock counts.
* **⏱️ Dual Quota Tracking with Live Countdowns**:
  Real-time visibility into both:
  - **5-Hour Rolling Limit**: Dynamic refresh timer (e.g., `Resets in 3 hr 30 min`).
  - **Weekly Quota Window**: Precise percentage and reset target (e.g., `Resets in 2 days 6 hours`).
* **🟣 Claude for Windows Desktop App Integration**:
  Detects and monitors your official Claude desktop client (`Claude for Windows`), reading active subscription tiers (`Claude Pro [Stripe Subscription]`) and real-time 5-hour and 7-day usage limits directly.
* **🖥️ Modern Windows 11 Desktop GUI (`gui_app.py`)**:
  - Sleek dark slate glass design with Windows 11 native dark titlebar (`DwmSetWindowAttribute`).
  - Full Per-Monitor v2 DPI awareness (`shcore.dll`).
  - Non-blocking asynchronous quota querying via background thread pool (`concurrent.futures`).
  - Auto-refresh on window focus (`<FocusIn>`) with debounce.
* **🔑 1-Click Browser OAuth Re-Authentication**:
  Built-in local loopback server (`http://localhost:8085/oauth/callback`) to generate fresh OAuth bearer tokens with full Cloud Code API scopes in a single browser click.
* **🔄 Automatic Antigravity Client Relaunch**:
  Optionally terminate and cleanly relaunch the Antigravity desktop application upon switching with a single command or click.

---

## 🛠️ Architecture & Windows Deep-Dive

On Windows, the Antigravity desktop app (Electron) and its backend Language Server maintain active authentication across three persistent storage layers and the Windows Credential Manager:

1. **`~/.gemini/oauth_creds.json`**: Active OAuth 2.0 access and refresh tokens.
2. **`~/.gemini/google_accounts.json`**: Current active user email and identity map.
3. **`%APPDATA%\Antigravity\app_storage.json`**: Electron local state (`jetski.onboarding.lastLoginUsername`).
4. **Windows Credential Manager (`gemini:antigravity`)**: Binary-serialized credential blob managed via Win32 `advapi32.dll` (`CredReadW` / `CredWriteW`).

### How Profile Swapping Works

```mermaid
flowchart TD
    Vault["Profile Vault (~/.gemini/profiles/)<br>• Profile 1 (email_a)<br>• Profile 2 (email_b)<br>• Profile 3 (email_c)"]
    Router["antigravity-account-switcher<br>(router.py / gui_app.py)"]
    
    TargetA["~/.gemini/oauth_creds.json"]
    TargetB["~/.gemini/google_accounts.json"]
    TargetC["%APPDATA%/Antigravity/app_storage.json"]
    TargetD["Windows Credential Manager<br>(gemini:antigravity)"]
    
    App["Antigravity Client / Language Server"]

    Vault <-->|Snapshot & Stash| Router
    Router -->|Atomic Atomic Write (<10ms)| TargetA
    Router -->|Atomic Atomic Write| TargetB
    Router -->|Atomic Atomic Write| TargetC
    Router -->|Win32 advapi32.CredWriteW| TargetD
    TargetD --> App
```

1. **Snapshots**: Isolated profiles are stored under `~/.gemini/profiles/<profile_name>/`.
2. **Atomic Swap**: Switching overwrites the active configuration files atomically via temporary files to eliminate disk corruption.
3. **Win32 Credential Update**: Writes the profile's credential blob directly into the Windows Credential Manager so Antigravity never detects an invalid session.
4. **Instant Client Bind**: Hitting `Ctrl + R` (or auto-relaunching) binds the Antigravity desktop app to the new identity in seconds.

---

## 📦 Installation & Quick Start

### 1. Prerequisites
- Windows 10 or Windows 11 (64-bit)
- Python 3.10 or higher
- PowerShell 5.1 or PowerShell 7+

### 2. Clone the Repository
```powershell
git clone https://github.com/krenz444/antigravity-account-switcher.git
cd antigravity-account-switcher
```

### 3. Install Optional Dependencies
```powershell
pip install -r requirements.txt
```
*(Standard libraries `tkinter`, `ctypes`, `urllib`, `ssl`, and `json` are included with Windows Python. `psutil` and `Pillow` are recommended for desktop process monitoring and icon rendering).*

### 4. Create Desktop Shortcut
Generate a one-click shortcut on your Windows Desktop with the custom Antigravity icon:
```powershell
powershell -ExecutionPolicy Bypass -File .\create_shortcut.ps1
```

---

## ⚡ Setup Your Accounts

Follow this simple one-time onboarding workflow:

### Step 1: Snapshot Your First Account
Log in to your first Google account in Antigravity or the browser, then run:
```powershell
python router.py save 1
```
*(The tool auto-extracts your email address from your session token and labels the profile).*

### Step 2: Add Secondary Accounts
1. In the Antigravity App (or via `python router.py auth 2`), sign in to your second Google account.
2. Snapshot the second account:
   ```powershell
   python router.py save 2
   ```
3. Repeat for account 3 if desired (`python router.py save 3`).

---

## 💻 Usage Guide

### Desktop GUI Switchboard
Launch the desktop application:
```powershell
python gui_app.py
# or with the PowerShell helper:
.\ai_switch.ps1 app
```
- **Click "Switch Account"** on any card to immediately stage that profile and write credentials.
- **Click "Switch & Relaunch"** to swap credentials and cleanly reboot the Antigravity desktop app.
- **Click "Authorize via Browser"** on an expired card to refresh tokens through Google's OAuth consent flow.

### Command Line Interface (CLI)

```powershell
# Check real-time quota across all accounts & Claude
python router.py status

# Switch to account 1, 2, or 3
python router.py switch 1
python router.py switch 2
python router.py switch 3

# Switch by email or partial email
python router.py switch user@gmail.com

# Switch and automatically relaunch Antigravity
python router.py switch 2 -r

# Inspect Claude for Windows desktop quota
python router.py claude

# Run an Antigravity command with automated 429 rate-limit failover
python router.py run agy --prompt "Run full test suite"
```

### PowerShell Quick Aliases (`ai_switch.ps1`)

For rapid terminal execution, use the included `ai_switch.ps1` helper:

| Shortcut | Description |
| :--- | :--- |
| `.\ai_switch.ps1 status` | Parallel quota status query across all accounts. |
| `.\ai_switch.ps1 1` | Switch to account #1. |
| `.\ai_switch.ps1 2 -r` | Switch to account #2 and relaunch Antigravity. |
| `.\ai_switch.ps1 app` | Launch the Desktop GUI Switchboard. |
| `.\ai_switch.ps1 auth 2` | Browser OAuth sign-in for account #2. |

---

## ⚙️ Configuration (`config.json`)

The application works out-of-the-box with zero configuration, automatically detecting Antigravity, Claude Desktop, and active sessions. For advanced setups, all behavior can be customized in `config.json`:

```json
{
  "antigravity_exe_path": "",
  "google_profiles": [
    "google_1",
    "google_2",
    "google_3"
  ],
  "claude_profile": {
    "enabled": true,
    "desktop_app_dir": "",
    "config_dir": "~/.claude"
  },
  "ui": {
    "refresh_interval_seconds": 60,
    "theme": "dark_slate",
    "auto_relaunch_on_switch": false
  },
  "security": {
    "confirm_relaunch": false,
    "loopback_oauth_port": 8085
  }
}
```

### Options Breakdown
* **`antigravity_exe_path`**: Path to `Antigravity.exe`. If empty (`""`), the application dynamically scans running processes, `%LOCALAPPDATA%\Programs\antigravity`, `%PROGRAMFILES%\Antigravity`, and `%PATH%`.
* **`claude_profile.enabled`**: Set to `false` if you do not use Claude for Windows and want to hide the Claude card.
* **`claude_profile.desktop_app_dir`**: Custom location for Claude LevelDB/LocalStorage files if using a custom package or portable installation. Auto-detected across all Windows MSIX package builds if empty.
* **`ui.refresh_interval_seconds`**: Interval for background quota polling (default: `60` seconds).
* **`ui.auto_relaunch_on_switch`**: When `true`, switching an account automatically relaunches the Antigravity desktop app without requiring you to click "Switch & Relaunch".
* **`security.loopback_oauth_port`**: Local loopback port for browser OAuth consent flow (default: `8085`).

---

## 🛡️ Security, Privacy & Safety Invariants

* **🔒 100% Local Execution**: All session tokens and configuration files live exclusively on your local machine (`~/.gemini/profiles`). No cloud databases, external servers, or remote relays.
* **🛡️ Path Traversal Protection**: All profile names and input arguments are strictly sanitized (`[a-zA-Z0-9_\-.]`) to prevent directory traversal attacks.
* **🔐 Win32 Credential Vault**: Token blobs are written into the Windows Credential Manager (`gemini:antigravity`) via Win32 `advapi32.dll` (`CRED_PERSIST_LOCAL_MACHINE`), isolated to your authenticated Windows user SID.
* **🌐 Direct First-Party Endpoints**: All network communications connect directly to official endpoints over TLS 1.3:
  - `https://cloudcode-pa.googleapis.com` (Google Cloud Code PA API)
  - `https://oauth2.googleapis.com` (Google OAuth token refresh)
  - `https://accounts.google.com` (Google consent screen)
* **🛑 Safe Loopback Server**: The temporary OAuth authorization listener strictly binds to `127.0.0.1` (localhost only, never `0.0.0.0`), terminating immediately upon code retrieval or after a 120-second timeout.
* **⚡ Atomic File Operations**: Disk writes to active JSON configurations use temporary files with atomic OS replacement (`os.replace`) to guard against file corruption in case of unexpected termination or power loss.
* **🚫 Zero Telemetry**: Contains zero analytics, phone-home telemetry, tracking pixels, or third-party SDKs.

---

## 📄 License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 krenz444.
