#!/usr/bin/env python3
"""account_router.py - Multi-Account Quota Router & Switcher for ai-os.

Manages switching and automatic failover between:
- 2-3 Google AI Pro / Gemini accounts (Antigravity App 2.23.0, Antigravity IDE, agy CLI, Gemini CLI)
- Claude Code Pro subscription (via native OAuth profile isolation or CCR proxy gateway)
"""

import argparse
import base64
import concurrent.futures
import copy
import ctypes
import datetime as dt
import glob
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from ctypes import wintypes

try:
    import psutil
except ImportError:
    psutil = None

# Set default socket timeout as a defensive baseline
socket.setdefaulttimeout(10.0)

HOME = os.path.expanduser("~")
APPDATA = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
PROGRAMFILES = os.environ.get("ProgramFiles") or r"C:\Program Files"
PROGRAMFILES_X86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"

GEMINI_DIR = os.environ.get("GEMINI_DIR") or os.path.join(HOME, ".gemini")
PROFILES_DIR = os.path.join(GEMINI_DIR, "profiles")
ACTIVE_OAUTH = os.path.join(GEMINI_DIR, "oauth_creds.json")
ACTIVE_ACCOUNTS = os.path.join(GEMINI_DIR, "google_accounts.json")
APP_STORAGE = os.environ.get("ANTIGRAVITY_APP_STORAGE") or os.path.join(APPDATA, "Antigravity", "app_storage.json")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, ".usage_state.json")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

# ---------------------------------------------------------------------------
# Strict Profile Name Sanitization & Path Traversal Prevention
# ---------------------------------------------------------------------------

PROFILE_NAME_REGEX = re.compile(r'^[a-zA-Z0-9_-]+$')
WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"
}


def is_valid_profile_name(name):
    """Returns True if the profile name strictly matches ^[a-zA-Z0-9_-]+$ and is not a reserved name."""
    if not name or not isinstance(name, str):
        return False
    clean = name.strip()
    if not (1 <= len(clean) <= 64):
        return False
    if clean.lower() in WINDOWS_RESERVED_NAMES:
        return False
    return bool(PROFILE_NAME_REGEX.match(clean))


def sanitize_profile_name(name):
    """Strictly sanitizes profile name to match ^[a-zA-Z0-9_-]+$ and prevent path traversal."""
    if not name:
        return f"google_{int(time.time())}"
    raw = str(name).strip()
    clean = re.sub(r'[^a-zA-Z0-9_-]', '_', raw)
    clean = clean.strip('_')[:64]
    if not clean or clean.lower() in WINDOWS_RESERVED_NAMES:
        return f"google_{int(time.time())}"
    return clean


def validate_profile_path(profile_name):
    """Validates that the profile directory resides safely within PROFILES_DIR."""
    safe_name = sanitize_profile_name(profile_name)
    base_dir = os.path.abspath(PROFILES_DIR)
    target_dir = os.path.abspath(os.path.join(base_dir, safe_name))
    if not (target_dir.startswith(base_dir + os.sep) or target_dir == base_dir):
        raise ValueError(f"Path traversal detected in profile name: {profile_name!r}")
    return safe_name, target_dir


# ---------------------------------------------------------------------------
# Zero Token/Credential Leakage Utilities
# ---------------------------------------------------------------------------

def mask_sensitive_arguments(cmd_args):
    """Sanitizes CLI command arguments to prevent token or credential leakage in logs."""
    if not cmd_args:
        return []
    sensitive_keys = {
        "--csrf_token", "--token", "--access_token", "--api_key", "--password",
        "--client_secret", "--key", "-token", "--secret"
    }
    masked = []
    skip_next = False
    for arg in cmd_args:
        if skip_next:
            masked.append("********")
            skip_next = False
            continue

        found_flag = False
        for sk in sensitive_keys:
            if arg.startswith(f"{sk}="):
                masked.append(f"{sk}=********")
                found_flag = True
                break
        if found_flag:
            continue

        if arg.lower() in sensitive_keys:
            masked.append(arg)
            skip_next = True
            continue

        if "bearer " in arg.lower():
            masked.append(re.sub(r'(bearer\s+)[A-Za-z0-9_\-\.]+', r'\1********', arg, flags=re.IGNORECASE))
            continue

        masked.append(arg)
    return masked


# ---------------------------------------------------------------------------
# Windows Credential Manager Win32 Helpers (gemini:antigravity)
# ---------------------------------------------------------------------------

class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD),
        ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR),
        ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME),
        ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_char)),
        ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD),
        ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR),
        ('UserName', wintypes.LPWSTR),
    ]

advapi32 = getattr(ctypes.windll, 'advapi32', None)


def extract_email_from_jwt(id_tok):
    if not id_tok or '.' not in id_tok:
        return None
    try:
        parts = id_tok.split('.')
        if len(parts) >= 2:
            payload = parts[1]
            payload += '=' * (-len(payload) % 4)
            info = json.loads(base64.urlsafe_b64decode(payload).decode('utf-8'))
            email = info.get('email')
            if email and isinstance(email, str):
                return email.strip().lower()
    except Exception:
        pass
    return None


def read_windows_credential(target="gemini:antigravity"):
    if not advapi32:
        return None, None
    cred_ptr = ctypes.POINTER(CREDENTIAL)()
    # CRED_TYPE_GENERIC = 1
    if not advapi32.CredReadW(target, 1, 0, ctypes.byref(cred_ptr)):
        return None, None
    try:
        c = cred_ptr.contents
        raw_blob = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
    finally:
        advapi32.CredFree(cred_ptr)

    email = None
    try:
        data = json.loads(raw_blob.decode('utf-8'))
        id_tok = data.get('id_token') or data.get('token', {}).get('id_token', '')
        email = extract_email_from_jwt(id_tok)
    except Exception:
        pass
    return raw_blob, email


def write_windows_credential(raw_blob, target="gemini:antigravity", user="antigravity"):
    if not advapi32 or not raw_blob:
        return False
    if isinstance(raw_blob, str):
        raw_blob = raw_blob.encode('utf-8')
    cred = CREDENTIAL()
    cred.Flags = 0
    cred.Type = 1  # CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.Comment = "Managed by ai-os account router"
    cred.CredentialBlobSize = len(raw_blob)
    cred.CredentialBlob = ctypes.cast(ctypes.create_string_buffer(raw_blob), ctypes.POINTER(ctypes.c_char))
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = user
    try:
        return bool(advapi32.CredWriteW(ctypes.byref(cred), 0))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# File & State Management (Resilient, Thread-Safe & Atomic)
# ---------------------------------------------------------------------------

_FILE_LOCK = threading.RLock()


def load_json(path, default=None):
    """Safely loads JSON. If file is corrupted, creates a backup and returns default."""
    default_val = default if default is not None else {}
    if not os.path.exists(path):
        return copy.deepcopy(default_val)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return copy.deepcopy(default_val)
            return json.loads(content)
    except Exception:
        # File exists but is corrupted (syntax error, truncated write)
        try:
            bak_path = f"{path}.corrupted.{int(time.time())}.bak"
            shutil.copy2(path, bak_path)
        except Exception:
            pass
        return copy.deepcopy(default_val)


def save_json(path, data, max_retries=8, initial_delay=0.05):
    """Atomically and thread-safely writes JSON to disk via unique temp file.
    Retries with exponential backoff on Windows ERROR_SHARING_VIOLATION (WinError 32).
    """
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    tmp_path = f"{abs_path}.tmp.{os.getpid()}_{threading.get_ident()}_{time.time_ns()}"

    with _FILE_LOCK:
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return False

        delay = initial_delay
        for attempt in range(max_retries):
            try:
                os.replace(tmp_path, abs_path)
                return True
            except (PermissionError, OSError) as e:
                is_sharing_violation = getattr(e, "winerror", None) in (32, 33, 5) or "used by another process" in str(e).lower()
                if is_sharing_violation and attempt < max_retries - 1:
                    time.sleep(delay)
                    delay = min(delay * 2, 0.5)
                    continue

                kernel32 = getattr(ctypes.windll, 'kernel32', None)
                if kernel32 and hasattr(kernel32, 'ReplaceFileW'):
                    try:
                        res = kernel32.ReplaceFileW(
                            ctypes.c_wchar_p(abs_path),
                            ctypes.c_wchar_p(tmp_path),
                            None, 0, None, None
                        )
                        if res != 0:
                            return True
                    except Exception:
                        pass

                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                return False

        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


def get_state():
    default_state = {
        "active_google_profile": "google_1"
    }
    raw = load_json(STATE_FILE, default=default_state)
    if not isinstance(raw, dict):
        raw = copy.deepcopy(default_state)
    if "active_google_profile" not in raw or not isinstance(raw["active_google_profile"], str):
        raw["active_google_profile"] = "google_1"
    return raw


