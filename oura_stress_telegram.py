#!/usr/bin/env python3
"""Oura Stress Alerts: Telegram alerts when your Oura Ring records more high stress.

Checks your Oura ring's daytime stress every few minutes and sends you a Telegram
message when Oura records more time in high stress today.

Standard library only, Python 3.9 or newer, macOS, Linux or Windows (experimental).
First run:  python3 oura_stress_telegram.py setup
"""
from __future__ import annotations

import argparse
import _thread
import ctypes
from ctypes import wintypes
import errno
import functools
import base64
import contextlib
import datetime as dt
import getpass
import hashlib
import html
import http.client
import http.server
import json
import os
import platform
import plistlib
import re
import secrets
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

# APP names saved data, the installed copy and scheduler jobs; keep it stable.
APP = "oura-stress-telegram"
PRODUCT_NAME = "Oura Stress Alerts"
VERSION = "0.2.3"
SCRIPT_NAME = "oura_stress_telegram.py"
BOT_PHOTO_NAME = "bot-avatar.jpg"
PROJECT_URL = "https://github.com/farhankhalaf/push-notifications-for-oura-ring-stress"

OURA_APPS_URL = "https://developer.ouraring.com/applications"
OURA_AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
OURA_TOKEN_URL = "https://api.ouraring.com/oauth/token"
OURA_STRESS_URL = "https://api.ouraring.com/v2/usercollection/daily_stress"
OURA_SCOPE = "daily"
TELEGRAM_API = "https://api.telegram.org"

DEFAULT_SETTINGS = {
    "quiet_start": "00:00",
    "quiet_end": "08:00",
    "interval_minutes": 5,
    "min_increase_minutes": 0,
    "redirect_port": 8765,
}
FAILURE_ALERT_THRESHOLD = 3
REFRESH_MARGIN_SECONDS = 600
DEFAULT_TOKEN_LIFETIME_SECONDS = 86400
HTTP_TIMEOUT_SECONDS = 20
CHECK_TIME_LIMIT_SECONDS = 120
DEFAULT_RETRY_AFTER_SECONDS = 300
MAX_RETRY_AFTER_SECONDS = 86400
INTERACTIVE_LOCK_WAIT_SECONDS = 60
OAUTH_WAIT_SECONDS = 300
TELEGRAM_CHAT_WAIT_SECONDS = 300
STALE_DATA_DAYS = 2

LAUNCHD_LABEL = "local.oura-stress-telegram"
SYSTEMD_UNIT = APP
CRON_MARKER = "# " + APP

BOT_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# --------------------------------------------------------------------------
# Errors and redaction
# --------------------------------------------------------------------------

class AppError(Exception):
    """A problem the user can act on. The message is safe to show and send."""


class NetworkError(AppError):
    pass


class TelegramError(AppError):
    pass


class OuraError(AppError):
    pass


class RateLimited(OuraError):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class ReconnectNeeded(AppError):
    """Oura no longer accepts our login. `action` is the command that fixes it:
    connect-oura for an expired login, setup when the Oura app keys are rejected."""

    def __init__(self, message: str, action: str = "connect-oura", reason: Optional[str] = None):
        super().__init__(message)
        self.action = action
        self.reason = reason


class RunTimeout(Exception):
    """Not an AppError, so no handler inside a check swallows it and keeps working."""


_SECRETS = set()


def remember_secret(value: Optional[str]) -> None:
    """Never print this value, nor its URL-encoded forms."""
    if isinstance(value, str) and len(value) >= 6:
        _SECRETS.update({value, urllib.parse.quote(value, safe=""),
                         urllib.parse.quote_plus(value)})


def redact(text: object) -> str:
    text = str(text)
    for value in sorted(_SECRETS, key=len, reverse=True):
        text = text.replace(value, "[redacted]")
    return BOT_TOKEN_RE.sub("[redacted]", text)


def log(message: str) -> None:
    stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"{stamp} {redact(message)}", file=sys.stderr, flush=True)


def say(message: str = "") -> None:
    print(redact(message), flush=True)


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Files: everything lives in one private directory
# --------------------------------------------------------------------------

class Paths:
    def __init__(self, root: Path):
        self.root = root
        self.config = root / "config.json"
        self.tokens = root / "tokens.json"
        self.state = root / "state.json"
        self.lock = root / "lock"
        self.last_run = root / "last_run.json"


def is_windows() -> bool:
    return os.name == "nt"


