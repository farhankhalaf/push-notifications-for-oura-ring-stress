import base64
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import plistlib
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import oura_stress_telegram as ost  # noqa: E402

ost._real_http_request = ost.http_request

BOT_TOKEN = "123456789:AAEexampleexampleexampleexampleexample"
CHAT_ID = "4242"
NOON = dt.datetime(2026, 10, 9, 12, 0, tzinfo=dt.timezone.utc)


def stress_body(*items):
    return json.dumps({"data": list(items), "next_token": None}).encode()


def today_item(seconds):
    return {"day": "2026-10-09", "stress_high": seconds}


class FakeHttp:
    """Stands in for ost.http_request. Routes by URL and records every call."""

    def __init__(self, paths):
        self.paths = paths
        self.calls = []
        self.sent = []
        self.token_calls = []
        self.stress = []          # queue of (status, body[, headers]); the last one repeats
        self.telegram_ok = True
        self.token_response = (200, {"access_token": "access-new-123456",
                                     "refresh_token": "refresh-new-123456",
                                     "expires_in": 86400, "token_type": "bearer"})
        self.tokens_on_disk_at_stress_call = []
        self.auth_headers = []

    def __call__(self, method, url, data=None, headers=None, timeout=None):
        assert timeout is None or timeout > 0
        self.calls.append((method, url))
        fields = dict(urllib.parse.parse_qsl(data.decode())) if data else {}
        if url.startswith(ost.OURA_TOKEN_URL):
            self.token_calls.append(fields)
            status, payload = self.token_response
            return status, {}, json.dumps(payload).encode()
        if url.startswith(ost.OURA_STRESS_URL):
            self.auth_headers.append((headers or {}).get("Authorization"))
            with contextlib.suppress(FileNotFoundError):
                self.tokens_on_disk_at_stress_call.append(
                    json.loads(self.paths.tokens.read_text()))
            entry = self.stress[0] if len(self.stress) == 1 else self.stress.pop(0)
            status, body = entry[0], entry[1]
            return status, (entry[2] if len(entry) > 2 else {}), body
        if url.startswith(ost.TELEGRAM_API):
            if url.endswith("/sendMessage"):
                if not self.telegram_ok:
                    return 400, {}, b'{"ok": false, "description": "Bad Request: chat not found"}'
                self.sent.append(fields["text"])
            return 200, {}, b'{"ok": true, "result": {}}'
        raise AssertionError(f"unexpected URL {url}")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = ost.Paths(Path(self.tmp.name) / "data")
        ost.write_json_private(self.paths.config, {
            "telegram_bot_token": BOT_TOKEN, "telegram_chat_id": CHAT_ID,
            "oura_client_id": "client-id", "oura_client_secret": "client-secret-xyz",
        })
        self.write_tokens(expires_in=7 * 86400)
        self.http = FakeHttp(self.paths)
        for target, value in ((ost, "http_request"),):
            patcher = mock.patch.object(target, value, self.http)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.stderr, self.stdout = io.StringIO(), io.StringIO()
        for name, stream in (("stderr", self.stderr), ("stdout", self.stdout)):
            patcher = mock.patch.object(sys, name, stream)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_tokens(self, expires_in):
        ost.write_json_private(self.paths.tokens, {
            "access_token": "access-old-123456", "refresh_token": "refresh-old-123456",
            "expires_at": int(time.time()) + expires_in, "obtained_at": int(time.time())})

    def state(self):
        return json.loads(self.paths.state.read_text())

    def set_state(self, **values):
        ost.write_json_private(self.paths.state, values)

    def check(self, now=NOON):
        return ost.run_check(self.paths, now=now)


class AlertRuleTests(Base):
    def test_first_increase_of_day(self):
        self.set_state(baseline_initialized=True)
        self.http.stress = [(200, stress_body(today_item(900)))]
        self.assertEqual(self.check(), 0)
        self.assertEqual(len(self.http.sent), 1)
        self.assertEqual(self.http.sent[0], "\U0001F534 <b>Oura recorded high stress</b>")
        self.assertNotIn("min today", self.http.sent[0])
        state = self.state()
        self.assertEqual((state["last_stress_high"], state["last_date"]), (900, "2026-10-09"))
        self.assertEqual(state["last_data_day"], "2026-10-09")

    def test_later_increase_sends_same_headline(self):
        self.set_state(last_date="2026-10-09", last_stress_high=900)
        self.http.stress = [(200, stress_body(today_item(1500)))]
        self.check()
        self.assertEqual(self.http.sent[0], "\U0001F534 <b>Oura recorded high stress</b>")
        self.assertEqual(self.state()["last_stress_high"], 1500)

    def test_no_increase_sends_nothing(self):
        self.set_state(last_date="2026-10-09", last_stress_high=900)
        self.http.stress = [(200, stress_body(today_item(900)))]
        self.check()
        self.assertEqual(self.http.sent, [])

    def test_decrease_keeps_high_water_mark(self):
        self.set_state(last_date="2026-10-09", last_stress_high=900)
        self.http.stress = [(200, stress_body(today_item(600)))]
        self.check()
        self.assertEqual(self.http.sent, [])
        self.assertEqual(self.state()["last_stress_high"], 900)

    def test_new_day_resets_baseline(self):
        self.set_state(last_date="2026-10-08", last_stress_high=3000)
        self.http.stress = [(200, stress_body(today_item(600)))]
        self.check()
        self.assertEqual(self.http.sent[0], "\U0001F534 <b>Oura recorded high stress</b>")
        self.assertEqual(self.state()["last_stress_high"], 600)

    def test_sub_minute_increases_still_alert(self):
        self.set_state(baseline_initialized=True)
        self.http.stress = [(200, stress_body(today_item(30)))]
        self.check()
        self.assertEqual(self.http.sent[0], "\U0001F534 <b>Oura recorded high stress</b>")
        self.assertEqual(self.state()["last_stress_high"], 30)
        self.set_state(last_date="2026-10-09", last_stress_high=60)
        self.http.stress = [(200, stress_body(today_item(90)))]
        self.check()
        self.assertEqual(self.http.sent[1], "\U0001F534 <b>Oura recorded high stress</b>")

    def test_min_increase_setting_batches_small_increases(self):
        self.set_state(baseline_initialized=True)
        config = json.loads(self.paths.config.read_text())
        config["settings"] = {"min_increase_minutes": 10}
        ost.write_json_private(self.paths.config, config)
        self.http.stress = [(200, stress_body(today_item(300)))]
        self.check()
        self.assertEqual(self.http.sent, [])
        self.assertEqual(self.state()["last_stress_high"], 0)
        self.http.stress = [(200, stress_body(today_item(600)))]
        self.check()
        self.assertEqual(len(self.http.sent), 1)
        self.assertEqual(self.state()["last_stress_high"], 600)

    def test_send_failure_keeps_baseline_and_records_delivery_error(self):
        self.set_state(baseline_initialized=True)
        self.http.stress = [(200, stress_body(today_item(900)))]
        self.http.telegram_ok = False
        self.assertEqual(self.check(), 0)
        state = self.state()
        self.assertEqual(state["last_stress_high"], 0)
        self.assertIn("chat not found", state["delivery_error"])
        self.http.telegram_ok = True
        self.check()
        self.assertIn("Oura recorded high stress", self.http.sent[0])
        self.assertEqual(self.state()["last_stress_high"], 900)
        self.assertIsNone(self.state()["delivery_error"])

    def test_picks_todays_record_regardless_of_order(self):
        self.set_state(baseline_initialized=True)
        self.http.stress = [(200, stress_body(
            {"day": "2026-10-10", "stress_high": 7000}, today_item(600),
            {"day": "2026-10-08", "stress_high": 5000}))]
        self.check()
        self.assertEqual(len(self.http.sent), 1)
        self.assertEqual(self.state()["last_stress_high"], 600)
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.http.calls[0][1]).query))
        self.assertEqual(query, {"start_date": "2026-10-08", "end_date": "2026-10-10"})

    def test_no_data_yet_is_healthy_but_not_data(self):
        self.set_state(consecutive_failures=2, last_error="x")
        for body in (stress_body(), stress_body(today_item(None)),
                     stress_body({"day": "2026-10-09"})):
            self.http.stress = [(200, body)]
            self.assertEqual(self.check(), 0)
            self.assertEqual(self.http.sent, [])
            self.assertEqual(self.state()["consecutive_failures"], 0)
            self.assertNotIn("last_data_day", self.state())

    def test_measured_zero_counts_as_data(self):
        self.http.stress = [(200, stress_body(today_item(0)))]
        self.check()
        self.assertEqual(self.http.sent, [])
        self.assertEqual(self.state()["last_data_day"], "2026-10-09")
        self.assertIs(self.state()["baseline_initialized"], True)
        self.http.stress = [(200, stress_body(today_item(900)))]
        self.check()
        self.assertEqual(len(self.http.sent), 1)
        self.assertIn("Oura recorded high stress</b>", self.http.sent[0])