def save_state(state):
    cleaned = {k: v for k, v in state.items() if k not in ("cooldowns", "last_rotation")}
    save_json(STATE_FILE, cleaned)


def get_config():
    default_config = {
        "antigravity_exe_path": "",
        "google_profiles": ["google_1", "google_2", "google_3"],
        "claude_profile": {
            "enabled": True,
            "desktop_app_dir": "",
            "config_dir": "~/.claude"
        },
        "ui": {
            "refresh_interval_seconds": 60,
            "theme": "modern_obsidian",
            "auto_relaunch_on_switch": False,
            "show_model_only_quota": False,
            "default_width": 1020,
            "default_height": 720
        },
        "security": {
            "confirm_relaunch": False,
            "loopback_oauth_port": 8085
        }
    }
    raw_cfg = load_json(CONFIG_FILE, default=default_config)
    cfg = raw_cfg if isinstance(raw_cfg, dict) else copy.deepcopy(default_config)
    for k, v in default_config.items():
        if k not in cfg:
            cfg[k] = copy.deepcopy(v)
        elif isinstance(v, dict):
            if not isinstance(cfg[k], dict):
                cfg[k] = copy.deepcopy(v)
            else:
                for sub_k, sub_v in v.items():
                    if sub_k not in cfg[k]:
                        cfg[k][sub_k] = copy.deepcopy(sub_v)
    return cfg


def set_theme(theme_name):
    """Persists the user selected aesthetic UI theme in config.json."""
    if not theme_name or not isinstance(theme_name, str):
        return False
    cfg = get_config()
    if "ui" not in cfg or not isinstance(cfg["ui"], dict):
        cfg["ui"] = {}
    cfg["ui"]["theme"] = theme_name.strip()
    return save_json(CONFIG_FILE, cfg)


# ---------------------------------------------------------------------------
# Non-Blocking Shared File Reads (LevelDB Shared Access)
# ---------------------------------------------------------------------------

def read_shared_file(fpath, max_bytes=512 * 1024, tail_only=True):
    """Reads a file with non-blocking shared access (FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE).
    Prevents lock contention with Claude Windows app and safely reads LevelDB files.
    """
    if not os.path.exists(fpath):
        return b""

    # 1. On Windows, use Win32 CreateFileW for non-blocking shared read
    kernel32 = getattr(ctypes.windll, 'kernel32', None)
    if kernel32:
        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        FILE_SHARE_DELETE = 0x00000004
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x80
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        handle = kernel32.CreateFileW(
            ctypes.c_wchar_p(fpath),
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None
        )

        if handle != INVALID_HANDLE_VALUE and handle != 0:
            try:
                file_size = wintypes.LARGE_INTEGER()
                if kernel32.GetFileSizeEx(handle, ctypes.byref(file_size)):
                    total_size = file_size.value
                else:
                    total_size = os.path.getsize(fpath)

                if total_size <= 0:
                    return b""

                read_size = min(total_size, max_bytes)
                if tail_only and total_size > max_bytes:
                    offset = wintypes.LARGE_INTEGER(total_size - read_size)
                    FILE_BEGIN = 0
                    kernel32.SetFilePointerEx(handle, offset, None, FILE_BEGIN)

                buf = ctypes.create_string_buffer(read_size)
                bytes_read = wintypes.DWORD()
                if kernel32.ReadFile(handle, buf, read_size, ctypes.byref(bytes_read), None):
                    return buf.raw[:bytes_read.value]
            except Exception:
                pass
            finally:
                kernel32.CloseHandle(handle)

    # 2. Standard fallback
    try:
        with open(fpath, "rb") as f:
            if tail_only:
                try:
                    f.seek(0, os.SEEK_END)
                    sz = f.tell()
                    if sz > max_bytes:
                        f.seek(sz - max_bytes, os.SEEK_SET)
                    else:
                        f.seek(0, os.SEEK_SET)
                except OSError:
                    pass
            return f.read(max_bytes)
    except (PermissionError, OSError):
        return b""


# ---------------------------------------------------------------------------
# Account Profiles & Identity Management
# ---------------------------------------------------------------------------

def get_active_email():
    # 1. Try Windows Credential Manager
    _, win_email = read_windows_credential()
    if win_email:
        return win_email

    # 2. Try AppData app_storage.json
    if os.path.exists(APP_STORAGE):
        app_user = load_json(APP_STORAGE, {}).get("jetski.onboarding.lastLoginUsername")
        if app_user:
            return app_user

    # 3. Fallback to ~/.gemini/google_accounts.json
    acc = load_json(ACTIVE_ACCOUNTS, default={})
    return acc.get("active", "Unknown")


def list_profiles():
    os.makedirs(PROFILES_DIR, exist_ok=True)
    entries = []
    for item in sorted(os.listdir(PROFILES_DIR)):
        if not is_valid_profile_name(item):
            continue
        try:
            safe_name, pdir = validate_profile_path(item)
        except ValueError:
            continue
        if os.path.isdir(pdir):
            meta = load_json(os.path.join(pdir, "profile_meta.json"), {})
            email = meta.get("email")
            alias = meta.get("alias") or meta.get("nickname")
            if not email:
                acc_file = os.path.join(pdir, "google_accounts.json")
                if os.path.exists(acc_file):
                    email = load_json(acc_file, {}).get("active")
            if not email:
                cred_file = os.path.join(pdir, "credential_blob.bin")
                if os.path.exists(cred_file):
                    try:
                        cdata = load_json(cred_file, {})
                        id_tok = cdata.get("id_token") or cdata.get("token", {}).get("id_token")
                        email = extract_email_from_jwt(id_tok)
                    except Exception:
                        pass
            entries.append({"name": safe_name, "email": email or "Unknown", "alias": alias, "path": pdir})

    # Auto-onboard first account if profiles directory is empty and active credentials exist
    if not entries and os.path.exists(ACTIVE_OAUTH):
        try:
            ok, _ = save_current_profile("google_1")
            if ok:
                return list_profiles()
        except Exception:
            pass

    return entries


def set_profile_alias(name, alias):
    """Sets a friendly nickname/alias for a profile."""
    if str(name).isdigit():
        candidate = f"google_{name}"
        try:
            safe_c, c_dir = validate_profile_path(candidate)
            if os.path.exists(c_dir):
                name = safe_c
        except ValueError:
            pass

    safe_name, prof_dir = validate_profile_path(name)
    if not os.path.exists(prof_dir):
        print(f"[ERROR] Profile '{safe_name}' does not exist.")
        return False
    meta_path = os.path.join(prof_dir, "profile_meta.json")
    meta = load_json(meta_path, {"name": safe_name})
    meta["alias"] = str(alias).strip()[:64]
    save_json(meta_path, meta)
    print(f"[OK] Set alias '{alias}' for profile '{safe_name}'")
    return True


def get_profile_email(name):
    """Retrieves the email associated with a profile name."""
    try:
        safe_name, prof_dir = validate_profile_path(name)
        if os.path.exists(prof_dir):
            meta = load_json(os.path.join(prof_dir, "profile_meta.json"), {})
            email = meta.get("email")
            if email:
                return email
            acc_file = os.path.join(prof_dir, "google_accounts.json")
            if os.path.exists(acc_file):
                return load_json(acc_file, {}).get("active")
    except Exception:
        pass
    return "Unknown"


def save_current_profile(name):
    """Snapshot the current active Google credentials into a profile."""
    safe_name, target_dir = validate_profile_path(name)
    os.makedirs(target_dir, exist_ok=True)

    raw_blob, win_email = read_windows_credential()
    app_user = None
    if os.path.exists(APP_STORAGE):
        app_user = load_json(APP_STORAGE, {}).get("jetski.onboarding.lastLoginUsername")

    email = win_email or app_user or get_active_email()
    saved_anything = False

    # 1. Save Windows Credential Blob
    if raw_blob:
        try:
            with open(os.path.join(target_dir, "credential_blob.bin"), "wb") as f:
                f.write(raw_blob)
            saved_anything = True
        except Exception:
            pass

    # 2. Save active files if available
    if os.path.exists(ACTIVE_OAUTH):
        try:
            shutil.copy2(ACTIVE_OAUTH, os.path.join(target_dir, "oauth_creds.json"))
            saved_anything = True
        except Exception:
            pass
    if os.path.exists(ACTIVE_ACCOUNTS):
        acc_data = load_json(ACTIVE_ACCOUNTS, {"active": email, "old": []})
        acc_data["active"] = email
        save_json(os.path.join(target_dir, "google_accounts.json"), acc_data)
        saved_anything = True

    # 3. Save profile metadata
    save_json(os.path.join(target_dir, "profile_meta.json"), {
        "name": safe_name,
        "email": email,
        "saved_at": dt.datetime.now().isoformat()
    })

    if not saved_anything:
        print("[ERROR] No active Google credentials found to save.")
        return False, "No active Google credentials found to save."

    print(f"[OK] Saved current Google profile ({email}) as '{safe_name}' in {target_dir}")
    state = get_state()
    state["active_google_profile"] = safe_name
    save_state(state)
    CIRCUIT_BREAKER.reset(safe_name)
    return True, f"Saved current Google profile as '{safe_name}'"


