"""Fail-closed guards for read-only 千川 material totals."""
from urllib.parse import parse_qs, urlparse


def detail_context_matches(url, *, aavid, ad_id, day):
    """Return True only for the exact expected 千川 detail account/plan/day."""
    parsed = urlparse(url or "")
    query = parse_qs(parsed.query)
    expected_day = f"{day},{day}"
    return (
        parsed.scheme == "https"
        and parsed.netloc == "qianchuan.jinritemai.com"
        and parsed.path == "/uni-prom/detail"
        and query.get("aavid") == [str(aavid)]
        and query.get("adId") == [str(ad_id)]
        and query.get("dr") == [expected_day]
    )


def require_complete_totals(payload, names, material_type):
    """Return requested named totals or fail instead of forwarding blank cells."""
    stats = ((payload.get("data") or {}).get("statsData") or {})
    totals = stats.get("totals") or {}
    missing = []
    values = []
    for name in names:
        cell = totals.get(name)
        if not isinstance(cell, dict) or (cell.get("valueStr") in (None, "") and cell.get("value") is None):
            missing.append(name)
            continue
        value = cell.get("valueStr")
        values.append(str(cell.get("value")) if value in (None, "") else str(value))
    if missing:
        raise RuntimeError(
            "incomplete_material_totals:"
            + str(material_type)
            + ":missing="
            + ",".join(missing)
            + ":available="
            + ",".join(sorted(totals))
        )
    return values


def retry_material_totals(fetch, names, material_type, attempts=3, sleep=None):
    """Retry only transient API errors or an incomplete named-totals payload."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    sleep = sleep or __import__("time").sleep
    last_error = None
    for attempt in range(attempts):
        payload = fetch()
        if payload.get("status_code") != 0:
            last_error = RuntimeError(
                "material_totals_api_failed:"
                + str(material_type)
                + ":"
                + str(payload.get("message") or payload.get("msg") or payload.get("status_code"))
            )
        else:
            try:
                return require_complete_totals(payload, names, material_type)
            except RuntimeError as exc:
                last_error = exc
        if attempt + 1 < attempts:
            sleep(1)
    raise last_error