class InitialBaselineTests(Base):
    def test_positive_first_read_is_silent_then_increases_alert(self):
        for seconds, count in ((2700, 0), (2700, 0), (3300, 1)):
            self.http.stress = [(200, stress_body(today_item(seconds)))]
            self.assertEqual(self.check(), 0)
            self.assertEqual(len(self.http.sent), count)
            self.assertEqual(self.state()["last_stress_high"], seconds)
            self.assertIs(self.state()["baseline_initialized"], True)
        self.assertEqual(self.http.sent[0], "\U0001F534 <b>Oura recorded high stress</b>")

    def test_verification_seeds_silently_during_quiet_hours(self):
        self.http.stress = [(200, stress_body(today_item(900)))]
        self.assertEqual(ost.run_check(self.paths, now=NOON.replace(hour=0, minute=30),
                                      verify=True), 0)
        self.assertEqual(self.http.sent, [])
        self.assertEqual(self.state()["last_stress_high"], 900)
        self.assertIs(self.state()["baseline_initialized"], True)
        self.assertEqual(ost.read_last_run(self.paths)["outcome"], "ok")

    def test_no_data_across_midnight_waits_for_first_valid_read(self):
        tomorrow = NOON + dt.timedelta(days=1)
        for now, payload in ((NOON, stress_body()),
                             (tomorrow, stress_body({"day": "2026-10-10", "stress_high": None}))):
            self.http.stress = [(200, payload)]
            self.check(now)
            self.assertIs(self.state()["baseline_initialized"], False)
        self.http.stress = [(200, stress_body({"day": "2026-10-10", "stress_high": 900}))]
        self.check(tomorrow)
        self.assertEqual(self.http.sent, [])
        self.assertEqual(self.state()["last_stress_high"], 900)
        self.assertIs(self.state()["baseline_initialized"], True)

    def test_api_error_does_not_consume_initialization(self):
        self.http.stress = [(500, b"{}")]
        self.assertEqual(self.check(), 1)
        self.assertFalse(ost.baseline_initialized(self.state()))
        self.http.stress = [(200, stress_body(today_item(900)))]
        self.assertEqual(self.check(), 0)
        self.assertEqual(self.http.sent, [])
        self.assertEqual(self.state()["last_stress_high"], 900)
        self.assertIs(self.state()["baseline_initialized"], True)

    def test_threshold_accumulates_from_silent_seed(self):
        config = ost.load_config(self.paths)
        config["settings"] = {"min_increase_minutes": 10}
        ost.write_json_private(self.paths.config, config)
        for seconds, baseline, count in ((900, 900, 0), (1200, 900, 0), (1500, 1500, 1)):
            self.http.stress = [(200, stress_body(today_item(seconds)))]
            self.check()
            self.assertEqual(self.state()["last_stress_high"], baseline)
            self.assertEqual(len(self.http.sent), count)

    def test_established_morning_without_data_preserves_initialization(self):
        for marker in ({"baseline_initialized": True}, {}):
            with self.subTest(marker=marker):
                self.set_state(last_date="2026-10-08", last_stress_high=2700, **marker)
                self.http.sent.clear()
                self.http.stress = [(200, stress_body())]
                self.check()
                self.assertIs(self.state()["baseline_initialized"], True)
                self.http.stress = [(500, b"{}")]
                self.assertEqual(self.check(), 1)
                self.assertIs(self.state()["baseline_initialized"], True)
                self.http.stress = [(200, stress_body())]
                ost.run_check(self.paths, now=NOON, verify=True)
                self.assertIs(self.state()["baseline_initialized"], True)
                self.http.stress = [(200, stress_body(today_item(900)))]
                self.check()
                self.assertEqual(len(self.http.sent), 1)
                self.assertIn("Oura recorded high stress</b>", self.http.sent[0])

    def test_next_day_after_seed_alerts_normally(self):
        self.http.stress = [(200, stress_body(today_item(900)))]
        self.check()
        self.http.stress = [(200, stress_body({"day": "2026-10-10", "stress_high": 600}))]
        self.check(NOON + dt.timedelta(days=1))
        self.assertEqual(len(self.http.sent), 1)
        self.assertIn("Oura recorded high stress</b>", self.http.sent[0])

    def test_legacy_baseline_and_failed_delivery_are_preserved(self):
        for baseline in (0, 900):
            with self.subTest(baseline=baseline):
                self.set_state(last_date="2026-10-09", last_stress_high=baseline)
                self.http.sent.clear()
                self.http.telegram_ok = False
                self.http.stress = [(200, stress_body(today_item(1500)))]
                self.check()
                self.assertEqual(self.state()["last_stress_high"], baseline)
                self.assertIs(self.state()["baseline_initialized"], True)
                self.http.telegram_ok = True
                self.http.stress = [(200, stress_body(today_item(1500)))]
                self.check()
                self.assertEqual(len(self.http.sent), 1)
                self.assertEqual(self.state()["last_stress_high"], 1500)

    def test_verification_on_existing_install_does_not_reseed(self):
        self.set_state(baseline_initialized=True, last_date="2026-10-09", last_stress_high=900)
        self.http.stress = [(200, stress_body(today_item(600)))]
        ost.run_check(self.paths, now=NOON, verify=True)
        self.assertEqual(self.state()["last_stress_high"], 900)
        self.http.stress = [(200, stress_body(today_item(1200)))]
        ost.run_check(self.paths, now=NOON, verify=True)
        self.assertEqual(self.http.sent[0], "\U0001F534 <b>Oura recorded high stress</b>")

    def test_only_literal_true_initializes_an_explicit_marker(self):
        for value in (False, None, 0, 1, "true", [], {}):
            with self.subTest(value=value):
                state = {"baseline_initialized": value, "last_date": "2026-10-09", "last_stress_high": 0}
                self.assertEqual(ost.plan_alert(900, state, "2026-10-09"), (None, 900))
        self.assertTrue(ost.baseline_initialized({"baseline_initialized": True}))

    def test_legacy_date_and_baseline_are_strict(self):
        for day in (None, 123, "20261009", "2026-W41-5", "2026-02-30", "bad"):
            self.assertFalse(ost.baseline_initialized({"last_date": day, "last_stress_high": 0}))
        for value in (None, True, False, -1, "0", 0.0):
            self.assertFalse(ost.baseline_initialized({"last_date": "2026-10-09", "last_stress_high": value}))
        self.assertTrue(ost.baseline_initialized({"last_date": "2026-10-09", "last_stress_high": 0}))

    def test_interactive_reads_and_reconnect_keep_marker(self):
        config = ost.load_config(self.paths)
        for marker in (False, True):
            with self.subTest(marker=marker):
                self.set_state(baseline_initialized=marker)
                with mock.patch.object(ost, "wait_for_redirect", return_value="fake-code"), \
                        mock.patch.object(ost, "token_request", return_value={
                            "access_token": "fake-access", "refresh_token": "fake-refresh", "expires_in": 3600}):
                    ost.connect_oura(self.paths, config)
                self.assertIs(self.state()["baseline_initialized"], marker)
                with mock.patch.object(ost, "read_oura_locked", return_value=900):
                    ost.read_stress_now(self.paths, config)
                self.assertIs(self.state()["baseline_initialized"], marker)
                with mock.patch.object(ost, "read_oura_locked", side_effect=ost.ReconnectNeeded("test rejection")):
                    with self.assertRaises(ost.ReconnectNeeded):
                        ost.read_stress_now(self.paths, config)
                self.assertIs(self.state()["baseline_initialized"], marker)

    def test_established_marker_survives_failures_and_pause(self):
        errors = (ost.OuraError("synthetic failure"), ost.RateLimited("synthetic limit", 60),
                  ost.ReconnectNeeded("synthetic rejection"), ost.RunTimeout("synthetic timeout"))
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.set_state(baseline_initialized=True, last_date="2026-10-09", last_stress_high=900)
                with mock.patch.object(ost, "read_oura_locked", side_effect=error):
                    self.assertEqual(self.check(), 1)
                self.assertIs(self.state()["baseline_initialized"], True)
                self.assertEqual(self.state()["last_stress_high"], 900)
        self.set_state(baseline_initialized=True, needs_reconnect=True, reconnect_notice_sent=True)
        self.assertEqual(self.check(), 1)
        self.assertIs(self.state()["baseline_initialized"], True)

    def test_setup_explanation_is_conditional_and_releases_lock_before_install(self):
        for marker in (False, True):
            with self.subTest(marker=marker):
                self.set_state(baseline_initialized=marker)
                self.stdout.seek(0)
                self.stdout.truncate()
                def installation(paths, config):
                    with ost.run_lock(paths) as acquired:
                        self.assertTrue(acquired)
                with mock.patch.object(ost, "setup_telegram"), \
                        mock.patch.object(ost, "setup_oura"), \
                        mock.patch.object(ost, "read_stress_now"), \
                        mock.patch.object(ost, "ask_yes", return_value=True), \
                        mock.patch.object(ost, "install_schedule", side_effect=installation):
                    self.assertEqual(ost.cmd_setup(self.paths, None), 0)
                text = self.stdout.getvalue()
                self.assertEqual("starting point" in text, not marker)
                self.assertEqual("saved alert history is kept" in text, marker)