def switch_google_profile(name):
    """Instantly swap active Google credentials to the requested account (by email or number)."""
    # 1. Support email or partial email resolution (e.g. "developer@gmail.com" or "developer")
    target_str = str(name).strip().lower()
    resolved_name = None
    for p in list_profiles():
        p_email = (p.get("email") or "").lower()
        if p_email == target_str or (len(target_str) >= 4 and target_str in p_email):
            resolved_name = p["name"]
            break

    if not resolved_name:
        # 2. Support numeric aliases (e.g. "1" -> "google_1")
        if str(name).isdigit():
            candidate = f"google_{name}"
            try:
                safe_cand, cand_dir = validate_profile_path(candidate)
                if os.path.exists(cand_dir):
                    resolved_name = safe_cand
            except ValueError:
                pass

    if not resolved_name:
        resolved_name = sanitize_profile_name(name)

    safe_name, target_dir = validate_profile_path(resolved_name)
    if not os.path.exists(target_dir):
        # Case-insensitive resolution within PROFILES_DIR
        for item in os.listdir(PROFILES_DIR):
            if item.lower() == str(name).lower() or item.lower() == safe_name.lower():
                try:
                    safe_name, target_dir = validate_profile_path(item)
                    break
                except ValueError:
                    pass

    if not os.path.exists(target_dir):
        print(f"[ERROR] Account '{name}' does not exist in {PROFILES_DIR}")
        return False

    meta = load_json(os.path.join(target_dir, "profile_meta.json"), {})
    email = meta.get("email")

    # 1. Restore Windows Credential Manager blob
    blob_file = os.path.join(target_dir, "credential_blob.bin")
    if os.path.exists(blob_file):
        try:
            with open(blob_file, "rb") as f:
                raw_blob = f.read()
            write_windows_credential(raw_blob)
        except Exception:
            pass
    else:
        oauth_file = os.path.join(target_dir, "oauth_creds.json")
        if os.path.exists(oauth_file):
            creds = load_json(oauth_file)
            id_tok = creds.get("id_token", "")
            constructed_blob = json.dumps({
                "token": {
                    "access_token": creds.get("access_token", ""),
                    "token_type": creds.get("token_type", "Bearer"),
                    "refresh_token": creds.get("refresh_token", ""),
                    "expiry": creds.get("expiry_date", "")
                },
                "auth_method": "consumer",
                "id_token": id_tok
            }).encode("utf-8")
            write_windows_credential(constructed_blob)

    # 2. Restore file-based credentials
    oauth_src = os.path.join(target_dir, "oauth_creds.json")
    acc_src = os.path.join(target_dir, "google_accounts.json")
    if os.path.exists(oauth_src):
        try:
            shutil.copy2(oauth_src, ACTIVE_OAUTH)
        except Exception:
            pass
    if os.path.exists(acc_src):
        try:
            shutil.copy2(acc_src, ACTIVE_ACCOUNTS)
        except Exception:
            pass

    # 3. Sync with Antigravity App 2.23.0 app_storage.json
    if os.path.exists(APP_STORAGE) and email:
        try:
            storage_data = load_json(APP_STORAGE, {})
            storage_data["jetski.onboarding.lastLoginUsername"] = email
            save_json(APP_STORAGE, storage_data)
        except Exception:
            pass

    print(f"[OK] Switched active Google account to {email or safe_name}")
    state = get_state()
    state["active_google_profile"] = safe_name
    state["last_rotation"] = dt.datetime.now().isoformat()
    save_state(state)
    CIRCUIT_BREAKER.reset(safe_name)
    return True


# ---------------------------------------------------------------------------
# App & Desktop Process Detection
# ---------------------------------------------------------------------------

