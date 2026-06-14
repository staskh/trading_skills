# ABOUTME: Shared Questrade connection/auth utilities used by all broker modules.
# ABOUTME: Handles single-use refresh-token rotation, access-token caching, authed GETs.

import json
import os
import time
from pathlib import Path

import requests

# Questrade's refresh token is SINGLE-USE and rotates on every exchange. If we
# lose the new one, you must manually generate a fresh token in the API Centre.
# So we persist the rotated refresh token atomically the instant we receive it.

TOKEN_URL = "https://login.questrade.com/oauth2/token"
ACCESS_TOKEN_TTL_SAFETY = 60  # refresh this many seconds before stated expiry


def _token_dir() -> Path:
    d = Path(os.environ.get("QUESTRADE_TOKEN_DIR", Path.home() / ".questrade-skills"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _token_file() -> Path:
    return _token_dir() / "token.json"


def _load_token_state() -> dict:
    """Load persisted token state, seeding the refresh token from env on first run."""
    tf = _token_file()
    if tf.exists():
        return json.loads(tf.read_text())
    seed = os.environ.get("QUESTRADE_REFRESH_TOKEN")
    if not seed:
        raise RuntimeError(
            "No token file and QUESTRADE_REFRESH_TOKEN is not set. "
            "Generate a manual refresh token in Questrade > API Centre > "
            "Personal applications, then set QUESTRADE_REFRESH_TOKEN once."
        )
    return {"refresh_token": seed}


def _save_token_state(state: dict) -> None:
    """Write token state atomically so a crash never leaves a half-written file."""
    tf = _token_file()
    tmp = tf.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, tf)  # atomic on POSIX and Windows
    try:
        os.chmod(tf, 0o600)
    except OSError:
        pass  # best effort on Windows


def _refresh_access_token(state: dict) -> dict:
    """Exchange the stored refresh token for a fresh access token + api_server.

    Persists the NEW refresh token immediately (single-use rotation).
    """
    resp = requests.get(
        TOKEN_URL,
        params={"grant_type": "refresh_token", "refresh_token": state["refresh_token"]},
        timeout=20,
    )
    if resp.status_code != 200:
        raise ConnectionError(
            f"Questrade token refresh failed ({resp.status_code}). "
            "The refresh token may be expired (3-day limit) or already used. "
            "Generate a new one in the API Centre and reset QUESTRADE_REFRESH_TOKEN."
        )
    data = resp.json()
    api_server = data["api_server"].rstrip("/")
    # api_server sometimes already ends in /v1; normalize to a bare base.
    if api_server.endswith("/v1"):
        api_server = api_server[: -len("/v1")]
    new_state = {
        "refresh_token": data["refresh_token"],
        "access_token": data["access_token"],
        "api_server": api_server,
        "expires_at": time.time() + int(data.get("expires_in", 1800)),
    }
    _save_token_state(new_state)  # persist rotated refresh token NOW
    return new_state


def _ensure_access_token() -> dict:
    """Return valid {access_token, api_server}, refreshing if needed."""
    state = _load_token_state()
    fresh_enough = (
        state.get("access_token")
        and state.get("api_server")
        and state.get("expires_at", 0) - ACCESS_TOKEN_TTL_SAFETY > time.time()
    )
    if not fresh_enough:
        state = _refresh_access_token(state)
    return state


def qt_get(path: str, params: dict | None = None) -> dict:
    """Authenticated GET against the Questrade API. `path` like '/v1/accounts'."""
    state = _ensure_access_token()
    url = f"{state['api_server']}{path}"
    headers = {"Authorization": f"Bearer {state['access_token']}"}
    resp = requests.get(url, headers=headers, params=params or {}, timeout=30)
    if resp.status_code == 401:
        # token died early; force one refresh and retry once
        state = _refresh_access_token(_load_token_state())
        headers = {"Authorization": f"Bearer {state['access_token']}"}
        resp = requests.get(url, headers=headers, params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def qt_post(path: str, body: dict) -> dict:
    """Authenticated POST against the Questrade API (e.g. options quotes)."""
    state = _ensure_access_token()
    url = f"{state['api_server']}{path}"
    headers = {"Authorization": f"Bearer {state['access_token']}"}
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code == 401:
        state = _refresh_access_token(_load_token_state())
        headers = {"Authorization": f"Bearer {state['access_token']}"}
        resp = requests.post(url, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_accounts() -> list[dict]:
    """List accounts on the login. Mirrors IB's managedAccounts()."""
    return qt_get("/v1/accounts").get("accounts", [])


def get_symbols(symbol_ids: list[int]) -> dict[int, dict]:
    """Batch-resolve symbolIds to their detail records. Returns {id: detail}.

    Used to classify positions (Stock vs Option) and pull option contract
    fields (optionType, optionStrikePrice, optionExpiryDate, optionRoot).
    """
    if not symbol_ids:
        return {}
    ids_param = ",".join(str(i) for i in symbol_ids)
    data = qt_get("/v1/symbols", params={"ids": ids_param})
    return {s["symbolId"]: s for s in data.get("symbols", [])}