class QuietHoursTests(Base):
    def test_default_quiet_hours_skip_network(self):
        early = dt.datetime(2026, 10, 9, 7, 59, tzinfo=dt.timezone.utc)
        self.assertEqual(self.check(early), 0)
        self.assertEqual(self.http.calls, [])
        self.http.stress = [(200, stress_body())]
        self.check(early.replace(hour=8, minute=0))
        self.assertEqual(len(self.http.calls), 1)

    def test_verify_mode_ignores_quiet_hours(self):
        self.http.stress = [(200, stress_body())]
        early = dt.datetime(2026, 10, 9, 3, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(ost.run_check(self.paths, now=early, verify=True), 0)
        self.assertEqual(len(self.http.calls), 1)
        self.assertEqual(ost.read_last_run(self.paths)["outcome"], "ok")

    def test_quiet_hours_skip_is_recorded_as_a_skip(self):
        self.check(dt.datetime(2026, 10, 9, 3, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(ost.read_last_run(self.paths)["outcome"], "skipped: quiet hours")

    def test_windows(self):
        q = ost.in_quiet_hours
        self.assertTrue(q(dt.time(23, 0), "22:00", "08:00"))
        self.assertTrue(q(dt.time(7, 59), "22:00", "08:00"))
        self.assertFalse(q(dt.time(12, 0), "22:00", "08:00"))
        self.assertFalse(q(dt.time(8, 0), "22:00", "08:00"))
        self.assertTrue(q(dt.time(13, 30), "13:00", "14:00"))
        self.assertFalse(q(dt.time(3, 0), "00:00", "00:00"))
        with self.assertRaises(ost.AppError):
            ost.parse_hhmm("8am")


class FailureTests(Base):
    def test_three_failures_alert_once_then_recovery_message(self):
        self.http.stress = [(500, b"oops")]
        for _ in range(4):
            self.assertEqual(self.check(), 1)
        self.assertEqual(len(self.http.sent), 1)
        self.assertIn("having trouble", self.http.sent[0])
        self.assertIn(ost.PRODUCT_NAME, self.http.sent[0])
        self.assertIn("HTTP 500", self.http.sent[0])
        self.assertRegex(self.http.sent[0], r" (?:&#x27;)?status(?:&#x27;)?</code>")
        self.assertEqual(self.state()["consecutive_failures"], 4)
        self.http.stress = [(200, stress_body())]
        self.assertEqual(self.check(), 0)
        self.assertIn("working again", self.http.sent[1])
        self.assertIn(ost.PRODUCT_NAME, self.http.sent[1])
        self.assertFalse(self.state()["failure_alerted"])
        self.check()
        self.assertEqual(len(self.http.sent), 2)

    def test_network_error_counts_as_failure(self):
        def broken(*args, **kwargs):
            raise ost.NetworkError("Could not reach api.ouraring.com: offline")
        with mock.patch.object(ost, "http_request", broken):
            self.assertEqual(self.check(), 1)
        self.assertEqual(self.state()["consecutive_failures"], 1)

    def test_unexpected_schema_is_failure(self):
        self.http.stress = [(200, b'{"nope": 1}')]
        self.assertEqual(self.check(), 1)
        self.assertIn("unexpected", self.state()["last_error"])

    def test_403_explains_membership(self):
        self.http.stress = [(403, b"{}")]
        self.check()
        self.assertIn("Membership", self.state()["last_error"])

    def test_missing_setup_is_reported(self):
        ost.write_json_private(self.paths.config, {})
        self.assertEqual(self.check(), 1)
        self.assertIn("setup is not finished", self.stderr.getvalue())

    def test_retry_after_pauses_oura_requests(self):
        self.http.stress = [(429, b"{}", {"retry-after": "1800"})]
        self.assertEqual(self.check(), 1)
        self.assertEqual(self.state()["next_oura_request_at"], int(NOON.timestamp()) + 1800)
        calls = len(self.http.calls)
        later = NOON + dt.timedelta(minutes=10)
        self.assertEqual(self.check(later), 0)
        self.assertEqual(len(self.http.calls), calls)
        self.assertEqual(self.state()["consecutive_failures"], 1)
        self.http.stress = [(200, stress_body())]
        self.assertEqual(self.check(NOON + dt.timedelta(minutes=31)), 0)
        self.assertIsNone(self.state()["next_oura_request_at"])

    def test_retry_after_is_capped_and_defaulted(self):
        self.assertEqual(ost.retry_after_seconds({"retry-after": "7200"}), 7200)
        self.assertEqual(ost.retry_after_seconds({"retry-after": "999999"}), 86400)
        self.assertEqual(ost.retry_after_seconds({}), ost.DEFAULT_RETRY_AFTER_SECONDS)
        self.assertEqual(ost.retry_after_seconds({"retry-after": "soon"}),
                         ost.DEFAULT_RETRY_AFTER_SECONDS)

    @unittest.skipIf(os.name == "nt", "POSIX hard deadline; Windows soft deadline has native coverage")
    def test_whole_run_time_limit(self):
        def slow(*args, **kwargs):
            time.sleep(5)
            raise AssertionError("should have been interrupted")
        with mock.patch.object(ost, "http_request", slow):
            started = time.monotonic()
            with ost.time_limit(1):
                self.assertEqual(self.check(), 1)
            self.assertLess(time.monotonic() - started, 4)
        self.assertIn("longer than", self.state()["last_error"])


class TokenTests(Base):
    def test_refresh_before_expiry_is_saved_before_use(self):
        self.write_tokens(expires_in=60)
        self.http.stress = [(200, stress_body())]
        self.assertEqual(self.check(), 0)
        call = self.http.token_calls[0]
        self.assertEqual((call["grant_type"], call["refresh_token"], call["client_secret"]),
                         ("refresh_token", "refresh-old-123456", "client-secret-xyz"))
        self.assertEqual(self.http.tokens_on_disk_at_stress_call[0]["refresh_token"],
                         "refresh-new-123456")
        self.assertEqual(self.http.auth_headers, ["Bearer access-new-123456"])

    def test_401_refreshes_once_then_retries(self):
        self.http.stress = [(401, b"{}"), (200, stress_body())]
        self.assertEqual(self.check(), 0)
        self.assertEqual(len(self.http.token_calls), 1)
        self.assertEqual(self.http.auth_headers,
                         ["Bearer access-old-123456", "Bearer access-new-123456"])

    def test_invalid_grant_pauses_and_notifies(self):
        self.write_tokens(expires_in=0)
        self.http.token_response = (400, {"error": "invalid_grant"})
        self.assertEqual(self.check(), 1)
        state = self.state()
        self.assertTrue(state["needs_reconnect"])
        self.assertTrue(state["reconnect_notice_sent"])
        self.assertRegex(self.http.sent[0], r"connect-oura(?:&#x27;)?</code>")
        self.assertIn(ost.SCRIPT_NAME, self.http.sent[0])
        # The test folder is not the default one, so the command must carry it.
        self.assertIn("--data-dir" if os.name == "nt" else "OURA_STRESS_HOME=", self.http.sent[0])
        self.assertEqual(ost.read_last_run(self.paths)["outcome"],
                         "paused: Oura needs to be reconnected")
        calls = len(self.http.calls)
        self.assertEqual(self.check(), 1)
        self.assertEqual(len(self.http.calls), calls)  # paused: no requests at all
        self.assertEqual(len(self.http.sent), 1)

    def test_reconnect_notice_retried_until_delivered(self):
        self.write_tokens(expires_in=0)
        self.http.token_response = (400, {"error": "invalid_grant"})
        self.http.telegram_ok = False
        self.check()
        self.assertFalse(self.state()["reconnect_notice_sent"])
        oura_calls = [c for c in self.http.calls if "ouraring" in c[1]]
        self.check()  # still failing: tries Telegram again, not Oura
        self.assertEqual([c for c in self.http.calls if "ouraring" in c[1]], oura_calls)
        self.http.telegram_ok = True
        self.check()
        self.assertTrue(self.state()["reconnect_notice_sent"])
        self.assertEqual(len(self.http.sent), 1)
        self.check()
        self.assertEqual(len(self.http.sent), 1)

    def test_spent_refresh_invalid_request_pauses_and_notifies_once(self):
        self.write_tokens(expires_in=0)
        self.http.token_response = (400, {"error": "invalid_request",
                                          "error_description": "Invalid request"})
        self.assertEqual(self.check(), 1)
        self.assertTrue(self.state()["needs_reconnect"])
        self.assertTrue(self.state()["reconnect_notice_sent"])
        self.assertRegex(self.http.sent[0], r"connect-oura(?:&#x27;)?</code>")
        self.assertIn("Sleep, readiness, and activity", self.http.sent[0])
        self.assertEqual(self.check(), 1)
        self.assertEqual(len(self.http.token_calls), 1)
        self.assertEqual(len(self.http.sent), 1)

    def test_invalid_authorization_request_is_not_a_spent_refresh_token(self):
        self.http.token_response = (400, {"error": "invalid_request"})
        with self.assertRaises(ost.OuraError):
            ost.token_request(ost.load_config(self.paths),
                              {"grant_type": "authorization_code", "code": "bad-code"})

    def test_missing_daily_consent_pauses_without_rotating_tokens(self):
        for detail in ("Token is not authorized access daily scope.",
                       "Token is not authorized to access daily scope."):
            body = json.dumps({"detail": detail}).encode()
            for status in (401, 403):
                with self.subTest(status=status, detail=detail):
                    self.set_state()
                    self.http.stress = [(status, body)]
                    self.assertEqual(self.check(), 1)
                    self.assertTrue(self.state()["needs_reconnect"])
                    self.assertIn("Daily permission was not granted", self.state()["last_error"])
                    self.assertNotIn("Run:", self.state()["last_error"])
                    self.assertIn("did not grant the Daily permission", self.http.sent[-1])
                    self.assertIn("Sleep, readiness, and activity", self.http.sent[-1])
                    self.assertEqual(self.http.token_calls, [])

    def test_missing_daily_reason_survives_notice_delivery_retry(self):
        self.http.stress = [(401, b'{"detail":"Token is not authorized access daily scope."}')]
        self.http.telegram_ok = False
        self.assertEqual(self.check(), 1)
        self.assertEqual(self.state()["reconnect_reason"], "missing_daily_scope")
        self.http.telegram_ok = True
        self.assertEqual(self.check(), 1)
        self.assertIn("did not grant the Daily permission", self.http.sent[-1])

    def test_second_401_needs_reconnect(self):
        self.http.stress = [(401, b"{}")]
        self.assertEqual(self.check(), 1)
        self.assertTrue(self.state()["needs_reconnect"])

    def test_lost_tokens_land_on_reconnect_path(self):
        self.paths.tokens.unlink()
        self.assertEqual(self.check(), 1)
        self.assertTrue(self.state()["needs_reconnect"])
        self.assertIn("connect-oura", self.http.sent[0])

    def test_lost_refresh_response_lands_on_reconnect_path(self):
        """Oura rotated the token but the reply never arrived: the old one is spent."""
        self.write_tokens(expires_in=0)
        real = self.http

        def drop_token_reply(method, url, **kwargs):
            if url.startswith(ost.OURA_TOKEN_URL):
                real.token_response = (400, {"error": "invalid_request",
                                             "error_description": "Invalid request"})
                raise ost.NetworkError("Could not reach api.ouraring.com: timed out")
            return real(method, url, **kwargs)
        with mock.patch.object(ost, "http_request", drop_token_reply):
            self.assertEqual(self.check(), 1)
        self.assertEqual(self.state()["consecutive_failures"], 1)
        self.assertEqual(json.loads(self.paths.tokens.read_text())["refresh_token"],
                         "refresh-old-123456")
        self.assertEqual(self.check(), 1)
        self.assertTrue(self.state()["needs_reconnect"])
        self.assertIn("connect-oura", self.http.sent[0])

    def test_failed_token_save_lands_on_reconnect_path(self):
        self.write_tokens(expires_in=0)
        real_write = ost.write_json_private

        def failing_write(path, data):
            if path == self.paths.tokens:
                raise OSError(28, "No space left on device")
            return real_write(path, data)
        with mock.patch.object(ost, "write_json_private", failing_write):
            self.assertEqual(self.check(), 1)
        self.assertIn("No space left", self.state()["last_error"])
        self.http.token_response = (400, {"error": "invalid_grant"})  # old token was spent
        self.assertEqual(self.check(), 1)
        self.assertTrue(self.state()["needs_reconnect"])

    def test_tokens_from_response_defaults(self):
        tokens = ost.tokens_from_response({"access_token": "a" * 10}, 1000.0, "old-refresh")
        self.assertEqual(tokens["expires_at"], 1000 + ost.DEFAULT_TOKEN_LIFETIME_SECONDS)
        self.assertEqual(tokens["refresh_token"], "old-refresh")


class SafetyTests(Base):
    def test_files_are_private(self):
        self.http.stress = [(200, stress_body())]
        self.check()
        if os.name == "nt":
            for path in (self.paths.root, self.paths.config, self.paths.tokens, self.paths.state):
                self.assertTrue(ost.private_windows_acl(ost.windows_acl(path), ost.windows_user_sid()))
            return
        self.assertEqual(stat.S_IMODE(os.stat(self.paths.root).st_mode), 0o700)
        for path in (self.paths.config, self.paths.tokens, self.paths.state):
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600, path)

    def test_all_credentials_are_redacted_including_encoded(self):
        code, verifier, secret = "authcode-QQ+/=zz", "verifier-RR+/=yy", "client-secret-xyz"
        ost.load_config(self.paths)
        ost.load_tokens(self.paths)
        ost.handle_redirect_query(urllib.parse.urlencode({"code": code, "state": "s"}), "s")
        ost.remember_secret(verifier)
        raw = (f"{BOT_TOKEN} refresh-old-123456 {secret} {code} {verifier} "
               f"{urllib.parse.quote(code, safe='')} {urllib.parse.quote_plus(verifier)}")
        text = ost.redact(raw)
        for value in (BOT_TOKEN, "refresh-old-123456", secret, code, verifier,
                      urllib.parse.quote(code, safe=""), urllib.parse.quote_plus(verifier)):
            self.assertNotIn(value, text)
        self.assertNotIn("987654321:" + "B" * 35, ost.redact("x 987654321:" + "B" * 35))

    def test_token_exchange_failure_does_not_leak(self):
        self.http.token_response = (500, {"error": "server_error"})
        with self.assertRaises(ost.OuraError) as ctx:
            ost.token_request({"oura_client_id": "id", "oura_client_secret": "sek-123456"},
                              {"grant_type": "authorization_code", "code": "code-777777",
                               "code_verifier": "ver-888888"})
        message = str(ctx.exception)
        for value in ("sek-123456", "code-777777", "ver-888888"):
            self.assertNotIn(value, message)

    def test_error_reason_is_html_escaped(self):
        self.set_state(consecutive_failures=2)
        with mock.patch.object(ost.OuraClient, "stress_high_today",
                               side_effect=ost.OuraError("<b>bad</b> & worse")):
            self.check()
        self.assertIn("&lt;b&gt;bad&lt;/b&gt; &amp; worse", self.http.sent[0])

    def test_lock_held_by_another_process_skips_check(self):
        script = textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(ROOT)!r})
            import oura_stress_telegram as ost
            from pathlib import Path, PurePosixPath
            with ost.run_lock(ost.Paths(Path({str(self.paths.root)!r}))) as held:
                print("held" if held else "busy", flush=True)
                time.sleep(3)
        """)
        child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "held")
            self.assertEqual(self.check(), 0)
            self.assertEqual(self.http.calls, [])
            self.assertIn("SKIP", self.stderr.getvalue())
            with self.assertRaises(ost.AppError):
                with mock.patch.object(ost, "INTERACTIVE_LOCK_WAIT_SECONDS", 0.5):
                    with ost.interactive_lock(self.paths):
                        pass
        finally:
            child.wait(timeout=10)
        with ost.interactive_lock(self.paths):
            pass

    def test_corrupt_state_starts_fresh(self):
        self.paths.state.write_text("{not json")
        self.http.stress = [(200, stress_body(today_item(120)))]
        self.assertEqual(self.check(), 0)
        self.assertEqual(self.state()["last_stress_high"], 120)
        self.assertEqual(self.http.sent, [])
        self.assertIs(self.state()["baseline_initialized"], True)

    def test_commands_in_messages_are_absolute(self):
        with mock.patch.dict(os.environ, {"OURA_STRESS_HOME": ""}):
            with mock.patch.object(ost, "default_paths",
                                   return_value=ost.Paths(ost.default_root())):
                command = ost.command_for("connect-oura")
        self.assertTrue(command.startswith("& ") if os.name == "nt" else
                        command.split()[0].startswith(("/", "'/")))
        self.assertIn(ost.SCRIPT_NAME, command)
        self.assertNotIn("OURA_STRESS_HOME", command)

    def test_recovery_command_works_from_a_clean_shell_with_custom_folder(self):
        command = ost.command_for("status", self.paths)
        if os.name == "nt":
            self.assertIn("--data-dir", command)
            command = ("$ErrorActionPreference='Stop'; "
                       "[Console]::InputEncoding=[Text.UTF8Encoding]::new($false); "
                       "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
                       + command + "; exit $LASTEXITCODE")
            encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
            cmd = [ost.windows_powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
            env = ost.scheduled_environment(self.paths)
        else:
            self.assertIn("OURA_STRESS_HOME=", command)
            cmd = ["/bin/sh", "-c", command]
            env = {"HOME": self.tmp.name, "PATH": "/usr/bin:/bin"}
        result = subprocess.run(cmd, env=env, capture_output=True, encoding="utf-8",
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Settings folder: {self.paths.root.resolve()}", result.stdout)
        self.assertIn("Telegram set up: yes", result.stdout)
        self.assertNotIn(BOT_TOKEN, result.stdout)

    def test_lock_contention_is_recorded_as_a_skip(self):
        with ost.run_lock(self.paths):
            pass
        held = ost.run_lock(self.paths)
        with held:
            child = subprocess.run(
                [sys.executable, str(ROOT / ost.SCRIPT_NAME), "check"],
                env=ost.scheduled_environment(self.paths),
                capture_output=True, text=True, timeout=60)
        self.assertEqual(child.returncode, 0)
        self.assertEqual(ost.read_last_run(self.paths)["outcome"],
                         "skipped: another check was running")


class InstallVerificationTests(Base):
    def fake_child(self, outcome, code=0, touch=True, same_id=True):
        def run(cmd, **kwargs):
            self.assertIn("--verify", cmd)
            self.assertEqual(kwargs["env"]["OURA_STRESS_HOME"], str(self.paths.root))
            run_id = cmd[cmd.index("--run-id") + 1] if same_id else "someone-else"
            if touch:
                ost.record_run(self.paths, time.time(), outcome, run_id)
            return subprocess.CompletedProcess(cmd, code, "", "")
        return run

    def test_paused_install_verification_includes_recovery_command(self):
        self.set_state(needs_reconnect=True, reconnect_action="connect-oura",
                       last_error="Oura Daily permission was not granted.")
        with mock.patch.object(ost, "run", self.fake_child("paused: Oura needs to be reconnected", code=1)):
            with self.assertRaises(ost.AppError) as caught:
                ost.verify_background_run(self.paths, "/usr/bin/python3", Path("/s.py"))
        self.assertIn(ost.command_for("connect-oura", self.paths), str(caught.exception))

    def test_verification_passes_only_for_its_own_successful_check(self):
        with mock.patch.object(ost, "run", self.fake_child("ok")):
            ost.verify_background_run(self.paths, "/usr/bin/python3", Path("/s.py"))
        ost.record_run(self.paths, time.time(), "ok", "stale-receipt")
        for child in (self.fake_child("skipped: another check was running"),
                      self.fake_child("ok", touch=False),
                      self.fake_child("ok", same_id=False),
                      self.fake_child("degraded: the Telegram alert failed"),
                      self.fake_child("error: Oura API returned HTTP 500", code=1)):
            with mock.patch.object(ost, "run", child):
                with self.assertRaises(ost.AppError):
                    ost.verify_background_run(self.paths, "/usr/bin/python3", Path("/s.py"))

    def test_scheduled_run_must_be_observed(self):
        since = time.time()
        self.assertIsNone(ost.wait_for_scheduled_run(self.paths, since, timeout=0.2))
        with self.assertRaises(ost.AppError):
            ost.report_scheduled_run(None)
        ost.record_run(self.paths, since + 0.1, "skipped: quiet hours")
        self.assertEqual(ost.wait_for_scheduled_run(self.paths, since, timeout=1),
                         "skipped: quiet hours")
        ost.report_scheduled_run("skipped: quiet hours")
        for bad in ("paused: Oura needs to be reconnected", "degraded: the Telegram alert failed"):
            with self.assertRaises(ost.AppError):
                ost.report_scheduled_run(bad)


class ReviewFixTests(Base):
    def test_delete_data_removes_only_owned_files(self):
        other = self.paths.root / "my-notes.txt"
        other.write_text("keep me")
        ost.delete_owned_files(self.paths.root, ost.OWNED_DATA_FILES)
        self.assertTrue(other.exists())
        self.assertFalse(self.paths.config.exists())
        other.unlink()
        ost.delete_owned_files(self.paths.root, ost.OWNED_DATA_FILES)
        self.assertFalse(self.paths.root.exists())

    def test_crontab_read_failure_leaves_crontab_alone(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 1, "", "crontab: permission denied")
        with mock.patch.object(ost, "run", fake_run):
            with self.assertRaises(ost.AppError):
                ost.set_cron_line("* * * * * x " + ost.CRON_MARKER)
        self.assertEqual(calls, [["crontab", "-l"]])

    def test_token_endpoint_429_pauses(self):
        self.write_tokens(expires_in=0)
        real = self.http

        def throttled(method, url, **kwargs):
            if url.startswith(ost.OURA_TOKEN_URL):
                return 429, {"retry-after": "7200"}, b"{}"
            return real(method, url, **kwargs)
        with mock.patch.object(ost, "http_request", throttled):
            self.assertEqual(self.check(), 1)
        self.assertEqual(self.state()["next_oura_request_at"], int(NOON.timestamp()) + 7200)
        with self.assertRaises(ost.AppError):
            with mock.patch.object(ost.time, "time", return_value=NOON.timestamp() + 60):
                ost.read_stress_now(self.paths, ost.load_config(self.paths))

    def test_rejected_app_keys_point_to_setup(self):
        self.write_tokens(expires_in=0)
        self.http.token_response = (401, {"error": "invalid_client"})
        self.check()
        self.assertEqual(self.state()["reconnect_action"], "setup")
        self.assertRegex(self.http.sent[0], r" (?:&#x27;)?setup(?:&#x27;)?</code>")

    def test_truncated_response_counts_as_failure(self):
        import http.client

        def truncated(*args, **kwargs):
            raise http.client.IncompleteRead(b"par")
        with mock.patch.object(ost._OPENER, "open", truncated):
            with mock.patch.object(ost, "http_request", ost.__dict__["_real_http_request"]):
                self.assertEqual(self.check(), 1)
        self.assertEqual(self.state()["consecutive_failures"], 1)

    @unittest.skipIf(os.name == "nt", "POSIX hard deadline; Windows soft deadline has native coverage")
    def test_timeout_does_no_more_network_work(self):
        sent_before = len(self.http.sent)
        self.set_state(consecutive_failures=2)

        def slow(*args, **kwargs):
            time.sleep(5)
        with mock.patch.object(ost.OuraClient, "stress_high_today", slow):
            with ost.time_limit(1):
                self.assertEqual(self.check(), 1)
        self.assertEqual(len(self.http.sent), sent_before)
        self.assertEqual(self.state()["consecutive_failures"], 3)

    def test_idle_connection_does_not_block_callback(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        result, done = {}, threading.Event()
        servers = ost.start_callback_servers(port, ost._callback_handler("st", result, done))
        idle = socket.create_connection(("127.0.0.1", port))
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=c123456&state=st",
                                        timeout=5) as response:
                self.assertEqual(response.status, 200)
            started = time.monotonic()
            for server in servers:
                server.shutdown()
                server.server_close()
            self.assertLess(time.monotonic() - started, 3)
        finally:
            idle.close()
        self.assertEqual(result["code"], "c123456")

    @unittest.skipIf(os.name == "nt", "POSIX hard deadline; Windows soft deadline has native coverage")
    def test_deadline_inside_error_body_read_is_not_swallowed(self):
        import email.message
        self.set_state(consecutive_failures=2)  # a counted failure would send a Telegram alert

        class SlowBody(io.BytesIO):
            def read(self, *args):
                time.sleep(5)
                return b""

        def opener(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 500, "boom",
                                         email.message.Message(), SlowBody())
        started = time.monotonic()
        with mock.patch.object(ost._OPENER, "open", opener), \
                mock.patch.object(ost, "http_request", ost._real_http_request), \
                mock.patch.object(ost, "send_telegram") as send:
            with ost.time_limit(1):
                self.assertEqual(self.check(), 1)
        self.assertLess(time.monotonic() - started, 2.5)
        send.assert_not_called()
        self.assertIn("longer than", self.state()["last_error"])

    @unittest.skipIf(os.name == "nt", "POSIX hard deadline; Windows soft deadline has native coverage")
    def test_timeout_cleanup_happens_while_holding_the_lock(self):
        import fcntl
        held_during_write = []
        real_write = ost.write_json_private

        def watching_write(path, data):
            if path == self.paths.state and "longer than" in str(data.get("last_error")):
                with open(self.paths.lock, "a") as other:
                    try:
                        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        held_during_write.append(False)
                    except OSError:
                        held_during_write.append(True)
            return real_write(path, data)

        def slow(*args, **kwargs):
            time.sleep(5)
        with mock.patch.object(ost.OuraClient, "stress_high_today", slow), \
                mock.patch.object(ost, "write_json_private", watching_write):
            with ost.time_limit(1):
                self.check()
        self.assertEqual(held_during_write, [True])

    def test_interactive_read_persists_and_honors_rate_limit(self):
        self.http.stress = [(429, b"{}", {"retry-after": "7200"})]
        config = ost.load_config(self.paths)
        with self.assertRaises(ost.RateLimited):
            ost.read_stress_now(self.paths, config)
        self.assertGreater(self.state()["next_oura_request_at"], time.time() + 7000)
        calls = len(self.http.calls)
        with self.assertRaises(ost.AppError):
            ost.read_stress_now(self.paths, config)
        self.assertEqual(len(self.http.calls), calls)

    @unittest.skipIf(os.name == "nt", "macOS-specific system interface")
    def test_uninstall_reports_a_job_that_is_still_loaded(self):
        plist = Path(self.tmp.name) / "job.plist"
        plist.write_text("x")

        def still_loaded(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0 if cmd[1] == "print" else 5, "", "")
        with mock.patch.object(ost.platform, "system", return_value="Darwin"), \
                mock.patch.object(ost, "launchd_plist_path", return_value=plist), \
                mock.patch.object(ost, "run", still_loaded):
            with self.assertRaises(ost.AppError):
                ost.uninstall_schedule()
        self.assertTrue(plist.exists())

    def test_uninstall_reports_unreachable_systemd(self):
        unit_dir = Path(self.tmp.name) / "units"
        unit_dir.mkdir()
        (unit_dir / f"{ost.SYSTEMD_UNIT}.timer").write_text("x")
        with mock.patch.object(ost.platform, "system", return_value="Linux"), \
                mock.patch.object(ost, "systemd_unit_dir", return_value=unit_dir), \
                mock.patch.object(ost, "systemd_user_available", return_value=False), \
                mock.patch.object(ost.shutil, "which", return_value=None):
            with self.assertRaises(ost.AppError):
                ost.uninstall_schedule()
        self.assertTrue((unit_dir / f"{ost.SYSTEMD_UNIT}.timer").exists())

    @unittest.skipIf(os.name == "nt", "macOS-specific system interface")
    def test_python_path_keeps_stable_paths(self):
        with mock.patch.object(ost.sys, "executable", "/opt/homebrew/opt/python@3.14/bin/python3.14"):
            self.assertEqual(ost.python_path(), "/opt/homebrew/opt/python@3.14/bin/python3.14")
        with mock.patch.object(ost.sys, "executable",
                               "/Applications/Xcode.app/Contents/Developer/usr/bin/python3"):
            if os.access("/usr/bin/python3", os.X_OK):
                self.assertEqual(ost.python_path(), "/usr/bin/python3")


class SetupGuidanceTests(Base):
    def test_missing_consent_during_setup_points_back_to_setup_and_can_finish(self):
        self.http.stress = [(401, b'{"detail":"Token is not authorized access daily scope."}')]
        with mock.patch.object(ost, "default_paths", return_value=self.paths), \
                mock.patch.object(ost, "setup_telegram"), \
                mock.patch.object(ost, "setup_oura"), \
                mock.patch.object(ost, "ask_yes", return_value=True), \
                mock.patch.object(ost, "install_schedule") as install:
            self.assertEqual(ost.main(["setup"]), 1)
            install.assert_not_called()
            self.assertIn("Your saved Telegram and Oura app keys are kept", self.stdout.getvalue())
            self.assertIn(ost.command_for("setup", self.paths, prefer_installed=False), self.stdout.getvalue())
            self.assertNotIn(ost.command_for("connect-oura", self.paths, prefer_installed=False), self.stdout.getvalue())
            self.http.stress = [(200, stress_body())]
            self.assertEqual(ost.main(["setup"]), 0)
            install.assert_called_once()

    def test_reconnect_checks_permission_before_reporting_success(self):
        self.http.stress = [(401, b'{"detail":"Token is not authorized access daily scope."}')]
        with mock.patch.object(ost, "default_paths", return_value=self.paths), \
                mock.patch.object(ost, "wait_for_redirect", return_value="new-code"):
            self.assertEqual(ost.main(["connect-oura"]), 1)
        self.assertIn("Daily permission was not granted", self.stdout.getvalue())
        self.assertIn(ost.command_for("connect-oura", self.paths, prefer_installed=False), self.stdout.getvalue())
        self.assertNotIn("Oura is connected", self.stdout.getvalue())
        self.assertNotIn("Oura: connected", self.stdout.getvalue())
        self.assertTrue(self.state()["needs_reconnect"])
        self.assertEqual(self.state()["reconnect_reason"], "missing_daily_scope")
        calls_before_check = len(self.http.calls)
        self.assertEqual(self.check(), 1)
        self.assertEqual(len(self.http.calls), calls_before_check)
        self.assertEqual(self.http.sent, [])

    def test_reconnect_without_schedule_explains_how_to_install(self):
        self.http.stress = [(200, stress_body())]
        with mock.patch.object(ost, "default_paths", return_value=self.paths), \
                mock.patch.object(ost, "wait_for_redirect", return_value="new-code"), \
                mock.patch.object(ost, "schedule_description", return_value="not installed"):
            self.assertEqual(ost.main(["connect-oura"]), 0)
        self.assertIn("Oura: connected", self.stdout.getvalue())
        self.assertIn("Automatic checks are not installed", self.stdout.getvalue())
        self.assertIn(ost.command_for("install", self.paths, prefer_installed=False), self.stdout.getvalue())

    def test_rejected_app_keys_during_setup_explain_replacement(self):
        self.http.token_response = (400, {"error": "invalid_client"})
        with mock.patch.object(ost, "default_paths", return_value=self.paths), \
                mock.patch.object(ost, "setup_telegram"), \
                mock.patch.object(ost, "ask_yes", return_value=True), \
                mock.patch.object(ost, "wait_for_redirect", return_value="new-code"):
            self.assertEqual(ost.main(["setup"]), 1)
        output = self.stdout.getvalue()
        self.assertIn("answer n", output)
        self.assertIn("enter the Client ID and Client Secret again", output)
        self.assertNotIn("app keys are kept", output)

    def test_interactive_setup_recovery_uses_current_source_not_an_old_install(self):
        installed = Path(self.tmp.name) / "old-installed.py"
        installed.write_text("# older installed copy\n")
        with mock.patch.object(ost, "default_paths", return_value=self.paths), \
                mock.patch.object(ost, "installed_script_path", return_value=installed), \
                mock.patch.object(ost, "setup_telegram"), \
                mock.patch.object(ost, "setup_oura", side_effect=ost.ReconnectNeeded("Reconnect")):
            self.assertEqual(ost.main(["setup"]), 1)
            self.assertIn(str(installed), ost.command_for("connect-oura", self.paths))
        self.assertIn(str(Path(ost.__file__).resolve()), self.stdout.getvalue())
        self.assertNotIn(str(installed), self.stdout.getvalue())

    def test_reconnect_read_outage_reports_that_login_was_saved(self):
        self.http.stress = [(500, b"{}")]
        with mock.patch.object(ost, "default_paths", return_value=self.paths), \
                mock.patch.object(ost, "wait_for_redirect", return_value="new-code"):
            self.assertEqual(ost.main(["connect-oura"]), 1)
        self.assertIn("login was saved, but the test read failed", self.stdout.getvalue())
        self.assertEqual(ost.load_tokens(self.paths)["access_token"], "access-new-123456")
        self.assertFalse(self.state()["needs_reconnect"])

    def test_new_app_setup_uses_current_registration_portal(self):
        config = {}
        with mock.patch.dict(os.environ, {"OURA_CLIENT_ID": "new-client-id",
                                          "OURA_CLIENT_SECRET": "new-client-secret"}), \
                mock.patch.object(ost, "connect_oura") as connect:
            ost.setup_oura(self.paths, config)
        output = self.stdout.getvalue()
        self.assertIn("https://developer.ouraring.com/applications", output)
        self.assertNotIn("https://cloud.ouraring.com/oauth/applications", output)
        self.assertIn("http://localhost:8765/callback", output)
        self.assertIn(f"application named {ost.PRODUCT_NAME}", output)
        self.assertNotIn("keep \"Oura\" out", output)
        self.assertIn("description and contact email", output)
        self.assertIn("Select Daily under Scopes", output)
        self.assertIn("Accept the Oura API Agreement", output)
        self.assertNotIn("new-client-secret", output)
        self.assertEqual(ost.load_config(self.paths)["oura_client_id"], "new-client-id")
        connect.assert_called_once_with(self.paths, config)

    def test_rejected_app_keys_link_to_current_portal(self):
        self.assertIn("https://developer.ouraring.com/applications",
                      ost.reconnect_notice(self.paths, action="setup"))


class OAuthTests(unittest.TestCase):
    def test_pkce_pair(self):
        verifier, challenge = ost.pkce_pair()
        self.assertTrue(43 <= len(verifier) <= 128)
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        self.assertEqual(challenge, expected.rstrip(b"=").decode())

    def test_redirect_query(self):
        handle = ost.handle_redirect_query
        self.assertEqual(handle("code=abc123&state=s1", "s1"), {"code": "abc123"})
        self.assertIn("did not match", handle("code=abc&state=evil", "s1")["error"])
        self.assertIn("access_denied", handle("error=access_denied&state=s1", "s1")["error"])
        self.assertIn("did not return", handle("state=s1", "s1")["error"])

    def test_callback_server_accepts_only_matching_state_and_logs_nothing(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        result, done = {}, threading.Event()
        captured = io.StringIO()
        with mock.patch.object(sys, "stderr", captured):
            servers = ost.start_callback_servers(port, ost._callback_handler("good", result, done))
            try:
                self.assertTrue(servers)
                base = f"http://127.0.0.1:{port}/callback"
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(f"{base}?code=x&state=bad", timeout=5)
                self.assertFalse(done.is_set())
                with urllib.request.urlopen(f"{base}?code=secret-code-999&state=good",
                                            timeout=5) as response:
                    self.assertIn(b"Connected", response.read())
                # Receiving the body does not synchronize with the server's
                # subsequent completion signal. Wait for that thread explicitly.
                self.assertTrue(done.wait(timeout=5))
                self.assertEqual(result["code"], "secret-code-999")
            finally:
                for server in servers:
                    server.shutdown()
                    server.server_close()
        self.assertNotIn("secret-code-999", captured.getvalue())

    def test_authorization_code_exchange_fields(self):
        captured = {}

        def fake(method, url, data=None, headers=None, timeout=None):
            captured.update(urllib.parse.parse_qsl(data.decode()))
            return 200, {}, json.dumps({"access_token": "a" * 12, "refresh_token": "r" * 12,
                                        "expires_in": 100}).encode()
        with mock.patch.object(ost, "http_request", fake):
            ost.token_request({"oura_client_id": "id", "oura_client_secret": "sec"},
                              {"grant_type": "authorization_code", "code": "c",
                               "redirect_uri": ost.redirect_uri(8765), "code_verifier": "v"})
        self.assertEqual(captured["client_id"], "id")
        self.assertEqual(captured["redirect_uri"], "http://localhost:8765/callback")
        self.assertEqual(captured["code_verifier"], "v")


class TelegramPairingTests(unittest.TestCase):
    def test_only_the_code_from_a_private_chat_pairs(self):
        updates = [
            {"update_id": 1, "message": {"chat": {"id": 5, "type": "private"}, "text": "hi"}},
            {"update_id": 2, "message": {"chat": {"id": -100, "type": "group"}, "text": "AB12CD"}},
            {"update_id": 3, "message": {"chat": {"id": 9, "type": "private"}, "text": "ab12cd"}},
            {"update_id": 4, "message": "weird"},
        ]
        self.assertEqual(ost.find_paired_chat(updates, "AB12CD")["id"], 9)
        self.assertIsNone(ost.find_paired_chat(updates[:2], "AB12CD"))
        self.assertEqual(len(ost.pairing_code()), 6)

    def test_polling_advances_offset_until_code_arrives(self):
        batches = [
            [{"update_id": 10, "message": {"chat": {"id": 5, "type": "private"}, "text": "hi"}}],
            [{"update_id": 11, "message": {"chat": {"id": 7, "type": "private"}, "text": "XY34ZW"}}],
        ]
        seen = []

        def fake(method, url, data=None, headers=None, timeout=None):
            seen.append(dict(urllib.parse.parse_qsl(data.decode())))
            return 200, {}, json.dumps({"ok": True, "result": batches.pop(0)}).encode()
        with mock.patch.object(ost, "http_request", fake):
            chat = ost.wait_for_pairing(BOT_TOKEN, "XY34ZW", wait_seconds=60)
        self.assertEqual(chat["id"], 7)
        self.assertNotIn("offset", seen[0])
        self.assertEqual(seen[1]["offset"], "11")

    def test_conflict_explains_new_bot(self):
        def fake(method, url, data=None, headers=None, timeout=None):
            return 409, {}, b'{"ok": false, "description": "Conflict: terminated by other getUpdates request"}'
        with mock.patch.object(ost, "http_request", fake):
            with self.assertRaises(ost.AppError) as ctx:
                ost.wait_for_pairing(BOT_TOKEN, "AAAAAA", wait_seconds=5)
        self.assertIn("new bot", str(ctx.exception))


class ScheduleTests(unittest.TestCase):
    def test_launchd_plist(self):
        data = plistlib.loads(ost.launchd_plist("/usr/bin/python3", PurePosixPath("/x y/s'q.py"),
                                                PurePosixPath("/d d"), 5))
        self.assertEqual(data["Label"], ost.LAUNCHD_LABEL)
        self.assertEqual(data["ProgramArguments"], ["/usr/bin/python3", "/x y/s'q.py", "check"])
        self.assertEqual(data["StartInterval"], 300)
        self.assertEqual(data["EnvironmentVariables"], {"OURA_STRESS_HOME": "/d d"})

    def test_cron_line_quotes_paths_and_escapes_percent(self):
        line = ost.cron_line("/usr/bin/python3", PurePosixPath("/home/a b/it's 100%.py"), PurePosixPath("/d"), 10,
                             PurePosixPath("/d/check.log"))
        self.assertTrue(line.startswith("*/10 * * * * OURA_STRESS_HOME=/d "))
        self.assertIn("100\\%.py", line)
        self.assertNotIn("100%.py", line.replace("\\%", ""))
        self.assertTrue(line.endswith(ost.CRON_MARKER))

    def test_systemd_units(self):
        service, timer = ost.systemd_units("/usr/bin/python3", PurePosixPath("/s $x 5%.py"),
                                           PurePosixPath("/d 1"), 5)
        self.assertIn('ExecStart="/usr/bin/python3" "/s $$x 5%%.py" check', service)
        self.assertIn('Environment="OURA_STRESS_HOME=/d 1"', service)
        self.assertIn("OnUnitActiveSec=5min", timer)

    def test_scheduled_command_runs_with_minimal_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data with space"
            env = ost.scheduled_environment(ost.Paths(data))
            result = subprocess.run([sys.executable, str(ROOT / ost.SCRIPT_NAME), "check"],
                                    env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 1)
            self.assertIn("setup is not finished", result.stderr)
            self.assertTrue(data.is_dir())


if __name__ == "__main__":
    unittest.main()