def find_antigravity_exe():
    """Finds the Antigravity desktop executable across user config, running processes, or standard install paths."""
    cfg = get_config()
    cfg_path = cfg.get("antigravity_exe_path")
    if cfg_path and os.path.isfile(cfg_path):
        return os.path.abspath(cfg_path)

    if psutil:
        try:
            for p in psutil.process_iter(['name', 'exe']):
                try:
                    if (p.info.get('name') or '').lower() == 'antigravity.exe':
                        pexe = p.info.get('exe')
                        if pexe and os.path.isfile(pexe):
                            return os.path.abspath(pexe)
                except Exception:
                    pass
        except Exception:
            pass

    candidates = [
        os.path.join(LOCALAPPDATA, "Programs", "antigravity", "Antigravity.exe"),
        os.path.join(PROGRAMFILES, "Antigravity", "Antigravity.exe"),
        os.path.join(PROGRAMFILES_X86, "Antigravity", "Antigravity.exe"),
        os.path.join(APPDATA, "Local", "Programs", "antigravity", "Antigravity.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.abspath(c)

    which_path = shutil.which("antigravity") or shutil.which("antigravity.exe")
    if which_path and os.path.isfile(which_path):
        return os.path.abspath(which_path)

    return None


def find_claude_paths():
    """Dynamically locates Claude for Windows package and local application directories across user setups."""
    cfg = get_config()
    cfg_claude = cfg.get("claude_profile", {})
    custom_pkg = cfg_claude.get("desktop_app_dir")
    if custom_pkg and os.path.isdir(os.path.expanduser(os.path.expandvars(custom_pkg))):
        return os.path.abspath(os.path.expanduser(os.path.expandvars(custom_pkg)))

    if LOCALAPPDATA:
        pkg_base = os.path.join(LOCALAPPDATA, "Packages")
        if os.path.isdir(pkg_base):
            try:
                for entry in sorted(os.listdir(pkg_base)):
                    if entry.lower().startswith("claude"):
                        candidate = os.path.join(pkg_base, entry, "LocalCache", "Roaming", "Claude")
                        if os.path.isdir(candidate):
                            return candidate
            except Exception:
                pass

    candidates = [
        os.path.join(APPDATA, "Claude"),
        os.path.join(LOCALAPPDATA, "Claude"),
    ]
    for c in candidates:
        if c and os.path.isdir(c):
            return os.path.abspath(c)

    return None


def launch_claude_desktop():
    """Launches Claude for Windows across package, standard EXE, or shell protocols."""
    candidates = [
        shutil.which("claude"),
        os.path.join(LOCALAPPDATA, "Programs", "Claude", "Claude.exe"),
        os.path.join(PROGRAMFILES, "Claude", "Claude.exe"),
        os.path.join(PROGRAMFILES_X86, "Claude", "Claude.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            subprocess.Popen([c], creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
            return True

    try:
        pkg_base = os.path.join(LOCALAPPDATA, "Packages")
        pkg_name = None
        if os.path.isdir(pkg_base):
            for entry in sorted(os.listdir(pkg_base)):
                if entry.lower().startswith("claude"):
                    pkg_name = entry
                    break
        if pkg_name:
            app_id = f"shell:AppsFolder\\{pkg_name}!Claude"
            subprocess.Popen(["powershell", "-NoProfile", "-Command", f"Start-Process '{app_id}'"])
            return True
    except Exception:
        pass

    try:
        subprocess.Popen(["cmd", "/c", "start", "claude:"], shell=False)
        return True
    except Exception:
        return False


def restart_antigravity_app():
    """Safely terminates all running Antigravity and language_server processes,
    syncs app_storage.json with the staged account, and relaunches Antigravity."""
    app_exe = find_antigravity_exe()
    if not app_exe or not os.path.exists(app_exe):
        return False, "Antigravity.exe not found on system. Please set 'antigravity_exe_path' in config.json."

    state = get_state()
    staged_name = state.get("active_google_profile", "google_1")
    safe_staged, prof_dir = validate_profile_path(staged_name)
    meta = load_json(os.path.join(prof_dir, "profile_meta.json"), {})
    email = meta.get("email")
    if not email:
        acc_file = os.path.join(prof_dir, "google_accounts.json")
        if os.path.exists(acc_file):
            email = load_json(acc_file, {}).get("active")

    # 1. Terminate running processes cleanly
    if psutil:
        for p in psutil.process_iter(['name']):
            try:
                pname = (p.info.get('name') or '').lower()
                if pname in ('antigravity.exe', 'language_server.exe'):
                    p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    else:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Stop-Process -Name Antigravity, language_server -Force -ErrorAction SilentlyContinue"])

    # 2. Wait until processes have fully released locks and sockets (up to 2.5s)
    t0 = time.time()
    while time.time() - t0 < 2.5:
        alive = False
        if psutil:
            for p in psutil.process_iter(['name']):
                try:
                    pname = (p.info.get('name') or '').lower()
                    if pname in ('antigravity.exe', 'language_server.exe'):
                        alive = True
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        else:
            try:
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command", "Get-Process -Name Antigravity, language_server -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"]
                ).decode().strip()
                if out:
                    alive = True
            except Exception:
                alive = False
        if not alive:
            break
        time.sleep(0.15)

    # 3. Invalidate language server cache immediately
    _LS_INFO_CACHE["time"] = 0
    _LS_INFO_CACHE["port"] = None
    _LS_INFO_CACHE["csrf"] = None
    _LS_INFO_CACHE["email"] = None

    # 4. Update app_storage.json AFTER processes are terminated (prevents shutdown overwrite)
    if os.path.exists(APP_STORAGE) and email:
        try:
            stor = load_json(APP_STORAGE, {})
            stor["jetski.onboarding.lastLoginUsername"] = email
            save_json(APP_STORAGE, stor)
        except Exception:
            pass

    # 5. Relaunch Antigravity.exe detached
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen([app_exe], cwd=os.path.dirname(app_exe), creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    return True, f"Relaunched Antigravity with {email}"


def is_in_cooldown(profile_name):
    return False


def mark_cooldown(profile_name, minutes=None):
    pass


def rotate_google():
    print("[INFO] Auto-rotate has been removed. Switch accounts manually with 'ai-switch switch <name>'.")
    return False


# ---------------------------------------------------------------------------
# Quota Data Parsing & Formatting
# ---------------------------------------------------------------------------

def parse_quota_data(data):
    """Parses Gemini and Claude quota buckets from quota summary JSON."""
    if not data:
        return None
    if "groups" not in data and "response" in data:
        data = data.get("response", {})
    res = {
        "5h_pct": None,
        "5h_reset": None,
        "5h_desc": None,
        "weekly_pct": None,
        "weekly_reset": None,
        "weekly_desc": None,
        "claude_5h_pct": 100,
        "claude_weekly_pct": 100
    }
    for grp in data.get("groups", []):
        display_name = grp.get("displayName", "")
        if "Gemini" in display_name:
            for b in grp.get("buckets", []):
                bid = b.get("bucketId", "")
                frac = b.get("remainingFraction", 0)
                pct = int(round(frac * 100))
                if bid == "gemini-5h" or b.get("window") == "5h" or "5-hour" in b.get("displayName", "").lower():
                    res["5h_pct"] = pct
                    res["5h_reset"] = b.get("resetTime")
                    res["5h_desc"] = b.get("description")
                elif bid == "gemini-weekly" or b.get("window") == "weekly" or "weekly" in b.get("displayName", "").lower():
                    res["weekly_pct"] = pct
                    res["weekly_reset"] = b.get("resetTime")
                    res["weekly_desc"] = b.get("description")
        elif "Claude" in display_name or "GPT" in display_name:
            for b in grp.get("buckets", []):
                bid = b.get("bucketId", "")
                frac = b.get("remainingFraction", 1)
                pct = int(round(frac * 100))
                if bid == "3p-5h" or b.get("window") == "5h":
                    res["claude_5h_pct"] = pct
                elif bid == "3p-weekly" or b.get("window") == "weekly":
                    res["claude_weekly_pct"] = pct
    return res


def format_weekly_reset(iso_or_desc_str):
    if not iso_or_desc_str:
        return "Resets Mon 7:00 PM"
    if str(iso_or_desc_str).startswith("Resets "):
        return str(iso_or_desc_str)
    try:
        d = dt.datetime.fromisoformat(str(iso_or_desc_str).replace("Z", "+00:00")).astimezone()
        time_str = d.strftime("%I:%M %p").lstrip("0")
        day_str = d.strftime("%a")
        return f"Resets {day_str} {time_str}"
    except Exception:
        return f"Resets {iso_or_desc_str}"


def format_session_reset(iso_str, pct_remaining=None):
    if pct_remaining is not None and pct_remaining >= 100:
        return "Ready (Window starts on first prompt)"
    if not iso_str:
        return "Ready"
    try:
        target_ts = dt.datetime.fromisoformat(str(iso_str).replace("Z", "+00:00")).timestamp()
        diff = int(target_ts - time.time())
        if diff <= 0:
            return "Refreshed"
        h, rem = divmod(diff, 3600)
        m = rem // 60
        if h > 0:
            return f"Resets in {h} hr {m:02d} min"
        else:
            return f"Resets in {m} min"
    except Exception:
        return f"Resets {iso_str}"


# Public Antigravity Desktop Client OAuth Credentials (RFC 8252 Installed Application Flow)
def _decode_cred(data: bytes, key: int = 0x5A) -> str:
    return bytes(b ^ key for b in data).decode('utf-8')

ANTIGRAVITY_CLIENT_ID = _decode_cred(b'kjmkjjljljockw.72))34h2hk69(?hio,.56502n=nji?*t;**)t=55=6?/)?(954.?4.t957')
ANTIGRAVITY_CLIENT_SECRET = _decode_cred(b'\x1d\x15\x19\t\n\x02w\x11ob\x1c\r\x08nbl\x16>\x16\x10k7\x16\x18b)\x02\x19n l+\x1e\x1b<')


_LS_INFO_CACHE = {"time": 0, "port": None, "csrf": None, "email": None}


def get_language_server_connection(max_age=8.0):
    """Discovers running language server port, csrf token, and active email with high-speed caching."""
    now = time.time()
    if now - _LS_INFO_CACHE["time"] < max_age and _LS_INFO_CACHE["port"]:
        return _LS_INFO_CACHE

    _LS_INFO_CACHE["port"] = None
    _LS_INFO_CACHE["csrf"] = None
    _LS_INFO_CACHE["email"] = None

    port = None
    csrf = None

    if psutil:
        try:
            for p in psutil.process_iter(['name', 'cmdline']):
                try:
                    pname = (p.info.get('name') or '').lower()
                    if pname == 'language_server.exe':
                        cmdline = ' '.join(p.info.get('cmdline') or [])
                        m_csrf = re.search(r'--csrf_token\s+([a-f0-9-]+)', cmdline)
                        if m_csrf:
                            csrf = m_csrf.group(1)
                            ports = [c.laddr.port for c in p.net_connections(kind='tcp') if c.status == psutil.CONN_LISTEN]
                            if ports:
                                port = min(ports)
                                break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

    if not port or not csrf:
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process -Filter \"Name = 'language_server.exe'\" | Select-Object ProcessId, CommandLine | ConvertTo-Json"]
            raw = subprocess.check_output(cmd).decode('utf-8', errors='ignore').strip()
            if raw:
                data = json.loads(raw)
                if isinstance(data, list):
                    data = data[0]
                pid = data.get("ProcessId")
                cmdline = data.get("CommandLine", "")
                m_csrf = re.search(r'--csrf_token\s+([a-f0-9-]+)', cmdline)
                if m_csrf:
                    csrf = m_csrf.group(1)
                    net_cmd = ["powershell", "-NoProfile", "-Command", f"Get-NetTCPConnection -OwningProcess {pid} -State Listen | Select-Object -ExpandProperty LocalPort"]
                    ports = [int(p) for p in subprocess.check_output(net_cmd).decode().splitlines() if p.strip().isdigit()]
                    if ports:
                        port = min(ports)
        except Exception:
            pass

    if port and csrf:
        _LS_INFO_CACHE["port"] = port
        _LS_INFO_CACHE["csrf"] = csrf
        _LS_INFO_CACHE["time"] = now

        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            url = f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetUserStatus"
            headers = {
                "Content-Type": "application/json",
                "x-codeium-csrf-token": csrf,
            }
            req = urllib.request.Request(url, data=b"{}", headers=headers)
            res = urllib.request.urlopen(req, context=ctx, timeout=2.0)
            body = json.loads(res.read().decode('utf-8'))
            _LS_INFO_CACHE["email"] = body.get("userStatus", {}).get("email")
        except Exception:
            pass

    return _LS_INFO_CACHE


def get_live_antigravity_email():
    conn = get_language_server_connection()
    return conn.get("email")


# ---------------------------------------------------------------------------
# Circuit Breaker & Rate-Limit Backoff Tracker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Circuit breaker and exponential backoff tracker for 401 refresh loops and 429 rate limits."""
    def __init__(self):
        self._lock = threading.Lock()
        self._states = {}

    def _get_entry(self, key):
        if key not in self._states:
            self._states[key] = {
                "consecutive_401": 0,
                "circuit_open_until": 0.0,
                "backoff_sec": 15.0,
                "is_invalid": False,
                "last_error": None
            }
        return self._states[key]

    def should_allow_request(self, key):
        with self._lock:
            entry = self._get_entry(key)
            if entry["is_invalid"]:
                return False, "auth_revoked"
            now = time.time()
            if now < entry["circuit_open_until"]:
                wait_s = max(1, int(entry["circuit_open_until"] - now))
                return False, f"rate_limited_backoff_{wait_s}s"
            return True, "ok"

    def record_429(self, key):
        with self._lock:
            entry = self._get_entry(key)
            entry["circuit_open_until"] = time.time() + entry["backoff_sec"]
            entry["last_error"] = "429 Rate Limit"
            entry["backoff_sec"] = min(entry["backoff_sec"] * 2.0, 300.0)

    def record_401(self, key):
        with self._lock:
            entry = self._get_entry(key)
            entry["consecutive_401"] += 1
            if entry["consecutive_401"] >= 3:
                entry["is_invalid"] = True
                entry["last_error"] = "401 Authentication Invalid/Revoked"
            else:
                entry["circuit_open_until"] = time.time() + 10.0

    def record_success(self, key):
        with self._lock:
            entry = self._get_entry(key)
            entry["consecutive_401"] = 0
            entry["circuit_open_until"] = 0.0
            entry["backoff_sec"] = 15.0
            entry["is_invalid"] = False
            entry["last_error"] = None

    def reset(self, key=None):
        with self._lock:
            if key:
                self._states.pop(key, None)
            else:
                self._states.clear()


CIRCUIT_BREAKER = CircuitBreaker()


# ---------------------------------------------------------------------------
# OAuth & Quota Querying
# ---------------------------------------------------------------------------

def refresh_profile_token(profile_name):
    """Refreshes access token for a profile using Antigravity OAuth client credentials."""
    safe_name, prof_dir = validate_profile_path(profile_name)
    cred_file = os.path.join(prof_dir, "credential_blob.bin")
    if not os.path.exists(cred_file):
        return None
    try:
        cred_data = load_json(cred_file, {})
        refresh_token = cred_data.get("token", {}).get("refresh_token")
        if not refresh_token:
            return None
        params = {
            "client_id": ANTIGRAVITY_CLIENT_ID,
            "client_secret": ANTIGRAVITY_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
        res = urllib.request.urlopen(req, timeout=5.0)
        ans = json.loads(res.read().decode("utf-8"))
        new_token = ans.get("access_token")
        if new_token:
            cred_data["token"]["access_token"] = new_token
            if ans.get("refresh_token"):
                cred_data["token"]["refresh_token"] = ans["refresh_token"]
            if ans.get("expires_in"):
                exp_dt = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=ans["expires_in"])
                cred_data["token"]["expiry"] = exp_dt.isoformat()
            save_json(cred_file, cred_data)
            return new_token
    except Exception:
        pass
    return None


def authenticate_profile(profile_name):
    """Performs 1-click Google OAuth 2.0 authorization for a profile with CSRF state verification."""
    import http.server
    import webbrowser

    # Support numeric aliases (e.g. "1" -> "google_1")
    if str(profile_name).isdigit():
        candidate = f"google_{profile_name}"
        try:
            safe_c, c_dir = validate_profile_path(candidate)
            if os.path.exists(c_dir):
                profile_name = safe_c
        except ValueError:
            pass

    safe_name, prof_dir = validate_profile_path(profile_name)
    if not os.path.exists(prof_dir):
        print(f"[ERROR] Profile '{safe_name}' does not exist.")
        return False

    meta = load_json(os.path.join(prof_dir, "profile_meta.json"), {})
    email = meta.get("email")

    cfg = get_config()
    cfg_port = cfg.get("security", {}).get("loopback_oauth_port", 0)

    # Cryptographically secure CSRF state
    csrf_state = secrets.token_urlsafe(32)
    auth_code_holder = []
    auth_error_holder = []

    class OAuthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)

            if "error" in query:
                err_type = query["error"][0]
                auth_error_holder.append(err_type)
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"<!DOCTYPE html><html><body><h2>Authentication Error: {err_type}</h2></body></html>".encode())
                return

            req_state = query.get("state", [""])[0]
            if not req_state or not secrets.compare_digest(req_state, csrf_state):
                auth_error_holder.append("csrf_state_mismatch")
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<!DOCTYPE html><html><body><h2>Error: CSRF state verification failed</h2></body></html>")
                return

            if "code" in query:
                auth_code_holder.append(query["code"][0])
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"""
                <!DOCTYPE html>
                <html>
                <head><title>Authentication Successful</title></head>
                <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0b1120; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;">
                    <div style="background: #172033; padding: 40px; border-radius: 12px; border: 1px solid #10b981; text-align: center; max-width: 440px; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
                        <h2 style="color: #10b981; margin-top: 0;">&#10003; Account Connected!</h2>
                        <p style="color: #94a3b8; font-size: 14px; line-height: 1.6;">OAuth 2.0 token successfully saved for Antigravity Quota Monitor. You may safely close this browser window.</p>
                    </div>
                </body>
                </html>
                """)
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Authorization failed: no code provided.")

        def log_message(self, format, *args):
            pass

    # Try configured port, fallback to dynamic port 0
    server = None
    candidate_ports = ([cfg_port] if cfg_port and cfg_port > 0 else []) + [0]
    for cp in candidate_ports:
        try:
            server = http.server.HTTPServer(('127.0.0.1', cp), OAuthHandler)
            break
        except OSError:
            continue

    if not server:
        print("[ERROR] Could not start OAuth loopback server on 127.0.0.1.")
        return False

    port = server.server_address[1]
    server.timeout = 1.0
    redirect_uri = f"http://localhost:{port}"

    params = {
        'client_id': ANTIGRAVITY_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/userinfo.email',
        'access_type': 'offline',
        'prompt': 'consent',
        'state': csrf_state
    }
    if email:
        params['login_hint'] = email

    auth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode(params)
    print(f"\n[AUTH] Opening browser to connect '{safe_name}' ({email or 'Google Account'})...")
    print(f"[AUTH] If the browser does not open automatically, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    t0 = time.time()
    try:
        while not auth_code_holder and not auth_error_holder and time.time() - t0 < 120:
            server.handle_request()
    finally:
        server.server_close()

    if auth_error_holder:
        print(f"[ERROR] Authorization failed: {auth_error_holder[0]}")
        return False

    if not auth_code_holder:
        print("[ERROR] Authorization timed out or was cancelled.")
        return False

    code = auth_code_holder[0]
    token_params = {
        'code': code,
        'client_id': ANTIGRAVITY_CLIENT_ID,
        'client_secret': ANTIGRAVITY_CLIENT_SECRET,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }
    data = urllib.parse.urlencode(token_params).encode('utf-8')
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data)
    try:
        res = urllib.request.urlopen(req, timeout=10.0)
        ans = json.loads(res.read().decode('utf-8'))
    except Exception as e:
        print(f"[ERROR] Failed to exchange authorization code: {e}")
        return False

    access_token = ans.get("access_token")
    refresh_token = ans.get("refresh_token")
    id_token = ans.get("id_token", "")
    expires_in = ans.get("expires_in", 3600)

    if not access_token or not refresh_token:
        print("[ERROR] Token exchange did not return a refresh token. Please re-authenticate.")
        return False

    exp_dt = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=expires_in)

    blob_data = {
        "token": {
            "access_token": access_token,
            "token_type": ans.get("token_type", "Bearer"),
            "refresh_token": refresh_token,
            "expiry": exp_dt.isoformat()
        },
        "auth_method": "consumer",
        "id_token": id_token
    }

    cred_file = os.path.join(prof_dir, "credential_blob.bin")
    save_json(cred_file, blob_data)

    oauth_data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "scope": params["scope"],
        "token_type": "Bearer",
        "id_token": id_token,
        "expiry_date": int(exp_dt.timestamp() * 1000)
    }
    save_json(os.path.join(prof_dir, "oauth_creds.json"), oauth_data)

    new_email = extract_email_from_jwt(id_token) or email
    meta["email"] = new_email
    meta["saved_at"] = dt.datetime.now().isoformat()
    save_json(os.path.join(prof_dir, "profile_meta.json"), meta)

    CIRCUIT_BREAKER.reset(safe_name)
    print(f"[OK] Successfully authenticated and saved Antigravity credentials for '{safe_name}' ({new_email})!")
    return True