@functools.lru_cache(maxsize=1)
def _windows_api():
    """Typed Win32 entry points, loaded only by native Windows calls."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    void = ctypes.c_void_p
    pointer = ctypes.POINTER
    signatures = [
        (kernel, "GetCurrentProcess", [], wintypes.HANDLE),
        (kernel, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
        (kernel, "LocalFree", [void], void),
        (kernel, "CreateDirectoryW", [wintypes.LPCWSTR, void], wintypes.BOOL),
        (kernel, "GetConsoleMode", [wintypes.HANDLE, pointer(wintypes.DWORD)], wintypes.BOOL),
        (advapi, "OpenProcessToken", [wintypes.HANDLE, wintypes.DWORD,
                                      pointer(wintypes.HANDLE)], wintypes.BOOL),
        (advapi, "GetTokenInformation", [wintypes.HANDLE, ctypes.c_int, void,
                                         wintypes.DWORD, pointer(wintypes.DWORD)], wintypes.BOOL),
        (advapi, "ConvertSidToStringSidW", [void, pointer(wintypes.LPWSTR)], wintypes.BOOL),
        (advapi, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
         [wintypes.LPCWSTR, wintypes.DWORD, pointer(void), pointer(wintypes.DWORD)], wintypes.BOOL),
        (advapi, "ConvertSecurityDescriptorToStringSecurityDescriptorW",
         [void, wintypes.DWORD, wintypes.DWORD, pointer(wintypes.LPWSTR),
          pointer(wintypes.DWORD)], wintypes.BOOL),
        (advapi, "GetNamedSecurityInfoW", [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
                                          pointer(void), pointer(void), pointer(void),
                                          pointer(void), pointer(void)], wintypes.DWORD),
        (advapi, "GetSecurityDescriptorDacl", [void, pointer(wintypes.BOOL), pointer(void),
                                               pointer(wintypes.BOOL)], wintypes.BOOL),
        (advapi, "SetNamedSecurityInfoW", [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
                                          void, void, void, void], wintypes.DWORD),
    ]
    for library, name, args, result in signatures:
        function = getattr(library, name)
        function.argtypes, function.restype = args, result
    return kernel, advapi


@functools.lru_cache(maxsize=1)
def windows_user_sid() -> str:
    kernel, advapi = _windows_api()
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        if not size.value:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        text = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel.LocalFree(text)
    finally:
        kernel.CloseHandle(token)


def windows_acl(path: Path) -> str:
    kernel, advapi = _windows_api()
    descriptor = ctypes.c_void_p()
    error = advapi.GetNamedSecurityInfoW(str(path), 1, 4, None, None, None, None,
                                         ctypes.byref(descriptor))
    if error:
        raise ctypes.WinError(error)
    try:
        text = wintypes.LPWSTR()
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, 1, 4, ctypes.byref(text), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel.LocalFree(text)
    finally:
        kernel.LocalFree(descriptor)


def private_windows_acl(sddl: str, sid: str) -> bool:
    """Allow only the user, SYSTEM and local administrators; require usable access."""
    allowed = {sid, "SY", "BA", "S-1-5-18", "S-1-5-32-544"}
    aces = re.findall(r"\(([^()]*)\)", sddl)
    user_access = False
    if not sddl.startswith("D:") or not aces:
        return False
    for ace in aces:
        fields = ace.split(";")
        if len(fields) != 6 or fields[0] not in ("A", "D"):
            return False  # Do not guess the meaning of conditional/object ACEs.
        kind, flags, rights, _, _, principal = fields
        # SDDL abbreviates the built-in local Administrator/Guest account SIDs.
        # Accept the alias only when it identifies this exact current user.
        if (principal == "LA" and sid.endswith("-500")) or (principal == "LG" and sid.endswith("-501")):
            principal = sid
        if kind == "D":
            continue
        if principal not in allowed:
            return False
        if principal == sid and "IO" not in flags:
            full = rights == "FA"
            if rights.startswith("0x"):
                with contextlib.suppress(ValueError):
                    full = int(rights, 16) & 0x1F01FF == 0x1F01FF
            user_access = user_access or full
    return user_access


@contextlib.contextmanager
def _windows_descriptor(directory: bool):
    kernel, advapi = _windows_api()
    flags = "OICI" if directory else ""
    sddl = "D:P" + "".join(f"(A;{flags};FA;;;{sid})"
                            for sid in (windows_user_sid(), "SY", "BA"))
    descriptor = ctypes.c_void_p()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield descriptor
    finally:
        kernel.LocalFree(descriptor)


def _windows_set_private(path: Path, directory: bool) -> None:
    _, advapi = _windows_api()
    with _windows_descriptor(directory) as descriptor:
        present, defaulted, acl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present),
                                                ctypes.byref(acl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        error = advapi.SetNamedSecurityInfoW(str(path), 1, 4 | 0x80000000,
                                             None, None, acl, None)
        if error:
            raise ctypes.WinError(error)


def owned_data_name(name: str) -> bool:
    return name in OWNED_DATA_FILES or name == "lock" or any(
        name.startswith(f".{item}.") and name.endswith(".tmp") for item in OWNED_DATA_FILES)


def ensure_windows_private_dir(path: Path) -> None:
    """Provision a private leaf atomically; never rewrite an unrelated directory tree."""
    kernel, _ = _windows_api()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p),
                        ("inherit", wintypes.BOOL)]

        with _windows_descriptor(True) as descriptor:
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
            if not kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)):
                error = ctypes.get_last_error()
                if error != 183 or not path.is_dir():
                    raise ctypes.WinError(error)
    if not path.is_dir() or path.is_symlink():
        raise AppError(f"Use a dedicated local folder for saved settings: {path}")
    sid = windows_user_sid()
    if not private_windows_acl(windows_acl(path), sid):
        entries = list(path.iterdir())
        if any(not child.is_file() or child.is_symlink()
               or not (owned_data_name(child.name) or child.name == SCRIPT_NAME)
               for child in entries):
            raise AppError(f"Cannot make {path} private without changing unrelated files. "
                           "Choose a new empty local folder with --data-dir.")
        _windows_set_private(path, True)
        if not private_windows_acl(windows_acl(path), sid):
            raise AppError("Windows could not protect the settings folder. Use a local NTFS folder.")


def protect_windows_file(path: Path) -> None:
    if path.exists() and not private_windows_acl(windows_acl(path), windows_user_sid()):
        _windows_set_private(path, False)
        if not private_windows_acl(windows_acl(path), windows_user_sid()):
            raise AppError(f"Windows could not protect {path}. Use a local NTFS folder.")


def windows_local_dir() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


def powershell_quote(value: str) -> str:
    # PowerShell also recognizes these typographic characters as single quotes.
    return "'" + re.sub("['\u2018\u2019\u201a\u201b]", lambda m: m[0] * 2, value) + "'"


def windows_cleanup_command(root: Path) -> str:
    paths = [powershell_quote(str(root / name)) for name in OWNED_DATA_FILES]
    return "Remove-Item -LiteralPath " + ", ".join(paths) + " -Force -ErrorAction SilentlyContinue"


def windows_runtime_check(paths: Paths) -> None:
    """Reject Store package virtualization before setup can save any credentials."""
    prefixes = (sys.executable, sys.prefix, sys.base_prefix)
    root = str(paths.root.resolve())
    store = any("windowsapps" in re.split(r"[\\/]", str(p).lower()) for p in prefixes)
    cache = "\\packages\\" in root.lower() and "\\localcache\\" in root.lower()
    if store or cache:
        raise AppError("This Microsoft Store Python or private package folder cannot be used "
                       "for background checks. Install a runtime with the Python install "
                       "manager from python.org and run setup with that runtime. "
                       "To remove saved files from the displayed folder in PowerShell: "
                       + windows_cleanup_command(Path(root)))
    legacy = Path.home() / ".config" / APP
    if paths.root == default_root() and not paths.config.exists() and (legacy / "config.json").exists():
        raise AppError("Saved settings exist in the old folder. Reuse them with: "
                       + command_for("setup", Paths(legacy), prefer_installed=False)
                       + ". Or remove those saved files in PowerShell: "
                       + windows_cleanup_command(legacy.resolve()))


def replace_private_file(source: str, target: Path) -> None:
    deadline = time.monotonic() + 1
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if not is_windows() or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def default_paths() -> Paths:
    override = os.environ.get("OURA_STRESS_HOME")
    if override:
        return Paths(Path(override).expanduser().resolve())
    if is_windows():
        return Paths(default_root())
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Paths((Path(base).expanduser() / APP).resolve())


def ensure_private_dir(path: Path) -> None:
    if is_windows():
        ensure_windows_private_dir(path)
    else:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)


def read_json(path: Path) -> dict:
    try:
        if is_windows():
            protect_windows_file(path)
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise AppError(f"Could not read {path}: {exc}") from None
    if not isinstance(value, dict):
        raise AppError(f"{path} is not a JSON object")
    return value


def write_json_private(path: Path, data: dict) -> None:
    """Atomic write: a crash leaves either the old file or the new one, never half."""
    ensure_private_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        if is_windows():
            protect_windows_file(Path(tmp))
        else:
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1  # fdopen now owns and closes the descriptor on every exit.
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        replace_private_file(tmp, path)
    finally:
        if fd != -1:
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    if not is_windows():
        with contextlib.suppress(OSError):
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)


@contextlib.contextmanager
def run_lock(paths: Paths, wait_seconds: float = 0) -> Iterator[bool]:
    """One lock for every command that reads or rotates Oura tokens.

    Yields True when held. With wait_seconds=0 it yields False at once if another
    process holds it; otherwise it retries until the wait runs out.
    """
    ensure_private_dir(paths.root)
    if is_windows():
        import msvcrt
    else:
        try:
            import fcntl
        except ImportError:
            raise AppError("This platform has no supported file lock.") from None
    handle = open(paths.lock, "a+b")
    held = False
    try:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                if is_windows():
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.25)
        if is_windows():
            # Token writers all hold this lock. Do not sweep config/receipt temps:
            # those can legitimately be in use by another command.
            for stale in paths.root.glob(".tokens.json.*.tmp"):
                with contextlib.suppress(OSError):
                    stale.unlink()
        yield True
    finally:
        if held and is_windows():
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                handle.close()
        else:
            handle.close()


@contextlib.contextmanager
def interactive_lock(paths: Paths) -> Iterator[None]:
    with run_lock(paths, wait_seconds=INTERACTIVE_LOCK_WAIT_SECONDS) as acquired:
        if not acquired:
            raise AppError("A background check is still running. Try again in a minute.")
        yield


def load_config(paths: Paths) -> dict:
    config = read_json(paths.config)
    for key in ("telegram_bot_token", "oura_client_secret"):
        remember_secret(config.get(key))
    return config


def load_tokens(paths: Paths) -> dict:
    tokens = read_json(paths.tokens)
    remember_secret(tokens.get("access_token"))
    remember_secret(tokens.get("refresh_token"))
    return tokens


def load_state(paths: Paths) -> dict:
    try:
        return read_json(paths.state)
    except AppError as exc:
        log(f"WARN: {exc}; starting with fresh state")
        return {}


def settings_of(config: dict) -> dict:
    merged = dict(DEFAULT_SETTINGS)
    merged.update(config.get("settings") or {})
    return merged


# --------------------------------------------------------------------------
# Commands shown to the user always use absolute paths
# --------------------------------------------------------------------------

def installed_script_path() -> Path:
    if is_windows():
        return windows_local_dir() / (APP + "-app") / SCRIPT_NAME
    return Path.home() / ".local" / "share" / APP / SCRIPT_NAME


def python_path() -> str:
    """The interpreter the background job should use.

    Keep symlinks: a resolved Homebrew path points into a versioned folder that is
    deleted on upgrade. Apple's developer-tools Python is reached through the
    /usr/bin/python3 shim, which survives Xcode and Command Line Tools updates.
    """
    exe = os.path.abspath(sys.executable or shutil.which("python3") or "/usr/bin/python3")
    if is_windows():
        path = Path(exe)
        if path.name.lower() == "pythonw.exe":
            path = path.with_name("python.exe")
        return str(path)
    apple = ("/Library/Developer/CommandLineTools/" in exe
             or (".app/Contents/Developer/" in exe and "Xcode" in exe))
    if apple and os.access("/usr/bin/python3", os.X_OK):
        return "/usr/bin/python3"
    return exe


def default_root() -> Path:
    if is_windows():
        return (windows_local_dir() / APP).resolve()
    return (Path.home() / ".config" / APP).resolve()


def command_for(action: str, paths: Optional[Paths] = None, *, prefer_installed: bool = True) -> str:
    """An absolute command for POSIX shells or Windows PowerShell."""
    script = installed_script_path()
    if not prefer_installed or not script.exists():
        script = Path(__file__).resolve()
    if is_windows():
        root = (paths or default_paths()).root
        return "& " + " ".join(powershell_quote(str(value)) for value in
                                (python_path(), script, "--data-dir", root, action))
    command = f"{shlex.quote(python_path())} {shlex.quote(str(script))} {action}"
    root = (paths or default_paths()).root
    if root != default_root():
        command = f"OURA_STRESS_HOME={shlex.quote(str(root))} {command}"
    return command


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # never forward tokens elsewhere
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def http_request(method: str, url: str, *, data: Optional[bytes] = None,
                 headers: Optional[Dict[str, str]] = None,
                 timeout: float = HTTP_TIMEOUT_SECONDS) -> Tuple[int, Dict[str, str], bytes]:
    """Returns (status, headers with lower-case names, body). Raises NetworkError."""
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    request.add_header("User-Agent", f"{APP}/{VERSION}")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return (response.status, {k.lower(): v for k, v in response.headers.items()},
                    response.read())
    except urllib.error.HTTPError as exc:
        body = b""
        with contextlib.suppress(OSError, http.client.HTTPException, ValueError):
            body = exc.read()
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, body
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        reason = str(getattr(exc, "reason", exc)) or type(exc).__name__
        host = urllib.parse.urlsplit(url).hostname
        if "CERTIFICATE_VERIFY_FAILED" in reason:
            if is_windows():
                raise NetworkError("Python cannot verify secure connections. Check the "
                                   "Windows date and time, install Windows Update certificate "
                                   "updates, then try again. On a managed computer, ask its "
                                   "administrator about the trusted certificate store. "
                                   "Do not turn off certificate verification.") from None
            raise NetworkError(
                "Python cannot verify secure connections on this computer. If you "
                "installed Python from python.org, open its folder in Applications and "
                "run 'Install Certificates.command', then try again.") from None
        raise NetworkError(f"Could not reach {host}: {redact(reason)}") from None


def parse_json_body(body: bytes) -> Optional[dict]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def form(data: Dict[str, str]) -> bytes:
    return urllib.parse.urlencode(data).encode("utf-8")


FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------

def telegram_call(token: str, method: str, params: Optional[Dict[str, str]] = None,
                  timeout: float = HTTP_TIMEOUT_SECONDS):
    remember_secret(token)
    status, _, body = http_request("POST", f"{TELEGRAM_API}/bot{token}/{method}",
                                   data=form(params or {}), headers=FORM_HEADERS,
                                   timeout=timeout)
    return telegram_result(status, body)


def telegram_result(status: int, body: bytes):
    payload = parse_json_body(body)
    if payload is None:
        raise TelegramError(f"Telegram gave an unreadable reply (HTTP {status})")
    if not payload.get("ok"):
        description = str(payload.get("description") or "unknown error")[:200]
        raise TelegramError(f"Telegram said: {description} (HTTP {status})")
    return payload.get("result")


def set_bot_photo(config: dict, *, only_if_missing: bool = False) -> bool:
    """Upload the bundled JPEG. Return False when keeping an existing photo."""
    token = config.get("telegram_bot_token")
    if not token:
        raise AppError("Set up Telegram first, then run set-bot-photo again.")
    remember_secret(token)
    if only_if_missing:
        bot = telegram_call(token, "getMe")
        if not isinstance(bot, dict) or not isinstance(bot.get("id"), int):
            raise TelegramError("Telegram did not return the bot's identity.")
        photos = telegram_call(token, "getUserProfilePhotos", {
            "user_id": str(bot["id"]), "limit": "1",
        })
        count = photos.get("total_count") if isinstance(photos, dict) else None
        if not isinstance(count, int) or count < 0:
            raise TelegramError("Telegram did not return the bot's photo count.")
        if count:
            return False
    photo_path = Path(__file__).resolve().with_name(BOT_PHOTO_NAME)
    try:
        with photo_path.open("rb") as handle:
            photo = handle.read(10 * 1024 * 1024 + 1)
    except FileNotFoundError:
        raise AppError(f"Keep {BOT_PHOTO_NAME} beside this script, or run set-bot-photo "
                       "from the downloaded project folder.") from None
    if not photo.startswith(b"\xff\xd8\xff") or len(photo) > 10 * 1024 * 1024:
        raise AppError("The bundled bot image must be a JPEG smaller than 10 MB.")
    boundary = "oura-photo-" + secrets.token_hex(24)
    metadata = json.dumps({"type": "static", "photo": "attach://avatar"})
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"\r\n\r\n"
            f"{metadata}\r\n--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"avatar\"; filename=\"{BOT_PHOTO_NAME}\"\r\n"
            "Content-Type: image/jpeg\r\n\r\n").encode() + photo + (
                f"\r\n--{boundary}--\r\n").encode()
    status, _, response = http_request(
        "POST", f"{TELEGRAM_API}/bot{token}/setMyProfilePhoto", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Accept": "application/json"})
    if telegram_result(status, response) is not True:
        raise TelegramError("Telegram did not confirm the bot photo update.")
    return True


def setup_bot_photo(config: dict) -> None:
    """Cosmetic setup failure must not interrupt pairing or Oura setup."""
    try:
        if set_bot_photo(config, only_if_missing=True):
            say("Added the ring profile picture to your Telegram bot.")
    except (AppError, OSError) as exc:
        say(f"Skipped the bot picture: {redact(exc)}")
        say("Alerts can still work. To retry the picture, run set-bot-photo from this project.")


def send_telegram(config: dict, text: str, state: Optional[dict] = None) -> bool:
    """Send a message. When `state` is given, record or clear delivery_error."""
    try:
        telegram_call(config["telegram_bot_token"], "sendMessage", {
            "chat_id": str(config["telegram_chat_id"]),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        })
    except (AppError, KeyError) as exc:
        reason = redact(f"Telegram send failed: {exc}")
        log(f"WARN: {reason}")
        if state is not None:
            state["delivery_error"] = f"{now_iso()} {reason}"
        return False
    if state is not None:
        state["delivery_error"] = None
    return True


# --------------------------------------------------------------------------
# Oura login (OAuth2) and data
# --------------------------------------------------------------------------

def redirect_uri(port: int) -> str:
    return f"http://localhost:{port}/callback"


def token_request(config: dict, fields: Dict[str, str]) -> dict:
    for key in ("code", "code_verifier", "refresh_token"):
        remember_secret(fields.get(key))
    remember_secret(config.get("oura_client_secret"))
    fields = dict(fields, client_id=config["oura_client_id"],
                  client_secret=config["oura_client_secret"])
    status, headers, body = http_request("POST", OURA_TOKEN_URL, data=form(fields),
                                         headers=FORM_HEADERS)
    payload = parse_json_body(body) or {}
    if status == 429:
        wait = retry_after_seconds(headers)
        raise RateLimited(f"Oura rate limit reached (HTTP 429); pausing {wait} s", wait)
    if status == 200 and isinstance(payload.get("access_token"), str):
        remember_secret(payload["access_token"])
        remember_secret(payload.get("refresh_token"))
        return payload
    error = payload.get("error") if isinstance(payload.get("error"), str) else ""
    error = re.sub(r"[^a-z_]", "", error.lower())[:40]
    if status in (400, 401) and error == "invalid_grant":
        raise ReconnectNeeded(f"Oura no longer accepts this login ({error})")
    # The current Oura provider reports a spent single-use refresh token as
    # invalid_request. Repeating it cannot recover the lost token response.
    if (status in (400, 401) and error == "invalid_request"
            and fields.get("grant_type") == "refresh_token"):
        raise ReconnectNeeded(f"Oura could not renew the saved login ({error})")
    if status in (400, 401) and error in ("invalid_client", "unauthorized_client"):
        raise ReconnectNeeded(f"Oura rejected the saved Oura app keys ({error})", action="setup")
    raise OuraError(f"Oura login request failed (HTTP {status}{', ' + error if error else ''})")


def tokens_from_response(payload: dict, now: float, previous_refresh: Optional[str] = None) -> dict:
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, bool) or not isinstance(expires_in, (int, float)) or expires_in <= 0:
        expires_in = DEFAULT_TOKEN_LIFETIME_SECONDS
    refresh = payload.get("refresh_token")
    return {
        "access_token": payload["access_token"],
        "refresh_token": refresh if isinstance(refresh, str) and refresh else previous_refresh,
        "expires_at": int(now + expires_in),
        "obtained_at": int(now),
    }


def retry_after_seconds(headers: Dict[str, str]) -> int:
    try:
        value = int(str(headers.get("retry-after", "")).strip())
    except ValueError:
        value = DEFAULT_RETRY_AFTER_SECONDS
    return max(1, min(value, MAX_RETRY_AFTER_SECONDS))


class OuraClient:
    """Create only while holding the run lock: it reads and may rotate tokens."""

    def __init__(self, paths: Paths, config: dict, clock=None):
        self.paths = paths
        self.config = config
        self.clock = clock or time.time
        self.tokens = load_tokens(paths)

    def access_token(self, force_refresh: bool = False) -> str:
        tokens = self.tokens
        if not tokens.get("access_token") and not tokens.get("refresh_token"):
            raise ReconnectNeeded("Oura is not connected yet")
        now = self.clock()
        expiring = int(tokens.get("expires_at") or 0) - now < REFRESH_MARGIN_SECONDS
        if force_refresh or expiring or not tokens.get("access_token"):
            refresh = tokens.get("refresh_token")
            if not refresh:
                raise ReconnectNeeded("Oura login expired and cannot be renewed automatically")
            payload = token_request(self.config, {"grant_type": "refresh_token",
                                                  "refresh_token": refresh})
            # The old refresh token is already spent: save the new pair before anything else.
            self.tokens = tokens_from_response(payload, now)
            write_json_private(self.paths.tokens, self.tokens)
        return self.tokens["access_token"]

    def stress_high_today(self, today: dt.date) -> Optional[int]:
        """Seconds in high stress for `today`, or None when Oura has nothing yet."""
        query = urllib.parse.urlencode({
            "start_date": (today - dt.timedelta(days=1)).isoformat(),
            "end_date": (today + dt.timedelta(days=1)).isoformat(),
        })
        for attempt in (1, 2):
            token = self.access_token(force_refresh=attempt == 2)
            status, headers, body = http_request("GET", f"{OURA_STRESS_URL}?{query}", headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json"})
            if status in (401, 403):
                detail = (parse_json_body(body) or {}).get("detail")
                if (isinstance(detail, str)
                        and re.search(r"\bnot authori[sz]ed (?:to )?access (?:the )?daily scope\b",
                                      detail, re.IGNORECASE)):
                    raise ReconnectNeeded(
                        "Oura Daily permission was not granted. Reconnect, turn on "
                        "'Sleep, readiness, and activity', then press Allow.",
                        reason="missing_daily_scope")
            if status == 401 and attempt == 1:
                continue
            if status == 401:
                raise ReconnectNeeded("Oura rejected the login even after renewing it")
            if status == 403:
                raise OuraError("Oura refused access to stress data (HTTP 403). Check that "
                                "your Oura Membership is active, then reconnect and turn on "
                                "'Sleep, readiness, and activity' before pressing Allow.")
            if status == 429:
                wait = retry_after_seconds(headers)
                raise RateLimited(f"Oura rate limit reached (HTTP 429); pausing {wait} s", wait)
            if not 200 <= status < 300:
                raise OuraError(f"Oura API returned HTTP {status}")
            payload = parse_json_body(body)
            items = payload.get("data") if payload else None
            if not isinstance(items, list):
                raise OuraError("Oura API returned an unexpected response")
            for item in items:
                if isinstance(item, dict) and item.get("day") == today.isoformat():
                    value = item.get("stress_high")
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        return value
                    return None
            return None
        raise AssertionError("unreachable")


# --------------------------------------------------------------------------
# The alert rule
# --------------------------------------------------------------------------

def minutes(seconds: int) -> int:
    """Whole minutes, never shown as 0 for a real increase."""
    return max(1, seconds // 60)


def baseline_initialized(state: dict) -> bool:
    """Recognize new state explicitly and preserve established pre-marker installs."""
    if "baseline_initialized" in state:
        return state["baseline_initialized"] is True
    day = state.get("last_date")
    value = state.get("last_stress_high")
    if not isinstance(day, str) or type(value) is not int or value < 0:
        return False
    try:
        # Require the same canonical date on all supported Python versions.
        return dt.date.fromisoformat(day).isoformat() == day
    except ValueError:
        return False


def plan_alert(stress_high: Optional[int], state: dict, today: str,
               min_increase_minutes: int = 0) -> Tuple[Optional[str], int]:
    """Return (message or None, baseline to keep without a new delivery).

    A new install silently records its first valid total. Thereafter the baseline
    is today's highest stress_high already accounted for. It starts at 0 each new
    day and only moves up. Any increase (or one of at least min_increase_minutes,
    when set) produces one message.
    """
    if stress_high is not None and not baseline_initialized(state):
        return None, stress_high
    baseline = 0
    if state.get("last_date") == today:
        stored = state.get("last_stress_high", 0)
        baseline = stored if isinstance(stored, int) and stored >= 0 else 0
    if stress_high is None or stress_high <= baseline:
        return None, baseline
    if stress_high - baseline < max(0, int(min_increase_minutes)) * 60:
        return None, baseline
    total = minutes(stress_high)
    if baseline == 0:
        message = "\U0001F534 <b>Oura recorded high stress</b>"
    else:
        added = minutes(stress_high - baseline)
        message = (f"\U0001F534 <b>More high stress recorded:</b> +{added} min "
                   f"({total} min today).\n\nConsider stepping away for a few minutes.")
    return message, baseline


def parse_hhmm(value: str) -> dt.time:
    match = HHMM_RE.match(str(value))
    if not match:
        raise AppError(f"Time must look like 08:00 or 22:30, got {value!r}")
    return dt.time(int(match.group(1)), int(match.group(2)))


def in_quiet_hours(now: dt.time, start: str, end: str) -> bool:
    begin, finish = parse_hhmm(start), parse_hhmm(end)
    now = now.replace(second=0, microsecond=0, tzinfo=None)
    if begin == finish:
        return False
    if begin < finish:
        return begin <= now < finish
    return now >= begin or now < finish


# --------------------------------------------------------------------------
# One scheduled check
# --------------------------------------------------------------------------

def reconnect_notice(paths: Paths, action: str = "connect-oura",
                     reason: Optional[str] = None) -> str:
    what = (f"the saved Oura app keys (check your app at {OURA_APPS_URL}, then enter "
            "its Client ID and Secret again)" if action == "setup" else "the saved login")
    consent = ("\n\nOn the consent screen, turn on 'Sleep, readiness, and activity', "
               "then press Allow." if action == "connect-oura" else "")
    explanation = ("Oura did not grant the Daily permission." if reason == "missing_daily_scope"
                   else f"Oura no longer accepts {what}.")
    return (f"\u26A0\uFE0F <b>{PRODUCT_NAME} is paused:</b> {explanation}"
            "\n\nTo fix it, run this on your computer:\n"
            f"<code>{html.escape(command_for(action, paths))}</code>{consent}")


def record_failure(paths: Paths, config: dict, state: dict, reason: str) -> int:
    log(f"ERROR: {reason}")
    failures = int(state.get("consecutive_failures") or 0) + 1
    state.update(consecutive_failures=failures, last_error=redact(reason),
                 last_check=now_iso())
    if failures >= FAILURE_ALERT_THRESHOLD and not state.get("failure_alerted"):
        text = (f"\u26A0\uFE0F <b>{PRODUCT_NAME} is having trouble</b> "
                f"({failures} checks in a row failed).\n\nLatest error: "
                f"{html.escape(redact(reason))}\n\nFor details, run this on your computer:\n"
                f"<code>{html.escape(command_for('status', paths))}</code>")
        if send_telegram(config, text, state):
            state["failure_alerted"] = True
    write_json_private(paths.state, state)
    return 1


def record_run(paths: Paths, invoked_at: float, outcome: str, run_id: Optional[str] = None) -> None:
    """Remember what the latest check did, so install and status can tell a real
    check from a skip."""
    with contextlib.suppress(OSError):
        write_json_private(paths.last_run, {"invoked_at": invoked_at, "finished_at": time.time(),
                                            "outcome": redact(outcome)[:300], "run_id": run_id})


def read_last_run(paths: Paths) -> dict:
    try:
        return read_json(paths.last_run)
    except AppError:
        return {}


def run_check(paths: Paths, now: Optional[dt.datetime] = None, verify: bool = False,
              run_id: Optional[str] = None) -> int:
    """One check. verify=True (used by install) waits for the lock and ignores quiet hours."""
    invoked_at = time.time()
    wait = INTERACTIVE_LOCK_WAIT_SECONDS if verify else 0
    try:
        with run_lock(paths, wait_seconds=wait) as acquired:
            if not acquired:
                log("SKIP: another check is already running")
                code, outcome = 0, "skipped: another check was running"
            else:
                try:
                    code, outcome = _run_check_locked(paths, now, verify)
                except RunTimeout as exc:
                    # Still holding the lock: record the failure, start no network work.
                    log(f"ERROR: {exc}")
                    state = load_state(paths)
                    failures = int(state.get("consecutive_failures") or 0) + 1
                    state.update(consecutive_failures=failures, last_error=str(exc),
                                 last_check=now_iso())
                    with contextlib.suppress(OSError):
                        write_json_private(paths.state, state)
                    code, outcome = 1, f"error: {exc}"
    except RunTimeout as exc:  # the deadline passed while waiting for the lock
        log(f"ERROR: {exc}")
        code, outcome = 1, f"error: {exc}"
    record_run(paths, invoked_at, outcome, run_id)
    return code


def _run_check_locked(paths: Paths, now: Optional[dt.datetime], verify: bool) -> Tuple[int, str]:
    """The body of one check. The caller holds the run lock."""
    config = load_config(paths)
    missing = [key for key in ("telegram_bot_token", "telegram_chat_id",
                               "oura_client_id", "oura_client_secret") if not config.get(key)]
    if missing:
        log(f"ERROR: setup is not finished (missing {', '.join(missing)}). "
            f"Run: {command_for('setup', paths)}")
        return 1, "error: setup is not finished"
    settings = settings_of(config)
    now = now or dt.datetime.now().astimezone()
    if not verify:
        try:
            if in_quiet_hours(now.time(), settings["quiet_start"], settings["quiet_end"]):
                return 0, "skipped: quiet hours"
        except AppError as exc:
            log(f"WARN: ignoring quiet hours: {exc}")
    state = load_state(paths)

    if state.get("needs_reconnect"):
        # Paused: no Oura requests, but keep trying until the user hears about it.
        if not state.get("reconnect_notice_sent"):
            action = state.get("reconnect_action") or "connect-oura"
            state["reconnect_notice_sent"] = send_telegram(
                config, reconnect_notice(paths, action, state.get("reconnect_reason")), state)
            write_json_private(paths.state, state)
        action = state.get("reconnect_action") or "connect-oura"
        log(f"ERROR: Oura needs to be reconnected. Run: {command_for(action, paths)}")
        return 1, "paused: Oura needs to be reconnected"

    next_allowed = state.get("next_oura_request_at")
    if isinstance(next_allowed, (int, float)) and now.timestamp() < next_allowed:
        until = dt.datetime.fromtimestamp(next_allowed).astimezone()
        return 0, f"skipped: Oura asked us to wait until {until.isoformat(timespec='minutes')}"

    today = now.date().isoformat()
    try:
        stress_high = read_oura_locked(paths, config, now, state)
    except ReconnectNeeded as exc:
        log(f"ERROR: {exc}")
        state.update(needs_reconnect=True, reconnect_action=exc.action,
                     reconnect_reason=exc.reason,
                     last_error=redact(exc), last_check=now_iso())
        state["reconnect_notice_sent"] = send_telegram(
            config, reconnect_notice(paths, exc.action, exc.reason), state)
        write_json_private(paths.state, state)
        return 1, "paused: Oura needs to be reconnected"
    except RateLimited as exc:
        return record_failure(paths, config, state, str(exc)), f"error: {exc}"
    except (AppError, OSError) as exc:
        # OSError: for example a renewed Oura login that could not be saved. The next
        # run then finds the old, spent login and lands on the reconnect path.
        return record_failure(paths, config, state, str(exc)), f"error: {exc}"

    if state.get("failure_alerted"):
        send_telegram(config, f"\u2705 {PRODUCT_NAME} is working again.", state)
    message, baseline = plan_alert(stress_high, state, today,
                                   int(settings.get("min_increase_minutes") or 0))
    new_baseline = baseline
    outcome = "ok"
    if message:
        if send_telegram(config, message, state):
            new_baseline = stress_high
            outcome = "ok: alert sent"
            log(f"ALERT sent: {stress_high // 60} min in high stress today")
        else:
            # The baseline stays, so a later check today retries any increase
            # that is still outstanding.
            outcome = "degraded: the Telegram alert failed"
    # None must never downgrade an established or legacy install. Persist false
    # for a new no-data run so its date/zero bookkeeping cannot look like legacy.
    initialized = baseline_initialized(state) or stress_high is not None
    state.update(last_date=today, last_stress_high=new_baseline, last_check=now_iso(),
                 baseline_initialized=initialized,
                 consecutive_failures=0, failure_alerted=False, last_error=None,
                 needs_reconnect=False, reconnect_notice_sent=False, reconnect_reason=None,
                 next_oura_request_at=None)
    if stress_high is not None:
        state.update(last_seen_stress_high=stress_high, last_data_day=today)
    write_json_private(paths.state, state)
    return 0, outcome


def oura_pause_message(state: dict, now: float) -> Optional[str]:
    pause = state.get("next_oura_request_at")
    if isinstance(pause, (int, float)) and now < pause:
        until = dt.datetime.fromtimestamp(pause).astimezone().isoformat(timespec="minutes")
        return f"Oura asked us to wait until {until}"
    return None


def read_oura_locked(paths: Paths, config: dict, now: dt.datetime, state: dict) -> Optional[int]:
    """Today's stress_high. Caller holds the run lock and saves `state` afterwards;
    a new Oura rate limit is recorded in `state` before the error is raised."""
    try:
        return OuraClient(paths, config).stress_high_today(now.date())
    except RateLimited as exc:
        state["next_oura_request_at"] = int(now.timestamp()) + exc.retry_after
        raise


def _raise_timeout(signum, frame):
    raise RunTimeout(f"check took longer than {CHECK_TIME_LIMIT_SECONDS} s and was stopped")


@contextlib.contextmanager
def windows_time_limit(seconds: int) -> Iterator[None]:
    """Soft deadline: Windows delivers the interrupt after blocking native work."""
    previous = signal.getsignal(signal.SIGINT)
    expired, disarmed = threading.Event(), threading.Event()

    def interrupt():
        if not disarmed.is_set():
            expired.set()
            _thread.interrupt_main()

    def handle_interrupt(signum, frame):
        if disarmed.is_set():
            return
        if expired.is_set():
            _raise_timeout(signum, frame)
        if callable(previous):
            previous(signum, frame)
        elif previous != signal.SIG_IGN:
            raise KeyboardInterrupt

    timer = threading.Timer(seconds, interrupt)
    timer.daemon = True
    signal.signal(signal.SIGINT, handle_interrupt)
    timer.start()
    try:
        yield
    finally:
        # Drain a pending timer interrupt while our disarmed handler still owns it.
        disarmed.set()
        timer.cancel()
        timer.join()
        expired.is_set()
        signal.signal(signal.SIGINT, previous)


def windows_console_available() -> bool:
    if sys.stdin is None:
        return False
    try:
        import msvcrt
        kernel, _ = _windows_api()
        mode = wintypes.DWORD()
        return bool(kernel.GetConsoleMode(msvcrt.get_osfhandle(sys.stdin.fileno()),
                                          ctypes.byref(mode)))
    except (OSError, ValueError, AttributeError):
        return False


class WindowsConsoleLine:
    """Poll hidden paste input without a thread that outlives the OAuth prompt."""
    def __init__(self):
        self.characters = []
        self.extended = False

    def poll(self) -> Optional[str]:
        import msvcrt
        for _ in range(8192):
            if not msvcrt.kbhit():
                return None
            character = msvcrt.getwch()
            if self.extended:
                self.extended = False
            elif character in ("\x00", "\xe0"):
                self.extended = True
            elif character == "\x03":
                raise KeyboardInterrupt
            elif character in ("\r", "\n"):
                line = "".join(self.characters)
                self.characters.clear()
                return line
            elif character == "\b":
                if self.characters:
                    self.characters.pop()
            elif character.isprintable():
                self.characters.append(character)
                if len(self.characters) > 8192:
                    self.characters.clear()
                    raise AppError("The pasted address is too long. Run the command again.")
        return None

    def discard(self) -> None:
        import msvcrt
        self.characters.clear()
        while msvcrt.kbhit():
            msvcrt.getwch()


@contextlib.contextmanager
def time_limit(seconds: int) -> Iterator[None]:
    if is_windows():
        with windows_time_limit(seconds):
            yield
        return
    if not hasattr(signal, "SIGALRM"):
        raise AppError("This platform has no supported check timeout.")
    previous = signal.signal(signal.SIGALRM, _raise_timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


# --------------------------------------------------------------------------
# Interactive helpers
# --------------------------------------------------------------------------

def interactive() -> bool:
    return (windows_console_available() if is_windows() else
            sys.stdin is not None and sys.stdin.isatty())


def ask(prompt: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or (default or "")


def ask_yes(prompt: str, default: bool = True) -> bool:
    if not interactive():
        return default
    answer = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not answer else answer in ("y", "yes")


def ask_secret(prompt: str, env_name: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if value:
        say(f"Using {env_name} from the environment.")
        return value
    if not interactive():
        raise AppError(f"Run setup in your own terminal window, or set {env_name}.")
    value = getpass.getpass(f"{prompt} (typing is hidden; paste, then press Enter): ").strip()
    if not value:
        raise AppError("Nothing was entered.")
    return value


def heading(text: str) -> None:
    say()
    say(text)
    say("-" * len(text))


# --------------------------------------------------------------------------
# Setup: Telegram
# --------------------------------------------------------------------------

def pairing_code() -> str:
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(6))


def find_paired_chat(updates, code: str) -> Optional[dict]:
    """The private chat that sent a message containing the pairing code."""
    for update in updates or []:
        if not isinstance(update, dict):
            continue
        for key in ("message", "edited_message"):
            message = update.get(key)
            if not isinstance(message, dict):
                continue
            chat = message.get("chat")
            text = message.get("text")
            if (isinstance(chat, dict) and chat.get("type") == "private" and "id" in chat
                    and isinstance(text, str) and code in text.upper()):
                return chat
    return None


def wait_for_pairing(token: str, code: str, wait_seconds: int = TELEGRAM_CHAT_WAIT_SECONDS,
                     clock=time.monotonic) -> dict:
    deadline = clock() + wait_seconds
    offset = None
    while True:
        remaining = int(deadline - clock())
        if remaining <= 0:
            raise AppError("The pairing code did not reach the bot in time. Run setup "
                           "again and send the code to your bot as a message.")
        poll = max(1, min(20, remaining))
        params = {"timeout": str(poll), "allowed_updates": '["message","edited_message"]'}
        if offset is not None:
            params["offset"] = str(offset)
        try:
            updates = telegram_call(token, "getUpdates", params, timeout=poll + 15)
        except TelegramError as exc:
            if "409" in str(exc) or "Conflict" in str(exc):
                raise AppError("This bot is already used by another program (it has a "
                               "webhook or another app reads its messages). Create a new "
                               "bot with @BotFather just for these alerts.") from None
            raise
        chat = find_paired_chat(updates, code)
        if chat:
            return chat
        ids = [u.get("update_id") for u in updates or [] if isinstance(u, dict)
               and isinstance(u.get("update_id"), int)]
        if ids:
            offset = max(ids) + 1


def setup_telegram(config: dict) -> None:
    heading("Step 1 of 3: Telegram")
    if config.get("telegram_bot_token") and config.get("telegram_chat_id"):
        if ask_yes("Telegram is already set up. Keep it?"):
            setup_bot_photo(config)
            return
    say("1. In Telegram, open a chat with @BotFather (the official bot with a blue check).")
    say(f"2. Send /newbot, name it {PRODUCT_NAME}, then a username ending in 'bot'.")
    say("3. BotFather replies with a token that looks like 123456789:ABCdef...")
    token = ask_secret("Paste the bot token", "TELEGRAM_BOT_TOKEN")
    remember_secret(token)
    try:
        bot = telegram_call(token, "getMe") or {}
    except TelegramError as exc:
        raise AppError(f"That token did not work ({exc}). Copy it again from BotFather.") from None
    username = bot.get("username", "your bot")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if chat_id:
        say("Using TELEGRAM_CHAT_ID from the environment.")
    else:
        code = pairing_code()
        say()
        say(f"4. Open https://t.me/{username} in Telegram and press Start.")
        say(f"5. Send this pairing code to the bot as a message:   {code}")
        say(f"Waiting up to {TELEGRAM_CHAT_WAIT_SECONDS // 60} minutes...")
        chat = wait_for_pairing(token, code)
        chat_id = str(chat["id"])
        name = chat.get("first_name") or chat.get("username") or "you"
        say(f"Paired with {name}.")
    config.update(telegram_bot_token=token, telegram_chat_id=chat_id)
    setup_bot_photo(config)
    if not send_telegram(config, f"\u2705 {PRODUCT_NAME} will send stress alerts to this chat."):
        raise AppError("Could not send a message to that chat. Check the bot and try again.")
    if interactive() and not ask_yes("We sent you a Telegram message. Did it arrive?"):
        raise AppError("The message did not arrive. Run setup again.")


# --------------------------------------------------------------------------
# Setup: Oura
# --------------------------------------------------------------------------

class _CallbackServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = not is_windows()
    daemon_threads = True
    block_on_close = False  # an idle browser connection must not block shutdown


class _CallbackServerV6(_CallbackServer):
    address_family = socket.AF_INET6


def _callback_handler(expected_state: str, result: dict, done: threading.Event):
    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = 10  # seconds to wait for a request on an accepted connection

        def log_message(self, *args):  # the request line contains the login code
            pass

        def do_GET(self):  # noqa: N802 (stdlib name)
            parts = urllib.parse.urlsplit(self.path)
            if parts.path != "/callback":
                self.send_error(404)
                return
            outcome = handle_redirect_query(parts.query, expected_state)
            if outcome.get("code"):
                result["code"] = outcome["code"]
            else:
                result["error"] = outcome["error"]
            ok = bool(outcome.get("code"))
            body = ("<h2>Connected to Oura.</h2><p>You can close this tab and go back to the "
                    "terminal.</p>" if ok else
                    f"<h2>Oura connection failed</h2><p>{html.escape(outcome.get('error', ''))}</p>")
            data = f"<!doctype html><meta charset=utf-8><title>{APP}</title>{body}".encode()
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            if ok:
                done.set()

    return Handler


def handle_redirect_query(query: str, expected_state: str) -> dict:
    params = urllib.parse.parse_qs(query)
    got_state = (params.get("state") or [""])[0]
    if not secrets.compare_digest(got_state.encode(), expected_state.encode()):
        return {"error": "The login link did not match this setup run. Start again."}
    if params.get("error"):
        reason = re.sub(r"[^a-z_]", "", params["error"][0].lower())[:40]
        return {"error": f"Oura did not grant access ({reason})."}
    code = (params.get("code") or [""])[0]
    if not code:
        return {"error": "Oura did not return a login code."}
    remember_secret(code)
    return {"code": code}


def pkce_pair() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def start_callback_servers(port: int, handler) -> list:
    servers = []
    for cls, host in ((_CallbackServer, "127.0.0.1"), (_CallbackServerV6, "::1")):
        try:
            server = cls((host, port), handler)
        except OSError:
            continue
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
    return servers


def wait_for_redirect(port: int, expected_state: str, auth_url: str) -> str:
    result: dict = {}
    console = None
    done = threading.Event()
    servers = start_callback_servers(port, _callback_handler(expected_state, result, done))
    try:
        if not servers:
            say(f"(Port {port} is busy, so the automatic return will not work.)")
        say()
        say("Opening Oura in your browser. If it does not open, copy this link into it:")
        say(auth_url)
        with contextlib.suppress(Exception):
            webbrowser.open(auth_url)
        say()
        say("Log in to Oura, turn on 'Sleep, readiness, and activity', then press Allow.")
        say("If the localhost return page fails, copy its full address, paste it here")
        say("and press Enter. If Oura itself shows an error, press Ctrl+C and run")
        say("this command again to start a fresh authorization request.")
        stdin_open = interactive()
        console = WindowsConsoleLine() if is_windows() and stdin_open else None
        if console:
            say("The pasted address is hidden while you type or paste it. Press Enter once.")
        deadline = time.monotonic() + OAUTH_WAIT_SECONDS
        while not done.is_set():
            if time.monotonic() > deadline:
                raise AppError("Timed out waiting for Oura. Run the command again.")
            line = None
            if console:
                line = console.poll()
                if line is None:
                    done.wait(0.05)
            elif stdin_open:
                ready, _, _ = select.select([sys.stdin], [], [], 0.5)
                if ready:
                    line = sys.stdin.readline()
                    if not line:
                        stdin_open = False
            else:
                done.wait(0.5)
            if line and line.strip():
                query = urllib.parse.urlsplit(line.strip()).query
                outcome = handle_redirect_query(query, expected_state)
                if outcome.get("code"):
                    return outcome["code"]
                say(outcome["error"])
            error = result.pop("error", None)
            if error and not done.is_set():
                say(error)
        return result["code"]
    finally:
        if console:
            console.discard()
        for server in servers:
            server.shutdown()
            server.server_close()


def connect_oura(paths: Paths, config: dict) -> None:
    pause = oura_pause_message(load_state(paths), time.time())
    if pause:
        raise AppError(f"{pause}. Try again after that.")
    port = int(settings_of(config)["redirect_port"])
    verifier, challenge = pkce_pair()
    remember_secret(verifier)
    expected_state = secrets.token_urlsafe(24)
    auth_url = OURA_AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": config["oura_client_id"],
        "redirect_uri": redirect_uri(port),
        "scope": OURA_SCOPE,
        "state": expected_state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    code = wait_for_redirect(port, expected_state, auth_url)
    # Hold the lock from the exchange to the save, so a background check cannot
    # race the new login.
    with interactive_lock(paths):
        try:
            payload = token_request(config, {"grant_type": "authorization_code", "code": code,
                                             "redirect_uri": redirect_uri(port),
                                             "code_verifier": verifier})
        except RateLimited as exc:
            state = load_state(paths)
            state["next_oura_request_at"] = int(time.time()) + exc.retry_after
            write_json_private(paths.state, state)
            raise
        if not payload.get("refresh_token"):
            say("Note: Oura did not provide a renewable login. You may need to reconnect "
                "when it expires.")
        write_json_private(paths.tokens, tokens_from_response(payload, time.time()))
        state = load_state(paths)
        state.update(needs_reconnect=False, reconnect_notice_sent=False, last_error=None,
                     next_oura_request_at=None, reconnect_action=None, reconnect_reason=None)
        write_json_private(paths.state, state)


def setup_oura(paths: Paths, config: dict) -> None:
    heading("Step 2 of 3: Oura")
    port = int(settings_of(config)["redirect_port"])
    keep = (config.get("oura_client_id") and config.get("oura_client_secret")
            and ask_yes("Your Oura app details are already saved. Keep them?"))
    if not keep:
        say(f"1. Open {OURA_APPS_URL} and log in with your Oura account.")
        say(f"2. Create a new application named {PRODUCT_NAME}.")
        say("   Enter a description and contact email.")
        say("   For Website, Privacy Policy and Terms of Service, a personal app can use:")
        say(f"   {PROJECT_URL}")
        say(f"3. Redirect URI must be exactly:  {redirect_uri(port)}")
        say("4. Select Daily under Scopes.")
        say("5. Accept the Oura API Agreement and create the app.")
        say("6. Copy the Client ID and Client Secret shown for the app.")
        client_id = os.environ.get("OURA_CLIENT_ID", "").strip()
        if client_id:
            say("Using OURA_CLIENT_ID from the environment.")
        elif interactive():
            client_id = ask("Paste the Client ID")
        if not client_id:
            raise AppError("Run setup in your own terminal window, or set OURA_CLIENT_ID.")
        secret = ask_secret("Paste the Client Secret", "OURA_CLIENT_SECRET")
        remember_secret(secret)
        config.update(oura_client_id=client_id, oura_client_secret=secret)
        write_json_private(paths.config, config)
    connect_oura(paths, config)


# --------------------------------------------------------------------------
# Background schedule
# --------------------------------------------------------------------------

# Keep this legacy identifier stable so existing Windows tasks remain manageable.
WINDOWS_TASK_SOURCE = "https://github.com/fkb032/oura-stress-notification"
WINDOWS_TASK_LIMIT_SECONDS = 600
TASK_XML_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"

# The program is fixed. All variable data travels as JSON, never as executable code.
WINDOWS_TASK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    $p = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $folder = $service.GetFolder('\')
    $task = $null
    try { $task = $folder.GetTask([string]$p.name) }
    catch {
        $e = $_.Exception
        while ($e.InnerException) { $e = $e.InnerException }
        if ($e.HResult -ne -2147024894) { throw }
    }
    if ($task -and $task.Definition.RegistrationInfo.Source -ne [string]$p.source) {
        throw 'A different program owns this task name. No task was changed.'
    }
    switch ([string]$p.operation) {
        'register' {
            $task = $folder.RegisterTask([string]$p.name, [string]$p.xml, 6,
                                        [string]$p.sid, $null, 3, $null)
        }
        'run' {
            if (-not $task) { throw 'The task is not installed.' }
            $task.Run($null) | Out-Null
        }
        'disable' {
            if ($task) { $task.Enabled = $false }
        }
        'uninstall' {
            if ($task) {
                $task.Enabled = $false
                $deadline = [DateTime]::UtcNow.AddSeconds(620)
                while ($task.GetInstances(0).Count -gt 0) {
                    if ([DateTime]::UtcNow -ge $deadline) {
                        throw 'The disabled task is still running. Saved data was kept. Try uninstall again later.'
                    }
                    Start-Sleep -Milliseconds 250
                }
                $folder.DeleteTask([string]$p.name, 0)
                $task = $null
                try { $task = $folder.GetTask([string]$p.name) }
                catch {
                    $e = $_.Exception
                    while ($e.InnerException) { $e = $e.InnerException }
                    if ($e.HResult -ne -2147024894) { throw }
                }
                if ($task) { throw 'The task is still installed. Saved data was kept.' }
            }
        }
        'query' { }
        default { throw 'Unknown scheduler operation.' }
    }
    if ($task) {
        @{ exists=$true; enabled=[bool]$task.Enabled; state=[int]$task.State;
           xml=[string]$task.Xml; result=[long]$task.LastTaskResult } | ConvertTo-Json -Compress
    } else {
        @{ exists=$false } | ConvertTo-Json -Compress
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""


def windows_powershell() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    exe = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not exe.is_file():
        raise AppError("Windows PowerShell 5.1 is unavailable. Automatic checks cannot be installed.")
    return str(exe)


def windows_task_name() -> str:
    return f"{APP}-{windows_user_sid()}"


def windows_task(operation: str, xml: Optional[str] = None,
                 name: Optional[str] = None) -> dict:
    payload = {"operation": operation, "xml": xml, "name": name or windows_task_name(),
               "sid": windows_user_sid(), "source": WINDOWS_TASK_SOURCE}
    command = [windows_powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand",
               base64.b64encode(WINDOWS_TASK_SCRIPT.encode("utf-16-le")).decode("ascii")]
    result = subprocess.run(command, input=json.dumps(payload), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            timeout=650 if operation == "uninstall" else 60)
    if result.returncode:
        raise AppError("Windows Task Scheduler failed: " + redact(result.stderr.strip())[:500]
                       + ". Use a normal PowerShell window. On a managed computer, "
                       "PowerShell or Task Scheduler may be restricted.")
    try:
        value = json.loads(result.stdout.lstrip("\ufeff"))
    except ValueError:
        raise AppError("Windows Task Scheduler returned an unreadable response.") from None
    if not isinstance(value, dict) or not isinstance(value.get("exists"), bool):
        raise AppError("Windows Task Scheduler returned an unexpected response.")
    return value


def windows_task_arguments(script: Path, data_dir: Path, run_id: str) -> list:
    return [str(script), "--data-dir", str(data_dir), "check", "--scheduled", "--run-id", run_id]


def windows_task_xml(pythonw: str, script: Path, data_dir: Path, interval: int,
                     sid: str, run_id: str, *, start: Optional[str] = None,
                     enabled: bool = True) -> str:
    for value in (pythonw, str(script), str(data_dir)):
        if re.search(r"%[^%]+%", value):
            raise AppError("Task Scheduler expands percent-variable names in paths. "
                           "Move the program or data to a folder without a %NAME% pair.")
    if not 1 <= interval <= 59:
        raise AppError("The check interval must be between 1 and 59 minutes.")
    root = ET.Element("Task", {"xmlns": TASK_XML_NAMESPACE, "version": "1.2"})

    def node(parent, name, text=None, **attributes):
        element = ET.SubElement(parent, name, attributes)
        if text is not None:
            element.text = str(text)
        return element

    info = node(root, "RegistrationInfo")
    node(info, "Description", f"{PRODUCT_NAME}: Telegram stress alerts")
    node(info, "Source", WINDOWS_TASK_SOURCE)
    triggers = node(root, "Triggers")
    trigger = node(triggers, "TimeTrigger")
    repetition = node(trigger, "Repetition")
    node(repetition, "Interval", f"PT{interval}M")  # No duration means indefinite repetition.
    node(repetition, "StopAtDurationEnd", "false")
    if start is None:
        start = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=interval)).replace(
            microsecond=0).isoformat()
    node(trigger, "StartBoundary", start)
    node(trigger, "Enabled", "true")
    principal = node(node(root, "Principals"), "Principal", id="User")
    node(principal, "UserId", sid)
    node(principal, "LogonType", "InteractiveToken")
    node(principal, "RunLevel", "LeastPrivilege")
    settings = node(root, "Settings")
    for name, value in (("MultipleInstancesPolicy", "IgnoreNew"),
                        ("DisallowStartIfOnBatteries", "false"),
                        ("StopIfGoingOnBatteries", "false"),
                        ("AllowHardTerminate", "true"), ("StartWhenAvailable", "true"),
                        ("RunOnlyIfNetworkAvailable", "false")):
        node(settings, name, value)
    idle = node(settings, "IdleSettings")
    node(idle, "StopOnIdleEnd", "false")
    node(idle, "RestartOnIdle", "false")
    for name, value in (("AllowStartOnDemand", "true"), ("Enabled", str(enabled).lower()),
                        ("Hidden", "false"), ("RunOnlyIfIdle", "false"),
                        ("WakeToRun", "false"), ("ExecutionTimeLimit", "PT10M"),
                        ("Priority", "7")):
        node(settings, name, value)
    action = node(node(root, "Actions", Context="User"), "Exec")
    node(action, "Command", pythonw)
    node(action, "Arguments", subprocess.list2cmdline(windows_task_arguments(script, data_dir, run_id)))
    return ET.tostring(root, encoding="unicode")


def windows_task_fields(xml: str) -> dict:
    """Read semantic fields, since Task Scheduler normalizes its stored XML."""
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, TypeError):
        raise AppError("Task Scheduler returned an invalid task definition.") from None
    ns = {"t": TASK_XML_NAMESPACE}
    fields = ("RegistrationInfo/Source", "Principals/Principal/UserId",
              "Principals/Principal/LogonType", "Principals/Principal/RunLevel",
              "Actions/Exec/Command", "Actions/Exec/Arguments",
              "Triggers/TimeTrigger/Repetition/Interval", "Settings/Enabled",
              "Settings/MultipleInstancesPolicy", "Settings/ExecutionTimeLimit",
              "Settings/DisallowStartIfOnBatteries", "Settings/StopIfGoingOnBatteries",
              "Settings/StartWhenAvailable", "Settings/WakeToRun", "Settings/RunOnlyIfIdle")
    result = {name: root.findtext("/".join("t:" + part for part in name.split("/")),
                                  namespaces=ns) for name in fields}
    defaults = {"Principals/Principal/RunLevel": "LeastPrivilege",
                "Settings/Enabled": "true", "Settings/MultipleInstancesPolicy": "IgnoreNew",
                "Settings/ExecutionTimeLimit": "PT72H", "Settings/DisallowStartIfOnBatteries": "true",
                "Settings/StopIfGoingOnBatteries": "true", "Settings/StartWhenAvailable": "false",
                "Settings/WakeToRun": "false", "Settings/RunOnlyIfIdle": "false"}
    for name, default in defaults.items():
        if result[name] is None:
            result[name] = default
    result["action_count"] = len(root.findall("t:Actions/*", ns))
    result["trigger_count"] = len(root.findall("t:Triggers/*", ns))
    return result


def windows_pythonw() -> str:
    console = Path(python_path())
    windowless = console.with_name("pythonw.exe")
    if console.name.lower() != "python.exe" or not console.is_file() or not windowless.is_file():
        raise AppError("Automatic checks need matching python.exe and pythonw.exe. "
                       "Use a standard runtime from the Python install manager at python.org.")
    return str(windowless)


def scheduled_environment(paths: Paths) -> dict:
    if is_windows():
        keys = {"systemroot", "windir", "systemdrive", "comspec", "pathext",
                "userprofile", "username", "userdomain", "homedrive", "homepath",
                "localappdata", "appdata", "allusersprofile", "programdata",
                "programfiles", "programfiles(x86)", "commonprogramfiles",
                "commonprogramfiles(x86)", "psmodulepath", "number_of_processors",
                "processor_architecture", "temp", "tmp", "path"}
        env = {key: value for key, value in os.environ.items() if key.lower() in keys}
        env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    else:
        env = {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
        if "LANG" in os.environ:
            env["LANG"] = os.environ["LANG"]
    env["OURA_STRESS_HOME"] = str(paths.root)
    return env


@contextlib.contextmanager
def scheduled_log(paths: Paths):
    ensure_private_dir(paths.root)
    target = paths.root / "check.log"
    if is_windows():
        protect_windows_file(target)
    with open(target, "a", encoding="utf-8", buffering=1) as handle:
        with contextlib.redirect_stdout(handle), contextlib.redirect_stderr(handle):
            yield


def install_windows_schedule(paths: Paths, script: Path, interval: int, verify: bool) -> None:
    pythonw = windows_pythonw()
    run_id = secrets.token_hex(16)
    xml = windows_task_xml(pythonw, script, paths.root, interval, windows_user_sid(), run_id)
    if verify:
        verify_background_run(paths, pythonw, script)
    since = time.time()
    registered = windows_task("register", xml)
    try:
        if not registered.get("exists"):
            raise AppError("the registered task is missing")
        actual, expected = windows_task_fields(registered.get("xml")), windows_task_fields(xml)
        differences = [name for name in expected if actual.get(name) != expected[name]]
        if differences:
            raise AppError("different task fields: " + ", ".join(differences))
    except AppError as exc:
        try:
            if windows_task("uninstall").get("exists"):
                raise AppError("the task is still present")
            cleanup = "The unverified task was removed."
        except (AppError, OSError, subprocess.SubprocessError) as cleanup_error:
            cleanup = ("The task may still be installed: " + redact(cleanup_error)
                       + ". To stop it, run: " + command_for("uninstall", paths))
        raise AppError(f"Windows task verification failed ({exc}). {cleanup} "
                       "Resolve the reported difference, then run install again.") from None
    if verify:
        windows_task("run")
        report_scheduled_run(wait_for_scheduled_run(paths, since, run_id=run_id))
    say(f"Installed. Checks run every {interval} minutes while you are signed in "
        "to Windows and the computer is awake. They resume after you sign in again.")
    say("Windows support is experimental; a live Windows account setup has not been tested.")
    say(f"Log file: {paths.root / 'check.log'}")


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def mac_log_path() -> Path:
    return Path.home() / "Library" / "Logs" / f"{APP}.log"


def systemd_unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "systemd" / "user"


def launchd_plist(python: str, script: Path, data_dir: Path, interval_minutes: int) -> bytes:
    return plistlib.dumps({
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [python, str(script), "check"],
        "StartInterval": int(interval_minutes) * 60,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "EnvironmentVariables": {"OURA_STRESS_HOME": str(data_dir)},
        "StandardOutPath": str(mac_log_path()),
        "StandardErrorPath": str(mac_log_path()),
    })


def _systemd_quote(value: str, exec_line: bool = True) -> str:
    """Quote for a unit file: % is a specifier everywhere, $ expands only in ExecStart."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    if exec_line:
        escaped = escaped.replace("$", "$$")
    return '"' + escaped + '"'


