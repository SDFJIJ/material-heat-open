"""Helpers for ensuring the configured Qianchuan Chrome/CDP profile is running."""
from __future__ import annotations

import os
import pathlib
import subprocess
import time
import urllib.request

from qianchuan_account_context import configured_cdp_urls, load_account_context

DEFAULT_CHROME = pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def cdp_alive(cdp_url: str, timeout: float = 2.0) -> bool:
    """Return True if the Chrome DevTools endpoint is reachable."""
    try:
        with urllib.request.urlopen(cdp_url.rstrip("/") + "/json/version", timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def _candidate_urls(cdp_url: str | None) -> list[str]:
    return [cdp_url] if cdp_url else configured_cdp_urls()


def ensure_chrome_9223(
    cdp_url: str | None = None,
    chrome_path: str | os.PathLike[str] | None = None,
    profile_dir: str | os.PathLike[str] | None = None,
    target_url: str | None = None,
    wait_seconds: int = 25,
) -> tuple[bool, str]:
    """Ensure Chrome is reachable for the selected QC_ACCOUNT.

    The configured browser endpoint is probed before launch (IPv6 first on this
    host).  If Chrome must be launched, its URL and profile come from the
    selected account context.  This does not attempt a login; callers must stop
    on a login redirect.
    """
    account = load_account_context()
    urls = _candidate_urls(cdp_url)
    for candidate in urls:
        if cdp_alive(candidate):
            os.environ["BU_CDP_URL"] = candidate
            return True, f"Chrome CDP already reachable at {candidate} for {account.alias}"

    chrome = pathlib.Path(chrome_path or os.environ.get("QIANCHUAN_CHROME") or DEFAULT_CHROME)
    profile = pathlib.Path(profile_dir or os.environ.get("QIANCHUAN_CHROME_PROFILE") or account.chrome_profile)
    if not chrome.exists():
        return False, f"Chrome executable not found: {chrome}"

    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(chrome),
        "--remote-debugging-port=9223",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        target_url or account.target_url,
    ]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    except Exception as exc:
        return False, f"Failed to start Chrome 9223: {exc}"

    for _ in range(max(1, wait_seconds)):
        time.sleep(1)
        for candidate in urls:
            if cdp_alive(candidate):
                os.environ["BU_CDP_URL"] = candidate
                return True, f"Started Chrome CDP at {candidate} for {account.alias}"
    return False, f"Chrome CDP not reachable after {wait_seconds}s at {', '.join(urls)}"