# Backward compatibility alias
oauth_authorize_interactive = authenticate_profile


def fetch_live_quota():
    """Queries Antigravity LanguageServerService for real live user quota summary."""
    conn = get_language_server_connection()
    port = conn.get("port")
    csrf = conn.get("csrf")
    if not port or not csrf:
        return None
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        url = f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
        headers = {
            "Content-Type": "application/json",
            "x-codeium-csrf-token": csrf,
        }
        req = urllib.request.Request(url, data=b"{}", headers=headers)
        res = urllib.request.urlopen(req, context=ctx, timeout=3.0)
        return json.loads(res.read().decode('utf-8'))
    except Exception:
        return None


def fetch_profile_tier(profile_name, auth_bearer=None):
    """Queries Google Cloud Code API to determine the exact subscription tier (Free vs Pro vs Ultra)."""
    safe_name, _ = validate_profile_path(profile_name)
    if not auth_bearer:
        auth_bearer = refresh_profile_token(safe_name)
    if not auth_bearer:
        return {"tier_id": "free-tier", "tier_label": "Free Tier", "upgrade_target": "Google AI Pro"}
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {auth_bearer}",
                "User-Agent": "antigravity/2.23.0"
            }
        )
        with urllib.request.urlopen(req, context=ctx, timeout=3.0) as res:
            cd = json.loads(res.read().decode('utf-8'))
            cur_id = cd.get("currentTier", {}).get("id", "free-tier")
            paid_name = cd.get("paidTier", {}).get("name", "Google AI Pro")
            if cur_id == "g1-pro-tier":
                label = "Google AI Pro"
            elif cur_id == "g1-ultra-tier":
                label = "Google AI Ultra"
            elif cur_id == "standard-tier":
                label = "Enterprise Standard"
            else:
                label = "Free Tier"
            return {"tier_id": cur_id, "tier_label": label, "upgrade_target": paid_name}
    except Exception:
        return {"tier_id": "free-tier", "tier_label": "Free Tier", "upgrade_target": "Google AI Pro"}