def systemd_units(python: str, script: Path, data_dir: Path, interval_minutes: int) -> Tuple[str, str]:
    environment = _systemd_quote("OURA_STRESS_HOME=" + str(data_dir), exec_line=False)
    service = (f"[Unit]\nDescription={PRODUCT_NAME}: Telegram stress alerts\n\n"
               f"[Service]\nType=oneshot\n"
               f"Environment={environment}\n"
               f"ExecStart={_systemd_quote(python)} {_systemd_quote(str(script))} check\n")
    timer = (f"[Unit]\nDescription=Run {PRODUCT_NAME} every {interval_minutes} minutes\n\n"
             f"[Timer]\nOnBootSec=1min\nOnUnitActiveSec={interval_minutes}min\n"
             f"Unit={SYSTEMD_UNIT}.service\n\n[Install]\nWantedBy=timers.target\n")
    return service, timer


def cron_line(python: str, script: Path, data_dir: Path, interval_minutes: int, log_path: Path) -> str:
    # cron treats an unescaped % as a newline, so escape it inside the command.
    command = (f"OURA_STRESS_HOME={shlex.quote(str(data_dir))} "
               f"{shlex.quote(python)} {shlex.quote(str(script))} check "
               f">> {shlex.quote(str(log_path))} 2>&1")
    return f"*/{interval_minutes} * * * * {command.replace('%', chr(92) + '%')} {CRON_MARKER}"


