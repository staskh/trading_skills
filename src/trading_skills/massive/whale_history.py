# ABOUTME: Historical options whale detection over Massive OPRA day-agg flatfiles (S3).
# ABOUTME: Downloads per-day OPRA day_aggs gz files for a date range, filters one underlying,
#          and flags per-day dollar-invested outliers (modified z-score + absolute floor).

import gzip
import io
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from dotenv import load_dotenv

load_dotenv()

DEFAULT_ENDPOINT = "https://files.massive.com"
DEFAULT_BUCKET = "flatfiles"
DAY_AGGS_PREFIX = "us_options_opra/day_aggs_v1"

# OPRA ticker: O:<UNDERLYING><YYMMDD><C|P><strike*1000, zero-padded to 8>
_TICKER_RE = re.compile(r"^O:([A-Z]+)(\d{6})([CP])(\d{8})$")


class FlatfileConfigError(RuntimeError):
    """Raised when the Massive S3 flatfile credentials are missing."""


def _credentials() -> tuple[str, str, str, str]:
    """Return (access_key_id, secret, endpoint, bucket) from the environment.

    These S3 flatfile creds are SEPARATE from the REST ``MASSIVE_API_KEY`` and
    do not require the 1-second aggregate entitlement the live whale skill needs.
    """
    akid = os.getenv("MASSIVE_S3_ACCESS_KEY_ID")
    secret = os.getenv("MASSIVE_S3_SECRET_ACCESS_KEY")
    if not akid or not secret:
        raise FlatfileConfigError(
            "MASSIVE_S3_ACCESS_KEY_ID / MASSIVE_S3_SECRET_ACCESS_KEY not set — "
            "add the Massive flatfile (S3) credentials to your environment/.env."
        )
    endpoint = os.getenv("MASSIVE_S3_ENDPOINT", DEFAULT_ENDPOINT)
    bucket = os.getenv("MASSIVE_S3_BUCKET", DEFAULT_BUCKET)
    return akid, secret, endpoint, bucket


def _make_s3():
    import boto3
    from botocore.config import Config

    akid, secret, endpoint, _ = _credentials()
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=akid,
        aws_secret_access_key=secret,
        config=Config(signature_version="s3v4", max_pool_connections=32),
    )


def parse_strike(raw: str) -> float:
    """OPRA strike field (8 digits, ×1000) -> float dollars."""
    return int(raw) / 1000.0