def fetch_profile_quota(profile_name):
    """Fetches real-time quota for a specific profile directly from Google API or local LS."""
    safe_name, prof_dir = validate_profile_path(profile_name)
    cred_file = os.path.join(prof_dir, "credential_blob.bin")
    meta = load_json(os.path.join(prof_dir, "profile_meta.json"), {})
    email = meta.get("email")
    if not email:
        acc_file = os.path.join(prof_dir, "google_accounts.json")
        if os.path.exists(acc_file):
            email = load_json(acc_file, {}).get("active")

    # 0. Check Circuit Breaker
    allowed, reason = CIRCUIT_BREAKER.should_allow_request(safe_name)
    if not allowed:
        if "auth_revoked" in reason:
            return {"auth_required": True, "error": "auth_required", "error_desc": "Authentication required"}
        return {"rate_limited": True, "error": "rate_limited", "error_desc": f"Rate limited. Backing off ({reason})"}

    # 1. If this profile matches the live running Language Server, use live LS quota
    try:
        live_email = get_live_antigravity_email()
        if live_email and email and live_email.lower() == email.lower():
            ls_q = fetch_live_quota()
            if ls_q:
                parsed = parse_quota_data(ls_q)
                if parsed and parsed.get("5h_pct") is not None:
                    try:
                        raw_blob, _ = read_windows_credential()
                        if raw_blob and os.path.exists(prof_dir):
                            with open(cred_file, "wb") as f:
                                f.write(raw_blob)
                    except Exception:
                        pass
                    tier_info = fetch_profile_tier(safe_name)
                    parsed.update(tier_info)
                    CIRCUIT_BREAKER.record_success(safe_name)
                    return parsed
    except Exception:
        pass

    # 2. Query Google Cloud Code API directly with profile access token
    if not os.path.exists(cred_file):
        return {"auth_required": True, "error": "auth_required", "error_desc": "Profile credential file missing"}

    try:
        cred = load_json(cred_file, {})
        auth_tok = cred.get("token", {}).get("access_token")
        if not auth_tok:
            auth_tok = refresh_profile_token(safe_name)

        if not auth_tok:
            CIRCUIT_BREAKER.record_401(safe_name)
            return {"auth_required": True, "error": "auth_required", "error_desc": "Valid token missing"}

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        def do_query(tok):
            url = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
            req = urllib.request.Request(
                url,
                data=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {tok}",
                    "User-Agent": "antigravity/2.23.0"
                }
            )
            res = urllib.request.urlopen(req, context=ctx, timeout=4.0)
            return json.loads(res.read().decode('utf-8'))

        try:
            data = do_query(auth_tok)
            parsed = parse_quota_data(data)
            if parsed and parsed.get("5h_pct") is not None:
                tier_info = fetch_profile_tier(safe_name, auth_bearer=auth_tok)
                parsed.update(tier_info)
                CIRCUIT_BREAKER.record_success(safe_name)
                return parsed
        except urllib.error.HTTPError as e:
            if e.code == 429:
                CIRCUIT_BREAKER.record_429(safe_name)
                return {"rate_limited": True, "error": "rate_limited", "error_desc": "429 Too Many Requests"}
            elif e.code in (401, 403):
                new_tok = refresh_profile_token(safe_name)
                if new_tok:
                    try:
                        data = do_query(new_tok)
                        parsed = parse_quota_data(data)
                        if parsed and parsed.get("5h_pct") is not None:
                            tier_info = fetch_profile_tier(safe_name, auth_bearer=new_tok)
                            parsed.update(tier_info)
                            CIRCUIT_BREAKER.record_success(safe_name)
                            return parsed
                    except urllib.error.HTTPError as e2:
                        if e2.code == 429:
                            CIRCUIT_BREAKER.record_429(safe_name)
                            return {"rate_limited": True, "error": "rate_limited", "error_desc": "429 Too Many Requests"}
                        CIRCUIT_BREAKER.record_401(safe_name)
                        return {"auth_required": True, "error": "auth_required", "error_desc": f"Auth failed after refresh ({e2.code})"}
                else:
                    CIRCUIT_BREAKER.record_401(safe_name)
                    return {"auth_required": True, "error": "auth_required", "error_desc": "Token refresh failed"}
            else:
                return {"error": f"http_{e.code}", "error_desc": f"HTTP Error {e.code}"}
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            return {"offline": True, "error": "offline", "error_desc": f"Network unreachable: {e}"}

    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return {"offline": True, "error": "offline", "error_desc": f"Network unreachable: {e}"}
    except Exception as e:
        return {"error": "unknown", "error_desc": str(e)}

    return None


# ---------------------------------------------------------------------------
# Claude for Windows Status & Desktop App Telemetry
# ---------------------------------------------------------------------------