def run(cmd: list, check: bool = False, input_text: Optional[str] = None,
        env: Optional[dict] = None, timeout: Optional[float] = 60) -> subprocess.CompletedProcess:
    options = ({"encoding": "utf-8", "errors": "replace",
                "creationflags": subprocess.CREATE_NO_WINDOW} if is_windows() else {"text": True})
    return subprocess.run(cmd, check=check, input=input_text, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, **options)


def systemd_user_available() -> bool:
    if not shutil.which("systemctl"):
        return False
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        return run(["systemctl", "--user", "show-environment"]).returncode == 0
    return False


def linger_enabled() -> Optional[bool]:
    if not shutil.which("loginctl"):
        return None
    user = os.environ.get("USER") or getpass.getuser()
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        out = run(["loginctl", "show-user", user, "-p", "Linger"]).stdout.strip()
        if out.startswith("Linger="):
            return out == "Linger=yes"
    return None


def copy_script() -> Path:
    target = installed_script_path()
    ensure_private_dir(target.parent)
    source = Path(__file__).resolve()
    if source != target.resolve():
        shutil.copy2(source, target)
    if is_windows():
        protect_windows_file(target)
    else:
        os.chmod(target, 0o700)
    photo = source.with_name(BOT_PHOTO_NAME)
    installed_photo = target.with_name(BOT_PHOTO_NAME)
    if photo.is_file() and photo.resolve() != installed_photo.resolve():
        shutil.copy2(photo, installed_photo)
        if is_windows():
            protect_windows_file(installed_photo)
    return target


