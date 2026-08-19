"""Load and validate explicit Qianchuan account contexts.

Switch account with QC_ACCOUNT=<alias>, or change active_account in
config/qianchuan_accounts.json.  There is intentionally no fallback to an
arbitrary account discovered in the browser: write-capable scripts must have a
configured AAVID and primary plan ID.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "qianchuan_accounts.json"


@dataclass(frozen=True)
class AccountContext:
    alias: str
    label: str
    aavid: str
    primary_ad_id: str
    anchor_id: str
    assist_task_scene: int
    target_roi: float
    gfversion: str
    chrome_profile: Path

    @property
    def target_url(self) -> str:
        query = urlencode({"aavid": self.aavid, "adId": self.primary_ad_id, "ct": "1"})
        return "https://qianchuan.jinritemai.com/uni-prom/detail?" + query

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "data" / "accounts" / self.alias


def _load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Qianchuan account config is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Qianchuan account config is invalid JSON: {path}: {exc}") from exc


def load_account_context(alias: str | None = None, *, config_path: Path = CONFIG_PATH) -> AccountContext:
    config = _load_config(config_path)
    selected = alias or os.environ.get("QC_ACCOUNT") or config.get("active_account")
    accounts = config.get("accounts") or {}
    if not selected or selected not in accounts:
        available = ", ".join(sorted(accounts)) or "(none)"
        raise RuntimeError(f"QC_ACCOUNT must name a configured account; available: {available}")

    raw = accounts[selected]
    required = ("aavid", "primary_ad_id", "anchor_id", "assist_task_scene", "target_roi", "gfversion", "chrome_profile")
    missing = [key for key in required if raw.get(key) in (None, "")]
    if missing:
        raise RuntimeError(f"Account {selected!r} is missing required fields: {', '.join(missing)}")

    aavid = str(raw["aavid"])
    primary_ad_id = str(raw["primary_ad_id"])
    anchor_id = str(raw["anchor_id"])
    if not aavid.isdigit() or not primary_ad_id.isdigit() or not anchor_id.isdigit():
        raise RuntimeError(f"Account {selected!r} has non-numeric AAVID, primary_ad_id, or anchor_id")

    return AccountContext(
        alias=selected,
        label=str(raw.get("label") or selected),
        aavid=aavid,
        primary_ad_id=primary_ad_id,
        anchor_id=anchor_id,
        assist_task_scene=int(raw["assist_task_scene"]),
        target_roi=float(raw["target_roi"]),
        gfversion=str(raw["gfversion"]),
        chrome_profile=Path(str(raw["chrome_profile"])),
    )


def configured_cdp_urls(*, config_path: Path = CONFIG_PATH) -> list[str]:
    override = os.environ.get("BU_CDP_URL")
    if override:
        return [override]
    config = _load_config(config_path)
    urls = [str(url).rstrip("/") for url in config.get("cdp_urls") or [] if str(url).strip()]
    if not urls:
        raise RuntimeError("No cdp_urls configured and BU_CDP_URL is unset")
    return urls


def resolve_cdp_url(*, config_path: Path = CONFIG_PATH) -> str:
    """Return the explicit override or the first configured CDP candidate.

    Callers that need liveness probing should test each configured candidate.
    """
    return configured_cdp_urls(config_path=config_path)[0]