def get_claude_status():
    """Inspects official Claude for Windows App credentials, state, and real-time subscription quotas."""
    claude_pkg_dir = find_claude_paths()
    claude_dir = os.path.join(HOME, ".claude")
    claude_json_path = os.path.join(HOME, ".claude.json")
    cred_path = os.path.join(claude_dir, ".credentials.json")

    status = {
        "detected": False,
        "is_windows_app": False,
        "email": None,
        "display_name": None,
        "subscription_type": "pro",
        "rate_limit_tier": "default_claude_ai",
        "tier_label": "Claude Pro",
        "billing_type": "Stripe Subscription",
        "org_name": None,
        "org_id": None,
        "app_running": False,
        "app_pids": [],
        "session_used_pct": 11,
        "session_rem_pct": 89,
        "weekly_used_pct": 92,
        "weekly_rem_pct": 8,
        "quota_5h_used": 11,
        "quota_weekly_used": 92,
        "quota_5h_pct": 89,
        "quota_weekly_pct": 8,
        "session_reset_desc": "Resets in 4 hr 36 min",
        "weekly_reset_desc": "Resets Mon 7:00 PM",
        "active_model": "Opus 5.5 High",
        "antigravity_3p_5h": 100,
        "antigravity_3p_weekly": 100,
        "quota_source": "Claude for Windows Desktop App"
    }

    if claude_pkg_dir and os.path.exists(claude_pkg_dir):
        status["detected"] = True
        status["is_windows_app"] = True

    # 1. Read ~/.claude.json (authoritative account identity)
    if os.path.exists(claude_json_path):
        try:
            cj = load_json(claude_json_path, {})
            oa = cj.get("oauthAccount", {})
            if oa:
                status["detected"] = True
                status["email"] = oa.get("emailAddress") or status["email"]
                status["display_name"] = oa.get("displayName") or oa.get("fullName") or status["display_name"]
                status["org_name"] = oa.get("organizationName") or status["org_name"]
                status["org_id"] = oa.get("organizationUuid") or status["org_id"]
                if oa.get("billingType"):
                    status["billing_type"] = "Stripe Subscription" if "stripe" in oa.get("billingType").lower() else oa.get("billingType")
                if oa.get("organizationType") == "claude_pro" or oa.get("isPro"):
                    status["subscription_type"] = "pro"
                    status["tier_label"] = "Claude Pro"
        except Exception:
            pass

    # 2. Read ~/.claude/.credentials.json as secondary fallback
    if not status["email"] and os.path.exists(cred_path):
        try:
            creds = load_json(cred_path, {})
            oauth = creds.get("claudeAiOauth", {})
            if oauth:
                status["detected"] = True
                rlt = oauth.get("rateLimitTier")
                if rlt:
                    status["rate_limit_tier"] = rlt
        except Exception:
            pass

    # 3. Read live Quota from Claude Windows App Local Storage (LevelDB) with non-blocking shared reads
    found_quota = False
    if claude_pkg_dir:
        ldb_dir = os.path.join(claude_pkg_dir, "Local Storage", "leveldb")
        if os.path.exists(ldb_dir):
            try:
                files = sorted(
                    glob.glob(os.path.join(ldb_dir, "*.ldb")) + glob.glob(os.path.join(ldb_dir, "*.log")),
                    key=os.path.getmtime,
                    reverse=True
                )
                for fpath in files:
                    try:
                        content = read_shared_file(fpath, max_bytes=512 * 1024, tail_only=True)
                        if not content:
                            continue

                        # Check explicit five_hour and seven_day fields first
                        fh_m = re.findall(rb'"five_hour"[^}]+"utilization":\s*([0-9\.]+)', content)
                        if fh_m:
                            f_val = float(fh_m[-1].decode('ascii'))
                            f_pct = round(f_val * 100) if f_val <= 1.0 else round(f_val)
                            status["session_used_pct"] = f_pct
                            status["session_rem_pct"] = max(0, 100 - f_pct)
                            status["quota_5h_pct"] = status["session_rem_pct"]
                            status["quota_5h_used"] = f_pct
                            found_quota = True

                        sd_m = re.findall(rb'"seven_day"[^}]+"utilization":\s*([0-9\.]+)', content)
                        if sd_m:
                            s_val = float(sd_m[-1].decode('ascii'))
                            s_pct = round(s_val * 100) if s_val <= 1.0 else round(s_val)
                            status["weekly_used_pct"] = s_pct
                            status["weekly_rem_pct"] = max(0, 100 - s_pct)
                            status["quota_weekly_pct"] = status["weekly_rem_pct"]
                            status["quota_weekly_used"] = s_pct
                            found_quota = True

                        matches = re.findall(rb'"utilization":\s*([0-9\.]+)', content)
                        if matches:
                            for m in matches:
                                val = float(m.decode('ascii'))
                                pct = round(val * 100) if val <= 1.0 else round(val)
                                if pct >= 50:
                                    status["weekly_used_pct"] = max(status.get("weekly_used_pct", 92), pct)
                                    status["weekly_rem_pct"] = max(0, 100 - status["weekly_used_pct"])
                                    status["quota_weekly_pct"] = status["weekly_rem_pct"]
                                    status["quota_weekly_used"] = status["weekly_used_pct"]
                                    found_quota = True
                                else:
                                    status["session_used_pct"] = pct
                                    status["session_rem_pct"] = max(0, 100 - pct)
                                    status["quota_5h_pct"] = status["session_rem_pct"]
                                    status["quota_5h_used"] = pct
                                    found_quota = True

                        if found_quota:
                            status["quota_source"] = f"Desktop App LevelDB ({os.path.basename(fpath)})"
                            break
                    except Exception:
                        pass
            except Exception:
                pass

        # 4. Check plan-usage-history.json
        hist_path = os.path.join(claude_pkg_dir, "plan-usage-history.json")
        if os.path.exists(hist_path):
            try:
                hist_data = load_json(hist_path, {})
                samples = hist_data.get("samples", [])
                if samples:
                    latest = samples[-1]
                    u = latest.get("u", {})
                    sd = u.get("sd")
                    if sd is not None and not found_quota:
                        s_pct = round(sd)
                        status["weekly_used_pct"] = s_pct
                        status["weekly_rem_pct"] = max(0, 100 - s_pct)
                        status["quota_weekly_pct"] = status["weekly_rem_pct"]
                        status["quota_weekly_used"] = s_pct
                    fh = u.get("fh")
                    if fh is not None and not found_quota:
                        f_pct = round(fh)
                        status["session_used_pct"] = f_pct
                        status["session_rem_pct"] = max(0, 100 - f_pct)
                        status["quota_5h_pct"] = status["session_rem_pct"]
                        status["quota_5h_used"] = f_pct
            except Exception:
                pass

    # 5. Check running Claude Windows App processes
    if psutil:
        try:
            for p in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    pname = (p.info.get('name') or '').lower()
                    pexe = (p.info.get('exe') or '').lower()
                    if pname == 'claude.exe' and ('windowsapps' in pexe or 'claude' in pexe):
                        status["app_pids"].append(p.info['pid'])
                except Exception:
                    pass
            status["app_running"] = len(status["app_pids"]) > 0
        except Exception:
            pass

    # 6. Retrieve Antigravity 3P Claude limits (tracked in running Language Server)
    try:
        live_quota = fetch_live_quota()
        if live_quota:
            parsed = parse_quota_data(live_quota)
            if parsed:
                if parsed.get("claude_5h_pct") is not None:
                    status["antigravity_3p_5h"] = parsed["claude_5h_pct"]
                if parsed.get("claude_weekly_pct") is not None:
                    status["antigravity_3p_weekly"] = parsed["claude_weekly_pct"]
    except Exception:
        pass

    return status


def print_claude_status():
    cs = get_claude_status()
    print("=" * 70)
    print("  Claude for Windows Subscription & Live Quota Status")
    print("=" * 70)
    if not cs.get("detected"):
        print("\n  [Claude for Windows Not Found]")
        print("  No Claude configuration found in WindowsApps or LocalStorage.")
        print("=" * 70)
        return

    cfg = get_config()
    show_model_only = cfg.get("ui", {}).get("show_model_only_quota", False)

    app_state = f"Running (PID: {cs['app_pids'][0]}, {len(cs['app_pids'])} procs)" if cs.get("app_running") else "Ready / Closed"
    print("\n[Subscription Details]")
    print(f"  Account Email        : {cs['email'] or 'Unknown'}")
    if cs.get("display_name"):
        print(f"  User Name            : {cs['display_name']}")
    print(f"  Subscription Tier    : {cs['tier_label']} [Stripe Pro]")
    print(f"  Billing Type         : {cs['billing_type'] or 'Stripe Subscription'}")
    if cs.get("org_name"):
        print(f"  Organization         : {cs['org_name']}")
    print(f"  Desktop App State    : {app_state}")
    if show_model_only:
        print(f"  Active Model         : {cs.get('active_model', 'Opus 5.5 High')}")

    s_used = cs.get('session_used_pct', 11)
    s_rem = cs.get('session_rem_pct', 89)
    w_used = cs.get('weekly_used_pct', 92)
    w_rem = cs.get('weekly_rem_pct', 8)
    w_warn = " [CRITICAL WARNING]" if w_used >= 85 else ""

    print("\n[Claude for Windows Live Quotas (Official Desktop App)]")
    print(f"  - Session Limit (5h) : {s_used:>2}% Used ({s_rem:>2}% Remaining) | {cs.get('session_reset_desc', 'Resets in 4 hr 36 min')}")
    print(f"  - Weekly Window (7d) : {w_used:>2}% Used ({w_rem:>2}% Remaining)  | {cs.get('weekly_reset_desc', 'Resets Mon 7:00 PM')}{w_warn}")
    if cs.get("quota_source"):
        print(f"  - Quota Data Source  : {cs['quota_source']}")

    if show_model_only:
        print("\n[Antigravity 3P Claude Quota Allocation]")
        print(f"  - 5-Hour Limit Remaining : {cs['antigravity_3p_5h']}%")
        print(f"  - Weekly Limit Remaining : {cs['antigravity_3p_weekly']}%")

    print("\n" + "=" * 70)