def verify_background_run(paths: Paths, python: str, script: Path) -> None:
    """Run the scheduled command once, with the minimal environment a scheduler gives."""
    env = scheduled_environment(paths)
    say("Running one check the way the background job will...")
    run_id = secrets.token_hex(8)
    command = ([python] + windows_task_arguments(script, paths.root, run_id) + ["--verify"]
               if is_windows() else [python, str(script), "check", "--verify", "--run-id", run_id])
    result = run(command, env=env,
                 timeout=CHECK_TIME_LIMIT_SECONDS + INTERACTIVE_LOCK_WAIT_SECONDS + 30)
    last = read_last_run(paths)
    outcome = str(last.get("outcome") or "") if last.get("run_id") == run_id else ""
    if result.returncode != 0 or outcome not in SUCCESS_OUTCOMES:
        state = load_state(paths)
        detail = (state.get("delivery_error") if outcome.startswith("degraded") else None) \
            or state.get("last_error") or outcome or redact(result.stderr.strip()[-300:]) \
            or "the check did not run"
        if state.get("needs_reconnect"):
            action = state.get("reconnect_action") or "connect-oura"
            detail += f". Run: {command_for(action, paths)}"
        raise AppError(f"The check did not succeed: {detail}")
    say(f"Check worked ({outcome}).")


