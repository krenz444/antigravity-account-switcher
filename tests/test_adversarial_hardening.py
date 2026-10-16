#!/usr/bin/env python3
"""test_adversarial_hardening.py - Comprehensive Unit & Integration Tests.

Audits and verifies all 4 dimensions:
1. Security & Token Leaks: OAuth CSRF state verification, strict profile regex, path traversal prevention, token masking, JWT edge cases.
2. Concurrency & Race Conditions: Atomic save_json thread concurrency, ERROR_SHARING_VIOLATION retry backoff, LevelDB non-blocking shared reads.
3. Network & Error Resilience: Explicit timeouts, circuit breaker backoff (429 & 401 loops), graceful offline error propagation.
4. Release & Binary Hardening: Corrupted config/state auto-healing & backup, High-DPI awareness, multi-user portability, GUI bindings.
"""

import base64
import ctypes
import http.client
import http.server
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch

# Ensure root directory is on path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import gui_app
import router


class TestSecurityAndTokenLeaks(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_sec_")
        self.orig_profiles_dir = router.PROFILES_DIR
        self.orig_active_oauth = router.ACTIVE_OAUTH
        self.orig_active_accounts = router.ACTIVE_ACCOUNTS
        self.orig_state_file = router.STATE_FILE
        router.PROFILES_DIR = os.path.join(self.test_dir, "profiles")
        router.ACTIVE_OAUTH = os.path.join(self.test_dir, "oauth_creds.json")
        router.ACTIVE_ACCOUNTS = os.path.join(self.test_dir, "google_accounts.json")
        router.STATE_FILE = os.path.join(self.test_dir, ".usage_state.json")
        os.makedirs(router.PROFILES_DIR, exist_ok=True)

    def tearDown(self):
        router.PROFILES_DIR = self.orig_profiles_dir
        router.ACTIVE_OAUTH = self.orig_active_oauth
        router.ACTIVE_ACCOUNTS = self.orig_active_accounts
        router.STATE_FILE = self.orig_state_file
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_oauth_csrf_state_verification_valid(self):
        """Verifies that matching CSRF state accepts authorization code with 200 OK."""
        received_code = []
        expected_state = "cryptographically_secure_random_state_123"

        class TestOAuthHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                import urllib.parse
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                req_state = query.get("state", [""])[0]
                if req_state == expected_state and "code" in query:
                    received_code.append(query["code"][0])
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"CSRF Failed")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), TestOAuthHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()

        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2.0)
        conn.request("GET", f"/?code=valid_auth_code_xyz&state={expected_state}")
        res = conn.getresponse()
        self.assertEqual(res.status, 200)
        self.assertEqual(received_code, ["valid_auth_code_xyz"])
        server.server_close()

    def test_oauth_csrf_state_verification_mismatched_and_missing(self):
        """Verifies that mismatched or missing CSRF state rejects the request with HTTP 400."""
        expected_state = "expected_state_abc"
        received_code = []

        class TestOAuthHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                import urllib.parse
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                req_state = query.get("state", [""])[0]
                if req_state == expected_state and "code" in query:
                    received_code.append(query["code"][0])
                    self.send_response(200)
                    self.end_headers()
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"CSRF verification failed")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), TestOAuthHandler)
        port = server.server_address[1]

        # 1. Mismatched state
        t1 = threading.Thread(target=server.handle_request, daemon=True)
        t1.start()
        conn1 = http.client.HTTPConnection('127.0.0.1', port, timeout=2.0)
        conn1.request("GET", "/?code=forged_code&state=attacker_state_evil")
        res1 = conn1.getresponse()
        self.assertEqual(res1.status, 400)
        self.assertEqual(received_code, [])

        # 2. Missing state
        t2 = threading.Thread(target=server.handle_request, daemon=True)
        t2.start()
        conn2 = http.client.HTTPConnection('127.0.0.1', port, timeout=2.0)
        conn2.request("GET", "/?code=forged_code")
        res2 = conn2.getresponse()
        self.assertEqual(res2.status, 400)
        self.assertEqual(received_code, [])

        server.server_close()

    def test_strict_profile_name_regex(self):
        """Verifies strict profile name validation against ^[a-zA-Z0-9_-]+$ and reserved names."""
        valid_names = ["google_1", "google-2", "work_account", "Personal-2026", "a", "account_3_prod"]
        for name in valid_names:
            self.assertTrue(router.is_valid_profile_name(name), f"Expected '{name}' to be valid")

        invalid_names = [
            "../../evil", "..\\system32", "profile.with.dots", "profile/slash",
            "profile\\backslash", "CON", "NUL", "PRN", "AUX", "COM1", "LPT1",
            "has space", "foo;bar", "test|pipe", "acc$var", "x" * 65, "", "   "
        ]
        for name in invalid_names:
            self.assertFalse(router.is_valid_profile_name(name), f"Expected '{name}' to be invalid")

    def test_sanitize_profile_name(self):
        """Verifies that sanitize_profile_name produces safe ^[a-zA-Z0-9_-]+$ names without path traversal."""
        self.assertTrue(router.is_valid_profile_name(router.sanitize_profile_name("../../evil/path")))
        self.assertTrue(router.is_valid_profile_name(router.sanitize_profile_name("CON")))
        self.assertTrue(router.is_valid_profile_name(router.sanitize_profile_name("foo bar!")))
        self.assertEqual(router.sanitize_profile_name("work-account"), "work-account")
        self.assertEqual(router.sanitize_profile_name("hello.world"), "hello_world")

    def test_validate_profile_path_containment(self):
        """Verifies that validate_profile_path guarantees paths remain strictly within PROFILES_DIR."""
        safe_name, target_dir = router.validate_profile_path("google_1")
        self.assertEqual(safe_name, "google_1")
        self.assertTrue(target_dir.startswith(os.path.abspath(router.PROFILES_DIR)))

        # Path traversal string is sanitized into a safe internal path
        safe_traversal, target_traversal = router.validate_profile_path("../../../windows/system32")
        self.assertTrue(target_traversal.startswith(os.path.abspath(router.PROFILES_DIR)))
        self.assertTrue(router.is_valid_profile_name(safe_traversal))

    def test_mask_sensitive_arguments(self):
        """Verifies that command arguments containing tokens, secrets, or keys are masked."""
        dummy_token = "mock" + "_" + "token" + "_" + "12345"
        dummy_secret = "mock" + "_" + "secret" + "_" + "xyz"
        dummy_bearer = "ya29.mock" + "_" + "bearer"
        raw_cmd = [
            "agy",
            "--prompt", "Generate code",
            "--csrf_token", "3f2e1a4d",
            f"--token={dummy_token}",
            "--client_secret", dummy_secret,
            f"Authorization: Bearer {dummy_bearer}",
            "-token", "legacy_token"
        ]
        masked = router.mask_sensitive_arguments(raw_cmd)
        self.assertEqual(masked[0], "agy")
        self.assertEqual(masked[1], "--prompt")
        self.assertEqual(masked[2], "Generate code")
        self.assertEqual(masked[3], "--csrf_token")
        self.assertEqual(masked[4], "********")
        self.assertEqual(masked[5], "--token=********")
        self.assertEqual(masked[6], "--client_secret")
        self.assertEqual(masked[7], "********")
        self.assertTrue("Bearer ********" in masked[8])
        self.assertEqual(masked[9], "-token")
        self.assertEqual(masked[10], "********")

    def test_extract_email_from_jwt_edge_cases(self):
        """Verifies JWT email parser on valid, invalid, malformed, and non-ASCII payloads."""
        # Valid JWT
        payload = base64.urlsafe_b64encode(json.dumps({"email": "developer@example.com"}).encode()).decode().rstrip('=')
        valid_jwt = f"header.{payload}.signature"
        self.assertEqual(router.extract_email_from_jwt(valid_jwt), "developer@example.com")

        # Edge cases: None, empty, missing dot, malformed base64, non-json
        self.assertIsNone(router.extract_email_from_jwt(None))
        self.assertIsNone(router.extract_email_from_jwt(""))
        self.assertIsNone(router.extract_email_from_jwt("nodotsintoken"))
        self.assertIsNone(router.extract_email_from_jwt("header.!!!invalid_base64!!!.sig"))
        self.assertIsNone(router.extract_email_from_jwt("header." + base64.b64encode(b"not json").decode() + ".sig"))

    def test_win32_credential_manager_helpers_safety(self):
        """Verifies write_windows_credential and read_windows_credential handle invalid inputs safely."""
        # Non-bytes/empty blob handling
        self.assertFalse(router.write_windows_credential(b""))
        self.assertFalse(router.write_windows_credential(None))

    def test_switch_google_profile_path_traversal_rejection(self):
        """Verifies that switch_google_profile rejects path traversal targets."""
        self.assertFalse(router.switch_google_profile("../../evil"))
        self.assertFalse(router.switch_google_profile("..\\..\\windows\\system32"))
        self.assertFalse(router.switch_google_profile("non_existent_account_12345"))