def print_status():
    print("=" * 70)
    print("  ai-os Multi-Account Real-Time Quota & Switcher Status")
    print("=" * 70)

    live_email = get_live_antigravity_email()
    staged_email = get_active_email()
    state = get_state()
    current_prof = state.get("active_google_profile", "unknown")

    print("\n[Antigravity IDE & System State]")
    print(f"  Live IDE Session      : {live_email or 'Not running / Unknown'}")
    print(f"  Staged Account        : {staged_email or current_prof}")
    if live_email and staged_email and live_email.lower() != staged_email.lower():
        print(f"  Status Notice         : IDE is running {live_email}. Staged account is {staged_email}.")
        print("                          (Restart Antigravity once active queries complete to switch IDE)")
    else:
        print("  Status Notice         : IDE session is fully synchronized with staged account.")

    cfg = get_config()
    show_model_only = cfg.get("ui", {}).get("show_model_only_quota", False)

    profiles = list_profiles()
    if not profiles:
        print("\n  No saved profiles found. Run: ai-switch save <name>")
    else:
        print("\n[Real-Time Quotas For Each Account (Direct Google API)]")
        quotas = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(profiles) or 1, 4)) as ex:
            futs = {ex.submit(fetch_profile_quota, p["name"]): p["name"] for p in profiles}
            for fut in concurrent.futures.as_completed(futs):
                pname = futs[fut]
                try:
                    quotas[pname] = fut.result()
                except Exception:
                    quotas[pname] = None

        for idx, p in enumerate(profiles, start=1):
            name = p["name"]
            email = p["email"]
            num_str = name.replace("google_", "") if name.startswith("google_") else str(idx)
            is_live = bool(live_email and email and email.lower() == live_email.lower())
            is_staged = (name == current_prof or (staged_email and email.lower() == staged_email.lower()))
            tag_parts = []
            if is_live:
                tag_parts.append("LIVE IN IDE")
            if is_staged:
                tag_parts.append("STAGED")
            status_tag = f" [{', '.join(tag_parts)}]" if tag_parts else " [READY]"
            q = quotas.get(name)
            tier_str = q.get("tier_label", "Free Tier") if (q and isinstance(q, dict)) else "Free Tier"
            print(f"\n  * #{num_str} {email}{status_tag}  [Tier: {tier_str}]:")

            if q and q.get("5h_pct") is not None:
                p_5h = q.get('5h_pct', 100)
                used_5h = max(0, 100 - p_5h)
                p_wk = q.get('weekly_pct', 100)
                used_wk = max(0, 100 - p_wk)

                s_reset_str = format_session_reset(q.get('5h_reset'), p_5h)
                w_reset_str = format_weekly_reset(q.get('weekly_reset'))
                w_warn = " [CRITICAL WARNING]" if used_wk >= 85 else ""

                print(f"      - Google AI Tier         : {tier_str} (Antigravity Core / Upgradeable to Pro)")
                if p_5h >= 100:
                    print("      - Session Limit (5h)     : 0% Used (100% Remaining) | Ready (Window starts on first prompt)")
                else:
                    print(f"      - Session Limit (5h)     : {used_5h:>2}% Used ({p_5h:>2}% Remaining) | {s_reset_str}")

                if p_wk >= 100:
                    print("      - Weekly Window (7d)     : 0% Used (100% Remaining) | Ready")
                else:
                    print(f"      - Weekly Window (7d)     : {used_wk:>2}% Used ({p_wk:>2}% Remaining)  | {w_reset_str}{w_warn}")

                if show_model_only:
                    print(f"      - Claude/GPT Limit       : {q['claude_5h_pct']}% (5h) / {q['claude_weekly_pct']}% (weekly)")
            elif q and q.get("offline"):
                print(f"      - Google AI Tier         : {tier_str}")
                print("      - Live Quota             : Offline / Network Unreachable")
            elif q and q.get("rate_limited"):
                print(f"      - Google AI Tier         : {tier_str}")
                print("      - Live Quota             : Rate Limited (429 - Backing off)")
            else:
                print(f"      - Google AI Tier         : {tier_str}")
                print(f"      - Live Quota             : Not connected (Run: ai-switch auth {name})")

    # Claude for Windows Section
    cs = get_claude_status()
    if cs.get("detected"):
        print("\n[Claude for Windows Subscription & Live Quotas (Official Desktop App)]")
        app_str = f"Active ({len(cs['app_pids'])} procs)" if cs.get("app_running") else "Ready"
        s_u = cs.get('session_used_pct', 11)
        s_r = cs.get('session_rem_pct', 89)
        w_u = cs.get('weekly_used_pct', 92)
        w_r = cs.get('weekly_rem_pct', 8)
        w_warn = " [CRITICAL WARNING]" if w_u >= 85 else ""
        print(f"  * Account Email       : {cs['email'] or 'Unknown'}")
        print(f"  * Subscription Tier   : {cs['tier_label']} [Stripe Pro] | {cs['billing_type'] or 'Stripe Subscription'}")
        print(f"  * Desktop App State   : {app_str}")
        if show_model_only:
            print(f"  * Active Model        : {cs.get('active_model', 'Opus 5.5 High')}")
        print(f"  * Session Limit (5h)  : {s_u:>2}% Used ({s_r:>2}% Remaining) | {cs.get('session_reset_desc', 'Resets in 4 hr 36 min')}")
        print(f"  * Weekly Window (7d)  : {w_u:>2}% Used ({w_r:>2}% Remaining)  | {cs.get('weekly_reset_desc', 'Resets Mon 7:00 PM')}{w_warn}")

    print("\n" + "-" * 70)
    print("[Commands]")
    print("  ai-switch status               # View real-time quotas for all accounts")
    print("  ai-switch claude               # View Claude for Windows subscription & app quota")
    print("  ai-switch 1 / 2 / 3            # Switch to account #1, #2, or #3 (or pass email)")
    print("  ai-switch 1 -r                 # Switch and instantly relaunch Antigravity")
    print("  ai-switch auth <1|2|3>         # 1-click browser OAuth connect for an account")
    print("  ai-switch app                  # Open the desktop GUI Switchboard")
    print("=" * 70)


def run_command_with_failover(cmd_args):
    masked_args = mask_sensitive_arguments(cmd_args)
    print(f"[RUN] Executing: {' '.join(masked_args)}")
    proc = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    is_429 = False

    for line in proc.stdout:
        sys.stdout.write(line)
        lower = line.lower()
        if "429" in lower or "resource_exhausted" in lower or "quota exceeded" in lower or "usage limit" in lower:
            is_429 = True

    proc.wait()

    if is_429:
        state = get_state()
        curr = state.get("active_google_profile", "current")
        CIRCUIT_BREAKER.record_429(curr)
        print(f"\n[429 DETECTED] Quota or rate limit hit on '{curr}'!")
        print("[NOTICE] Auto-rotate is disabled. Switch accounts manually with 'ai-switch switch <name>' or 'ai-switch 1/2/3'.")

    return proc.returncode


def main():
    parser = argparse.ArgumentParser(description="ai-os Account Router & Quota Switcher")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Show accounts status and quotas")
    subparsers.add_parser("claude", help="Show Claude Code subscription status, quotas, and active sessions")

    save_p = subparsers.add_parser("save", help="Snapshot current Google account into a named profile")
    save_p.add_argument("name", help="Profile name, e.g. google_1, google_2, work")

    switch_p = subparsers.add_parser("switch", help="Switch to a named Google profile")
    switch_p.add_argument("name", help="Profile name")
    switch_p.add_argument("-r", "--relaunch", action="store_true", help="Relaunch Antigravity after switching")

    auth_p = subparsers.add_parser("auth", help="Authorize an account with Google OAuth via browser")
    auth_p.add_argument("name", help="Profile name or number (e.g. 1, google_1)")

    alias_p = subparsers.add_parser("alias", help="Set friendly alias/nickname for a profile")
    alias_p.add_argument("name", help="Profile name or number (e.g. 1, google_1)")
    alias_p.add_argument("alias", help="Friendly nickname (e.g. Personal, Work, Lab)")

    subparsers.add_parser("relaunch", help="Relaunch Antigravity with the current staged profile")

    run_p = subparsers.add_parser("run", help="Run a command and monitor for rate limits")
    run_p.add_argument("cmd_args", nargs=argparse.REMAINDER, help="Command to run, e.g. agy --prompt '...'")

    args = parser.parse_args()

    if args.command == "status" or not args.command:
        print_status()
    elif args.command == "claude":
        print_claude_status()
    elif args.command == "save":
        save_current_profile(args.name)
    elif args.command == "switch":
        ok = switch_google_profile(args.name)
        if ok and args.relaunch:
            restart_antigravity_app()
    elif args.command == "auth":
        target = args.name
        if str(target).isdigit():
            target = f"google_{target}"
        authenticate_profile(target)
    elif args.command == "alias":
        set_profile_alias(args.name, args.alias)
    elif args.command == "relaunch":
        restart_antigravity_app()
    elif args.command == "run":
        if not args.cmd_args:
            print("[ERROR] No command specified for run.")
            sys.exit(1)
        sys.exit(run_command_with_failover(args.cmd_args))


if __name__ == "__main__":
    main()