SUCCESS_OUTCOMES = ("ok", "ok: alert sent")


def wait_for_scheduled_run(paths: Paths, since: float, timeout: float = 60,
                           run_id: Optional[str] = None) -> Optional[str]:
    """Outcome of the first check started by the scheduler after `since`, or None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        last = read_last_run(paths)
        if (float(last.get("invoked_at") or 0) >= since and last.get("finished_at")
                and (run_id is None or last.get("run_id") == run_id)):
            return str(last.get("outcome") or "")
        time.sleep(1)
    return None


def report_scheduled_run(outcome: Optional[str]) -> None:
    if outcome is None:
        raise AppError("The background job was installed but did not run within a minute. "
                       "Run 'status' in a few minutes; if 'Last background run' stays "
                       "empty, see Troubleshooting in SETUP.md.")
    if outcome.startswith(("error", "paused", "degraded")):
        raise AppError(f"The background job ran but reported: {outcome}")
    say(f"The scheduler started a check by itself ({outcome}).")


def install_schedule(paths: Paths, config: dict, verify: bool = True) -> None:
    interval = int(settings_of(config)["interval_minutes"])
    python = python_path()
    system = platform.system()
    if system not in ("Darwin", "Linux", "Windows"):
        raise AppError(f"Automatic scheduling is not supported on {system}. See SETUP.md.")
    script = copy_script()
    if system == "Windows":
        install_windows_schedule(paths, script, interval, verify)
        return
    if verify:
        verify_background_run(paths, python, script)
    if system == "Darwin":
        plist = launchd_plist_path()
        plist.parent.mkdir(parents=True, exist_ok=True)
        mac_log_path().parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(launchd_plist(python, script, paths.root, interval))
        domain = f"gui/{os.getuid()}"
        run(["launchctl", "bootout", f"{domain}/{LAUNCHD_LABEL}"])
        since = time.time()
        result = run(["launchctl", "bootstrap", domain, str(plist)])
        if result.returncode != 0:
            fallback = run(["launchctl", "load", "-w", str(plist)])
            if fallback.returncode != 0:
                raise AppError(f"launchctl could not start the job: {result.stderr.strip()}")
        if verify:  # RunAtLoad makes launchd start one check right away.
            report_scheduled_run(wait_for_scheduled_run(paths, since))
        say(f"Installed. Checks run every {interval} minutes while you are logged in to "
            "this Mac and it is awake. They start again automatically when you log in.")
        say(f"Log file: {mac_log_path()}")
        return
    log_path = paths.root / "check.log"
    if systemd_user_available():
        since = time.time()  # before enabling: the timer may start a check right away
        unit_dir = systemd_unit_dir()
        unit_dir.mkdir(parents=True, exist_ok=True)
        service, timer = systemd_units(python, script, paths.root, interval)
        (unit_dir / f"{SYSTEMD_UNIT}.service").write_text(service)
        (unit_dir / f"{SYSTEMD_UNIT}.timer").write_text(timer)
        run(["systemctl", "--user", "daemon-reload"], check=True)
        run(["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT}.timer"], check=True)
        run(["systemctl", "--user", "restart", f"{SYSTEMD_UNIT}.timer"])
        if verify:  # Start the service through systemd once, to prove the unit works.
            run(["systemctl", "--user", "start", f"{SYSTEMD_UNIT}.service"],
                timeout=CHECK_TIME_LIMIT_SECONDS + 30)
            report_scheduled_run(wait_for_scheduled_run(paths, since, timeout=30))
        say(f"Installed a systemd user timer (every {interval} minutes).")
        say(f"Logs: journalctl --user -u {SYSTEMD_UNIT}.service")
        if linger_enabled() is False:
            say("By default these checks stop when you log out.")
            if ask_yes("Keep checking even when you are logged out?", default=False):
                user = os.environ.get("USER") or getpass.getuser()
                if run(["loginctl", "enable-linger", user]).returncode == 0:
                    say("Done: checks continue after logout.")
                else:
                    say(f"Could not change it. You can run: loginctl enable-linger {user}")
    elif shutil.which("crontab"):
        set_cron_line(cron_line(python, script, paths.root, interval, log_path))
        say(f"Installed a cron job (every {interval} minutes). Log file: {log_path}")
        say("Note: cron support is experimental. Run 'status' after a few minutes and check "
            "that 'Last background run' is recent.")
    else:
        raise AppError("Neither systemd nor cron is available on this computer.")


def set_cron_line(line: Optional[str]) -> None:
    current = run(["crontab", "-l"])
    if current.returncode != 0 and "no crontab" not in current.stderr.lower():
        raise AppError(f"Could not read your existing crontab, so it was left unchanged: "
                       f"{current.stderr.strip()[:200]}")
    lines = current.stdout.splitlines() if current.returncode == 0 else []
    kept = [item for item in lines if CRON_MARKER not in item]
    if line:
        kept.append(line)
    run(["crontab", "-"], check=True, input_text="\n".join(kept) + ("\n" if kept else ""))


def uninstall_schedule() -> None:
    """Stop and remove the background job. Raises if it may still be running."""
    system = platform.system()
    problems = []
    if system == "Windows":
        windows_task("uninstall")
    elif system == "Darwin":
        target = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
        run(["launchctl", "bootout", target])
        if run(["launchctl", "print", target]).returncode == 0:
            problems.append(f"launchd still has the job loaded; try: launchctl bootout {target}")
        else:
            with contextlib.suppress(FileNotFoundError):
                launchd_plist_path().unlink()
    elif system == "Linux":
        unit_files = [systemd_unit_dir() / f"{SYSTEMD_UNIT}.{kind}" for kind in ("service", "timer")]
        if systemd_user_available():
            run(["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT}.timer"])
            run(["systemctl", "--user", "stop", f"{SYSTEMD_UNIT}.service"])
            still = [unit for unit in (f"{SYSTEMD_UNIT}.timer", f"{SYSTEMD_UNIT}.service")
                     if run(["systemctl", "--user", "is-active", unit]).stdout.strip()
                     in ("active", "activating", "reloading")]
            if still:
                problems.append(f"systemd still reports {', '.join(still)} as active")
            else:
                for path in unit_files:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
                run(["systemctl", "--user", "daemon-reload"])
        elif any(path.exists() for path in unit_files):
            problems.append("the systemd user manager is not reachable from this session, so "
                            "the timer could not be stopped; log in normally and run "
                            "uninstall again")
        if shutil.which("crontab"):
            set_cron_line(None)  # raises, without writing, if the crontab cannot be read
    if problems:
        raise AppError("Background checks may still be running: " + "; ".join(problems))
    say("Background checks removed.")


def schedule_description() -> str:
    system = platform.system()
    if system == "Windows":
        task = windows_task("query")
        if not task["exists"]:
            return "not installed"
        if not task.get("enabled"):
            return "installed but disabled (run install again)"
        if task.get("state") not in (2, 3, 4):
            return "installed but not ready (run install again)"
        return "installed (Task Scheduler; runs while you are signed in and Windows is awake)"
    if system == "Darwin":
        if not launchd_plist_path().exists():
            return "not installed"
        loaded = run(["launchctl", "print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"]).returncode == 0
        return ("installed (runs while you are logged in and the Mac is awake)" if loaded
                else "installed but not running (run install again)")
    if system == "Linux":
        if systemd_user_available():
            active = run(["systemctl", "--user", "is-active", f"{SYSTEMD_UNIT}.timer"]).stdout.strip()
            if active == "active":
                linger = linger_enabled()
                note = ("also while logged out" if linger else "stops when you log out")
                return f"installed (systemd timer, {note})"
        if shutil.which("crontab") and CRON_MARKER in run(["crontab", "-l"]).stdout:
            return "installed (cron)"
        return "not installed"
    return "not supported on this system"


def safe_schedule_description() -> str:
    """A failed scheduler query must not hide connection or health diagnostics."""
    try:
        return schedule_description()
    except (AppError, OSError, subprocess.SubprocessError) as exc:
        return "could not be checked (" + redact(exc) + ")"


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_setup(paths: Paths, args) -> int:
    say(f"{PRODUCT_NAME} setup")
    say("Your keys stay on this computer, in:")
    say(f"  {paths.root}")
    config = load_config(paths)
    setup_telegram(config)
    write_json_private(paths.config, config)
    setup_oura(paths, config)
    heading("Step 3 of 3: Check and schedule")
    read_stress_now(paths, config)
    with interactive_lock(paths):
        initialized = baseline_initialized(load_state(paths))
    if initialized:
        say("Your saved alert history is kept. The installation check may send "
            "an alert for stress recorded since the last check, even during quiet hours.")
    else:
        say("The first check with stress data records a starting point without "
            "sending a stress alert. Alerts begin with later increases. If there "
            "is no data yet, this starts when the first reading becomes available.")
    if ask_yes("Check automatically in the background from now on?"):
        install_schedule(paths, config)
    else:
        say(f"Skipped. To start later, run: {command_for('install', paths, prefer_installed=False)}")
    say()
    say("All set. You will get a Telegram message when Oura records new high stress.")
    return 0


def read_stress_now(paths: Paths, config: dict) -> None:
    with interactive_lock(paths):
        state = load_state(paths)
        pause = oura_pause_message(state, time.time())
        if pause:
            raise AppError(f"{pause}. Try again after that.")
        try:
            value = read_oura_locked(paths, config, dt.datetime.now().astimezone(), state)
        except ReconnectNeeded as exc:
            # Persist the pause under the same lock as the failed read. The
            # caller shows the actionable error in the terminal, so do not send
            # another Telegram notice for this same interactive failure.
            state.update(needs_reconnect=True, reconnect_action=exc.action,
                         reconnect_reason=exc.reason, reconnect_notice_sent=True,
                         last_error=redact(exc), last_check=now_iso())
            write_json_private(paths.state, state)
            raise
        except RateLimited:
            write_json_private(paths.state, state)
            raise
    if value is None:
        say("Oura: connected. No stress data for today yet. It appears after your ring "
            "syncs, and Daytime Stress needs a few days of wear before Oura shows it.")
    else:
        say(f"Oura: connected. {value // 60} min in high stress so far today.")


def cmd_connect_oura(paths: Paths, args) -> int:
    config = load_config(paths)
    if not config.get("oura_client_id") or not config.get("oura_client_secret"):
        raise AppError(f"Run setup first: {command_for('setup', paths)}")
    connect_oura(paths, config)
    try:
        read_stress_now(paths, config)
    except ReconnectNeeded:
        raise
    except (AppError, OSError) as exc:
        raise AppError(f"Your new Oura login was saved, but the test read failed: {exc}") from None
    description = safe_schedule_description()
    if description.startswith("could not be checked"):
        say("Oura is connected. Background checks " + description + ".")
    elif description == "not installed":
        say("Automatic checks are not installed. To enable them, run:")
        say(command_for("install", paths, prefer_installed=False))
    return 0


def cmd_test(paths: Paths, args) -> int:
    config = load_config(paths)
    if not config.get("telegram_bot_token"):
        raise AppError(f"Run setup first: {command_for('setup', paths)}")
    ok = send_telegram(config, f"\U0001F9EA Test from {PRODUCT_NAME}. Telegram works.")
    say("Telegram: test message sent." if ok else "Telegram: sending failed (see above).")
    read_stress_now(paths, config)
    return 0 if ok else 1


def cmd_set_bot_photo(paths: Paths, args) -> int:
    set_bot_photo(load_config(paths))
    say("Telegram bot profile picture updated to the bundled ring image.")
    return 0


def cmd_check(paths: Paths, args) -> int:
    limit = CHECK_TIME_LIMIT_SECONDS + (INTERACTIVE_LOCK_WAIT_SECONDS if args.verify else 0)
    with time_limit(limit):
        return run_check(paths, verify=args.verify, run_id=args.run_id)


def cmd_install(paths: Paths, args) -> int:
    config = load_config(paths)
    if not config.get("oura_client_id") or not config.get("telegram_chat_id"):
        raise AppError(f"Run setup first: {command_for('setup', paths)}")
    install_schedule(paths, config)
    return 0


def cmd_uninstall(paths: Paths, args) -> int:
    uninstall_schedule()
    if args.delete_data:
        # Wait for any running check, so it cannot write files back after deletion.
        with interactive_lock(paths):
            delete_owned_files(paths.root, OWNED_DATA_FILES, remove_lock=False)
        delete_owned_files(paths.root, (), remove_lock=True)
        delete_owned_files(installed_script_path().parent, (SCRIPT_NAME, BOT_PHOTO_NAME))
        say(f"Deleted saved settings and keys in {paths.root}.")
    return 0


OWNED_DATA_FILES = ("config.json", "tokens.json", "state.json", "last_run.json", "check.log")


def delete_owned_files(folder: Path, names, *, remove_lock: bool = True) -> None:
    """Remove only files this program creates; remove the folder only if then empty."""
    if not folder.is_dir():
        return
    for item in folder.iterdir():
        ours = item.name in names or (item.name.startswith(tuple(f".{n}." for n in names))
                                      and item.name.endswith(".tmp"))
        if ours and item.is_file():
            item.unlink()
    lock = folder / "lock"
    if remove_lock and lock.is_file() and set(os.listdir(folder)) == {"lock"}:
        lock.unlink()
    if not os.listdir(folder):
        folder.rmdir()


def cmd_settings(paths: Paths, args) -> int:
    config = load_config(paths)
    settings = dict(config.get("settings") or {})
    changed = False
    schedule_problem = None
    if args.quiet is not None:
        if args.quiet.lower() in ("off", "none"):
            settings.update(quiet_start="00:00", quiet_end="00:00")
        else:
            start, sep, end = args.quiet.partition("-")
            if not sep:
                raise AppError("Use --quiet 22:00-08:00, or --quiet off")
            parse_hhmm(start.strip())
            parse_hhmm(end.strip())
            settings.update(quiet_start=start.strip(), quiet_end=end.strip())
        changed = True
    if args.interval is not None:
        if not 1 <= args.interval <= 59:
            raise AppError("--interval must be between 1 and 59 minutes")
        settings["interval_minutes"] = args.interval
        changed = True
    if args.min_increase is not None:
        if not 0 <= args.min_increase <= 240:
            raise AppError("--min-increase must be between 0 and 240 minutes")
        settings["min_increase_minutes"] = args.min_increase
        changed = True
    if changed:
        config["settings"] = settings
        write_json_private(paths.config, config)
        if args.interval is not None:
            description = safe_schedule_description()
            if description.startswith("installed"):
                try:
                    install_schedule(paths, config, verify=False)
                except (AppError, OSError, subprocess.SubprocessError) as exc:
                    raise AppError("Settings were saved, but automatic check timing could not "
                                   f"be updated: {redact(exc)}") from None
            elif description.startswith("could not be checked"):
                schedule_problem = description
    current = settings_of(config)
    quiet = ("off" if current["quiet_start"] == current["quiet_end"]
             else f"{current['quiet_start']} to {current['quiet_end']}")
    say(f"Quiet hours (no checks): {quiet}")
    if schedule_problem:
        say(f"Requested check interval: {current['interval_minutes']} minutes (not yet verified)")
        say("Settings saved. Background checks " + schedule_problem + ".")
        say("After fixing that issue, update automatic checks with: " + command_for("install", paths))
    else:
        say(f"Check every: {current['interval_minutes']} minutes")
    increase = int(current["min_increase_minutes"] or 0)
    say("Alert on: " + ("any new high stress" if increase == 0
                        else f"at least {increase} new minutes of high stress"))
    return 0


def cmd_status(paths: Paths, args) -> int:
    with interactive_lock(paths):
        config = load_config(paths)
        tokens = load_tokens(paths)
        state = load_state(paths)

    def yes(value) -> str:
        return "yes" if value else "no"

    say(f"Settings folder: {paths.root}")
    say(f"Telegram set up: {yes(config.get('telegram_bot_token') and config.get('telegram_chat_id'))}")
    say(f"Oura app saved: {yes(config.get('oura_client_id') and config.get('oura_client_secret'))}")
    if tokens.get("expires_at"):
        days = (int(tokens["expires_at"]) - time.time()) / 86400
        renew = "renews automatically" if tokens.get("refresh_token") else "cannot renew"
        validity = f"valid for {days:.1f} more days" if days > 0 else "expired"
        say(f"Oura login: {validity} ({renew})")
    else:
        say("Oura login: not connected")
    current = settings_of(config)
    quiet = ("off" if current["quiet_start"] == current["quiet_end"]
             else f"{current['quiet_start']} to {current['quiet_end']}")
    say(f"Quiet hours: {quiet}")
    say(f"Background checks: {safe_schedule_description()} (every {current['interval_minutes']} min)")
    say(f"Last check: {state.get('last_check') or 'never'}")
    last_run = read_last_run(paths)
    if last_run.get("invoked_at"):
        when = dt.datetime.fromtimestamp(float(last_run["invoked_at"])).astimezone()
        say(f"Last background run: {when.isoformat(timespec='seconds')} ({last_run.get('outcome')})")
    else:
        say("Last background run: none yet")
    if isinstance(state.get("next_oura_request_at"), (int, float)):
        until = dt.datetime.fromtimestamp(state["next_oura_request_at"]).astimezone()
        if until.timestamp() > time.time():
            say(f"Oura asked us to wait until {until.isoformat(timespec='minutes')}")
    data_day = state.get("last_data_day")
    if data_day:
        say(f"Latest stress data: {data_day} "
            f"({int(state.get('last_seen_stress_high') or 0) // 60} min in high stress)")
        with contextlib.suppress(ValueError):
            age = (dt.date.today() - dt.date.fromisoformat(data_day)).days
            if age >= STALE_DATA_DAYS:
                say(f"WARNING: no new stress data for {age} days. Open the Oura app to "
                    "sync, and check that Daytime Stress shows there.")
    elif state.get("last_check"):
        say("Latest stress data: none yet. Daytime Stress needs an Oura Ring Gen3 or "
            "Ring 4, an active membership, and a few days of wear.")
    if state.get("needs_reconnect"):
        action = state.get("reconnect_action") or "connect-oura"
        say(f"ACTION NEEDED: reconnect Oura by running: {command_for(action, paths)}")
    if state.get("delivery_error"):
        say(f"ACTION NEEDED: Telegram messages are failing. {state['delivery_error']}")
    if state.get("consecutive_failures"):
        say(f"Failed checks in a row: {state['consecutive_failures']}")
    if state.get("last_error"):
        say(f"Last error: {state['last_error']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="Telegram nudges when your Oura ring records high stress.")
    parser.add_argument("--data-dir", help="folder for saved settings and login")
    parser.add_argument("--version", action="version", version=f"{APP} {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="guided first-time setup")
    commands.add_parser("connect-oura", help="log in to Oura again")
    commands.add_parser("test", help="send a test message and read today's stress")
    commands.add_parser("set-bot-photo", help="set the bot's profile picture to the bundled ring image")
    check = commands.add_parser("check", help="run one check (the background job runs this)")
    check.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    check.add_argument("--verify", action="store_true", help=argparse.SUPPRESS)
    check.add_argument("--run-id", help=argparse.SUPPRESS)
    commands.add_parser("install", help="start background checks")
    uninstall = commands.add_parser("uninstall", help="stop background checks")
    uninstall.add_argument("--delete-data", action="store_true",
                           help="also delete saved keys and settings")
    settings = commands.add_parser("settings", help="show or change quiet hours and interval")
    settings.add_argument("--quiet", help="quiet hours like 22:00-08:00, or 'off'")
    settings.add_argument("--interval", type=int, help="minutes between checks (1-59)")
    settings.add_argument("--min-increase", type=int,
                          help="only alert after this many new minutes of high stress (0 = any)")
    commands.add_parser("status", help="show whether everything is working")
    return parser


COMMANDS = {
    "setup": cmd_setup, "connect-oura": cmd_connect_oura, "test": cmd_test,
    "check": cmd_check, "install": cmd_install, "uninstall": cmd_uninstall,
    "settings": cmd_settings, "status": cmd_status,
    "set-bot-photo": cmd_set_bot_photo,
}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    paths = Paths(Path(args.data_dir).expanduser().resolve()) if args.data_dir else default_paths()
    try:
        if is_windows():
            windows_runtime_check(paths)
        if getattr(args, "scheduled", False):
            with scheduled_log(paths):
                return dispatch_command(paths, args)
        return dispatch_command(paths, args)
    except (AppError, OSError) as exc:
        say(f"Problem: {redact(exc)}")
        return 1


def dispatch_command(paths: Paths, args) -> int:
    try:
        return COMMANDS[args.command](paths, args)
    except KeyboardInterrupt:
        say("\nStopped.")
        return 130
    except ReconnectNeeded as exc:
        action = "setup" if args.command == "setup" else exc.action
        report = log if args.command == "check" else say
        report(f"Problem: {exc}")
        if exc.action == "setup":
            report("Run setup again. When it asks to keep your Oura app details, answer n")
            report("and enter the Client ID and Client Secret again.")
        elif args.command == "setup":
            report("Run setup again to finish. Your saved Telegram and Oura app keys are kept.")
        report(f"Run: {command_for(action, paths, prefer_installed=False)}")
        return 1
    except (AppError, OSError, subprocess.SubprocessError, RunTimeout) as exc:
        if args.command == "check":
            log(f"ERROR: {exc}")
        else:
            say(f"Problem: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