def _months_of(start: date, end: date) -> list[str]:
    """``YYYY/MM`` prefixes spanning [start, end] inclusive."""
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y}/{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


def list_trading_days(s3, bucket: str, start: date, end: date) -> list[str]:
    """Sorted day_aggs object keys present within [start, end]."""
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for mon in _months_of(start, end):
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{DAY_AGGS_PREFIX}/{mon}/"):
            for obj in page.get("Contents", []):
                name = obj["Key"].rsplit("/", 1)[-1].replace(".csv.gz", "")
                try:
                    day = date.fromisoformat(name)
                except ValueError:
                    continue
                if start <= day <= end:
                    keys.append(obj["Key"])
    return sorted(keys)


def _modified_z(invested: list[float]) -> tuple[float, float]:
    """Return (median, MAD) for a modified z-score."""
    s = sorted(invested)
    n = len(s)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    devs = sorted(abs(x - med) for x in s)
    mad = devs[n // 2] if n % 2 else (devs[n // 2 - 1] + devs[n // 2]) / 2
    return med, mad


def detect_whales(
    rows: list[dict],
    sigma_z: float,
    floor: float,
    exclude_0dte: bool,
    trade_date: str,
) -> list[dict]:
    """Flag rows whose dollar invested is a modified-z outlier above ``floor``.

    ``rows`` items need: type, strike, expiry, close, volume, transactions, invested.
    Pure function (no I/O) so it is unit-testable without network access.
    """
    active = [r for r in rows if r["invested"] > 0]
    if exclude_0dte:
        active = [r for r in active if r["expiry"] != trade_date]
    if not active:
        return []
    med, mad = _modified_z([r["invested"] for r in active])
    whales = []
    for r in active:
        if r["invested"] < floor:
            continue
        if mad > 0:
            mz = 0.6745 * (r["invested"] - med) / mad
        else:
            mz = float("inf") if r["invested"] > med else 0.0
        if mz >= sigma_z:
            be = r["strike"] + r["close"] if r["type"] == "call" else r["strike"] - r["close"]
            whales.append(
                {
                    **r,
                    "mod_z": round(mz, 1) if mz != float("inf") else None,
                    "break_even": round(be, 4),
                    "date": trade_date,
                }
            )
    whales.sort(key=lambda x: x["invested"], reverse=True)
    return whales


def _parse_day_csv(text: str, underlying: str) -> list[dict]:
    """Parse a day_aggs CSV body, keeping only rows for ``underlying``."""
    rows = []
    prefix = "O:" + underlying
    for line in io.StringIO(text):
        if not line.startswith(prefix):
            continue
        parts = line.rstrip("\n").split(",")
        m = _TICKER_RE.match(parts[0])
        if not m or m.group(1) != underlying:
            continue
        _, yymmdd, right, strike_raw = m.groups()
        try:
            volume = float(parts[1])
            close = float(parts[3])
            txns = int(parts[7])
        except (ValueError, IndexError):
            continue
        rows.append(
            {
                "ticker": parts[0],
                "type": "call" if right == "C" else "put",
                "strike": parse_strike(strike_raw),
                "expiry": f"20{yymmdd[0:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}",
                "close": round(close, 4),
                "volume": int(volume),
                "transactions": txns,
                "invested": round(close * volume * 100.0, 2),
            }
        )
    return rows


def _scan_day(key: str, underlying: str, sigma_z: float, floor: float, exclude_0dte: bool) -> dict:
    s3 = _make_s3()
    obj = s3.get_object(Bucket=_credentials()[3], Key=key)
    text = gzip.decompress(obj["Body"].read()).decode()
    trade_date = key.rsplit("/", 1)[-1].replace(".csv.gz", "")
    rows = _parse_day_csv(text, underlying)
    return {
        "date": trade_date,
        "whales": detect_whales(rows, sigma_z, floor, exclude_0dte, trade_date),
    }


def hunt_history(
    underlying: str,
    start: date,
    end: date,
    sigma_z: float = 3.5,
    floor: float = 500_000.0,
    exclude_0dte: bool = False,
    max_workers: int = 12,
) -> dict:
    """Scan OPRA day_aggs flatfiles for whale events over [start, end]."""
    underlying = underlying.upper()
    s3 = _make_s3()
    bucket = _credentials()[3]
    keys = list_trading_days(s3, bucket, start, end)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(
            ex.map(lambda k: _scan_day(k, underlying, sigma_z, floor, exclude_0dte), keys)
        )
    results.sort(key=lambda x: x["date"])

    all_whales = [w for r in results for w in r["whales"]]
    call_inv = sum(w["invested"] for w in all_whales if w["type"] == "call")
    put_inv = sum(w["invested"] for w in all_whales if w["type"] == "put")
    return {
        "underlying": underlying,
        "source": "massive OPRA day_aggs flatfiles",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "trading_days": len(keys),
        "sigma_z": sigma_z,
        "floor_invested": floor,
        "exclude_0dte": exclude_0dte,
        "total_whales": len(all_whales),
        "total_call_invested": round(call_inv, 2),
        "total_put_invested": round(put_inv, 2),
        "call_put_ratio": round(call_inv / put_inv, 4) if put_inv else None,
        "by_day": [{"date": r["date"], "whale_count": len(r["whales"])} for r in results],
        "top_whales": sorted(all_whales, key=lambda x: x["invested"], reverse=True)[:40],
    }