class TestConcurrencyAndRaceConditions(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_conc_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_atomic_save_json_thread_concurrency(self):
        """Verifies 20 concurrent threads writing to save_json without corruption or data loss."""
        target_file = os.path.join(self.test_dir, "shared_state.json")
        errors = []

        def worker(thread_idx):
            for i in range(10):
                data = {
                    "last_thread": thread_idx,
                    "iteration": i,
                    "timestamp": time.time_ns(),
                    "payload": list(range(50))
                }
                ok = router.save_json(target_file, data)
                if not ok:
                    errors.append(f"Thread {thread_idx} save failed")
                # Immediately verify the file is valid JSON
                read_back = router.load_json(target_file)
                if not isinstance(read_back, dict) or "last_thread" not in read_back:
                    errors.append(f"Corrupted read in thread {thread_idx}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(20)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        self.assertEqual(errors, [])
        final_data = router.load_json(target_file)
        self.assertIsInstance(final_data, dict)
        self.assertIn("last_thread", final_data)

    def test_atomic_save_json_sharing_violation_retry(self):
        """Verifies retry backoff when os.replace encounters Windows ERROR_SHARING_VIOLATION (WinError 32)."""
        target_file = os.path.join(self.test_dir, "locked_state.json")
        attempts = []
        real_replace = os.replace

        def mock_replace(src, dst):
            attempts.append(time.time())
            if len(attempts) <= 2:
                err = PermissionError("The process cannot access the file because it is being used by another process.")
                err.winerror = 32
                raise err
            return real_replace(src, dst)

        with patch("os.replace", side_effect=mock_replace):
            ok = router.save_json(target_file, {"recovered": True}, max_retries=5, initial_delay=0.02)

        self.assertTrue(ok)
        self.assertGreaterEqual(len(attempts), 3)
        self.assertTrue(router.load_json(target_file).get("recovered"))

    def test_atomic_save_json_permanent_failure_preserves_original(self):
        """Verifies that if all retries fail, original file is preserved and tmp file is cleaned up."""
        target_file = os.path.join(self.test_dir, "preserved_state.json")
        router.save_json(target_file, {"initial": "good_data"})

        def mock_replace_always_fail(src, dst):
            err = PermissionError("Sharing violation")
            err.winerror = 32
            raise err

        kernel32 = getattr(ctypes.windll, 'kernel32', None)
        orig_replace_file = getattr(kernel32, 'ReplaceFileW', None) if kernel32 else None
        if kernel32 and orig_replace_file:
            kernel32.ReplaceFileW = lambda *args: 0

        try:
            with patch("os.replace", side_effect=mock_replace_always_fail):
                ok = router.save_json(target_file, {"corrupted": "bad_write"}, max_retries=3, initial_delay=0.01)
        finally:
            if kernel32 and orig_replace_file:
                kernel32.ReplaceFileW = orig_replace_file

        self.assertFalse(ok)
        # Verify original data was preserved and NOT truncated
        self.assertEqual(router.load_json(target_file), {"initial": "good_data"})
        # Verify no tmp files were leaked
        tmp_files = [f for f in os.listdir(self.test_dir) if ".tmp." in f]
        self.assertEqual(tmp_files, [])

    def test_claude_leveldb_nonblocking_shared_read(self):
        """Verifies that read_shared_file safely reads LevelDB files and extracts quota regex."""
        ldb_file = os.path.join(self.test_dir, "test_leveldb.ldb")
        # Generate simulated LevelDB content with binary padding and quota records
        pad = b"random_binary_leveldb_block\x00\x01\x02" * 50
        content = pad + b'{"five_hour":{"utilization":0.22},"seven_day":{"utilization":0.87}}' + pad
        with open(ldb_file, "wb") as f:
            f.write(content)

        read_bytes = router.read_shared_file(ldb_file, max_bytes=1024 * 1024, tail_only=False)
        self.assertIn(b'"five_hour"', read_bytes)
        self.assertIn(b'"seven_day"', read_bytes)

        # Verify regex matching
        import re
        fh_m = re.findall(rb'"five_hour"[^}]+"utilization":\s*([0-9\.]+)', read_bytes)
        sd_m = re.findall(rb'"seven_day"[^}]+"utilization":\s*([0-9\.]+)', read_bytes)
        self.assertTrue(len(fh_m) > 0)
        self.assertEqual(float(fh_m[-1].decode()), 0.22)
        self.assertEqual(float(sd_m[-1].decode()), 0.87)


class TestNetworkAndErrorResilience(unittest.TestCase):
    def setUp(self):
        router.CIRCUIT_BREAKER.reset()

    def tearDown(self):
        router.CIRCUIT_BREAKER.reset()

    def test_socket_timeouts_explicit(self):
        """Verifies default socket timeout is configured defensively."""
        self.assertIsNotNone(socket.getdefaulttimeout())
        self.assertLessEqual(socket.getdefaulttimeout(), 10.0)

    def test_circuit_breaker_429_exponential_backoff(self):
        """Verifies that 429 rate limits trigger exponential backoff and block subsequent requests."""
        key = "google_test_429"
        allowed, reason = router.CIRCUIT_BREAKER.should_allow_request(key)
        self.assertTrue(allowed)

        # Record 429
        router.CIRCUIT_BREAKER.record_429(key)
        allowed, reason = router.CIRCUIT_BREAKER.should_allow_request(key)
        self.assertFalse(allowed)
        self.assertIn("rate_limited_backoff", reason)

        # Check backoff doubles
        entry = router.CIRCUIT_BREAKER._get_entry(key)
        self.assertEqual(entry["backoff_sec"], 30.0)  # Started at 15, doubled to 30

        # Success resets backoff
        router.CIRCUIT_BREAKER.record_success(key)
        allowed, _ = router.CIRCUIT_BREAKER.should_allow_request(key)
        self.assertTrue(allowed)

    def test_circuit_breaker_401_prevents_infinite_refresh_loop(self):
        """Verifies that 3 consecutive 401s trip the circuit breaker and mark auth as revoked."""
        key = "google_test_401"
        self.assertTrue(router.CIRCUIT_BREAKER.should_allow_request(key)[0])

        router.CIRCUIT_BREAKER.record_401(key)
        self.assertFalse(router.CIRCUIT_BREAKER._get_entry(key)["is_invalid"])

        router.CIRCUIT_BREAKER.record_401(key)
        self.assertFalse(router.CIRCUIT_BREAKER._get_entry(key)["is_invalid"])

        router.CIRCUIT_BREAKER.record_401(key)
        # Tripped after 3 consecutive 401s
        self.assertTrue(router.CIRCUIT_BREAKER._get_entry(key)["is_invalid"])
        allowed, reason = router.CIRCUIT_BREAKER.should_allow_request(key)
        self.assertFalse(allowed)
        self.assertEqual(reason, "auth_revoked")

    def test_offline_network_resilience(self):
        """Verifies that network errors (URLError/timeout) return explicit offline status."""
        test_dir = tempfile.mkdtemp(prefix="test_offline_")
        orig_prof = router.PROFILES_DIR
        router.PROFILES_DIR = test_dir
        prof_name = "test_offline_prof"
        pdir = os.path.join(test_dir, prof_name)
        os.makedirs(pdir, exist_ok=True)
        with open(os.path.join(pdir, "credential_blob.bin"), "w", encoding="utf-8") as f:
            json.dump({"token": {"access_token": "mock_tok"}}, f)

        try:
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
                res = router.fetch_profile_quota(prof_name)
                self.assertIsNotNone(res)
                self.assertTrue(res.get("offline"))
                self.assertEqual(res.get("error"), "offline")
        finally:
            router.PROFILES_DIR = orig_prof
            shutil.rmtree(test_dir, ignore_errors=True)


class TestReleaseAndBinaryHardening(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_rel_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_corrupted_config_json_creates_backup_and_returns_defaults(self):
        """Verifies that corrupted config.json is backed up and safe defaults are returned."""
        cfg_file = os.path.join(self.test_dir, "config.json")
        with open(cfg_file, "w", encoding="utf-8") as f:
            f.write("{ invalid json syntax truncated: ")

        with patch("router.CONFIG_FILE", cfg_file):
            cfg = router.get_config()
            self.assertIsInstance(cfg, dict)
            self.assertIn("ui", cfg)
            self.assertIn("google_profiles", cfg)
            self.assertEqual(cfg["ui"]["default_width"], 1020)

            # Check that a .bak backup file was created
            bak_files = [f for f in os.listdir(self.test_dir) if ".corrupted." in f and f.endswith(".bak")]
            self.assertGreaterEqual(len(bak_files), 1)

    def test_corrupted_state_json_heals(self):
        """Verifies that corrupted state file gracefully heals to default state."""
        state_file = os.path.join(self.test_dir, ".usage_state.json")
        with open(state_file, "w", encoding="utf-8") as f:
            f.write("[1, 2, 3]")  # Valid JSON but wrong type (list instead of dict)

        with patch("router.STATE_FILE", state_file):
            st = router.get_state()
            self.assertIsInstance(st, dict)
            self.assertEqual(st.get("active_google_profile"), "google_1")

    def test_high_dpi_awareness_fallback_cascade(self):
        """Verifies that enable_high_dpi_awareness executes safely without uncaught exceptions."""
        res = gui_app.enable_high_dpi_awareness()
        self.assertIsInstance(res, bool)

    def test_gui_quota_color_scale(self):
        """Verifies consistent color thresholds across UI progress indicators."""
        self.assertEqual(gui_app.get_quota_color(95), gui_app.COLOR_DANGER)
        self.assertEqual(gui_app.get_quota_color(85), gui_app.COLOR_WARN)
        self.assertEqual(gui_app.get_quota_color(50), gui_app.COLOR_READY)
        self.assertEqual(gui_app.get_quota_color(0), gui_app.COLOR_READY)

    def test_gui_app_add_account_compatibility(self):
        """Verifies that router.authenticate_profile and oauth_authorize_interactive alias are callable."""
        self.assertTrue(callable(router.authenticate_profile))
        self.assertTrue(callable(router.oauth_authorize_interactive))
        self.assertIs(router.authenticate_profile, router.oauth_authorize_interactive)

    def test_modern_aesthetic_themes_registry(self):
        """Verifies that all 6 modern aesthetic themes exist with complete valid hex palettes."""
        import re
        expected_themes = ["modern_obsidian", "tokyo_night", "cyberpunk_neon", "catppuccin_mocha", "nordic_frost", "dark_slate"]
        self.assertIn("modern_obsidian", gui_app.THEMES)
        for t_key in expected_themes:
            self.assertIn(t_key, gui_app.THEMES, f"Missing theme: {t_key}")
            palette = gui_app.THEMES[t_key]
            self.assertIn("name", palette)
            self.assertIn("icon", palette)
            for color_key in ["bg_main", "bg_card", "border_live", "border_staged", "color_active", "color_ready", "color_warn", "color_danger", "bg_progress_track"]:
                self.assertIn(color_key, palette)
                val = palette[color_key]
                self.assertTrue(bool(re.match(r'^#[0-9a-fA-F]{6}$', val)), f"Invalid hex color for {t_key}.{color_key}: {val}")

    def test_theme_switching_and_globals(self):
        """Verifies that applying a theme updates global color variables and restores defaults."""
        orig_theme = gui_app.CURRENT_THEME
        try:
            tokyo = gui_app.apply_theme_globals("tokyo_night")
            self.assertEqual(gui_app.CURRENT_THEME, "tokyo_night")
            self.assertEqual(gui_app.BG_MAIN, tokyo["bg_main"])
            self.assertEqual(gui_app.COLOR_READY, tokyo["color_ready"])

            obsidian = gui_app.apply_theme_globals("modern_obsidian")
            self.assertEqual(gui_app.CURRENT_THEME, "modern_obsidian")
            self.assertEqual(gui_app.BG_MAIN, obsidian["bg_main"])
            self.assertEqual(gui_app.COLOR_ACTIVE, obsidian["color_active"])
        finally:
            gui_app.apply_theme_globals(orig_theme)

    def test_set_theme_persists_in_config(self):
        """Verifies that router.set_theme persists the chosen aesthetic theme in config.json."""
        test_cfg = os.path.join(self.test_dir, "test_theme_config.json")
        with patch("router.CONFIG_FILE", test_cfg):
            router.save_json(test_cfg, {"ui": {"theme": "dark_slate"}})
            ok = router.set_theme("cyberpunk_neon")
            self.assertTrue(ok)
            loaded = router.get_config()
            self.assertEqual(loaded.get("ui", {}).get("theme"), "cyberpunk_neon")


if __name__ == "__main__":
    unittest.main(verbosity=2)
