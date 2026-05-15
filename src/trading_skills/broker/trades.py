# ABOUTME: Fetches trade executions from Interactive Brokers.
# ABOUTME: Supports live API, FlexReport web service, and local FlexReport XML files.

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from ib_async import ExecutionFilter

from trading_skills.broker.connection import CLIENT_IDS, ib_connection


class _UrllibResponse:
    def __init__(self, status_code: int, content: bytes, headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = content.decode("utf-8")
        self.ok = 200 <= status_code < 400

    def raise_for_status(self) -> None:
        if not self.ok:
            raise urllib.error.HTTPError(
                url="",
                code=self.status_code,
                msg=f"HTTP request failed with status {self.status_code}",
                hdrs=self.headers,
                fp=None,
            )

    def json(self):
        return json.loads(self.text)


class _UrllibRequestsCompat:
    @staticmethod
    def get(url: str, params: dict | None = None, timeout: float | None = None) -> _UrllibResponse:
        if params:
            query = urllib.parse.urlencode(params, doseq=True)
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{query}"
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return _UrllibResponse(
                status_code=response.getcode(),
                content=response.read(),
                headers=response.headers,
            )


requests = _UrllibRequestsCompat()


async def get_trades(
    port: int = 7496,
    account: str | None = None,
    all_accounts: bool = False,
    symbol: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    flex_token: str | None = None,
    flex_query_id: str | list[str] | None = None,
    files: list[str] | None = None,
) -> dict:
    """Fetch trade executions from IB.

    Dispatches to local files, FlexReport web service, or reqExecutionsAsync.

    Args:
        port: IB Gateway/TWS port.
        account: Specific account ID to filter.
        all_accounts: If True, fetch trades for all managed accounts.
        symbol: Filter trades by symbol.
        start_date: Start date (YYYY-MM-DD). Defaults to Jan 1 of current year.
        end_date: End date (YYYY-MM-DD). Defaults to today.
        flex_token: FlexReport token (enables extended history).
        flex_query_id: FlexReport query ID(s). Pass a list to merge multiple queries.
        files: Local FlexReport XML file path(s) to load.
    """
    today = datetime.now()
    if not start_date:
        start_date = f"{today.year}-01-01"
    if not end_date:
        end_date = today.strftime("%Y-%m-%d")

    if files:
        return _fetch_from_files(
            files=files,
            account=account,
            all_accounts=all_accounts,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )

    use_flex = flex_token and flex_query_id

    if use_flex:
        # Normalize to list
        query_ids = flex_query_id if isinstance(flex_query_id, list) else [flex_query_id]
        return await _fetch_via_flex(
            port=port,
            account=account,
            all_accounts=all_accounts,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            flex_token=flex_token,
            flex_query_ids=query_ids,
        )
    else:
        return await _fetch_via_api(
            port=port,
            account=account,
            all_accounts=all_accounts,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )


def _fetch_from_files(
    files: list[str],
    account: str | None,
    all_accounts: bool,
    symbol: str | None,
    start_date: str,
    end_date: str,
) -> dict:
    """Load trade executions from local FlexReport XML files."""
    raw_trades = []
    loaded_files = []
    for file_path in files:
        path = Path(file_path)
        if not path.exists():
            return {
                "connected": False,
                "error": f"File not found: {file_path}",
            }
        trades = _parse_flex_xml(path)
        raw_trades.extend(trades)
        loaded_files.append(str(path.name))

    # Deduplicate by tradeID
    seen_ids = set()
    unique_trades = []
    for trade in raw_trades:
        trade_id = getattr(trade, "tradeID", None)
        if trade_id and trade_id in seen_ids:
            continue
        if trade_id:
            seen_ids.add(trade_id)
        unique_trades.append(trade)

    all_executions = [_normalize_flex_trade(t) for t in unique_trades]

    # Apply filters
    all_executions = _filter_by_date(all_executions, start_date, end_date)

    if symbol:
        all_executions = [e for e in all_executions if e["symbol"] == symbol.upper()]

    if account:
        all_executions = [e for e in all_executions if e["account"] == account]
    elif not all_accounts:
        # Without IB connection, default to all accounts from files
        pass

    summary = _aggregate_executions(all_executions)

    return {
        "connected": True,
        "source": "file",
        "files": loaded_files,
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "symbol": symbol,
            "account": account or ("all" if all_accounts else "all"),
        },
        "execution_count": len(all_executions),
        "executions": all_executions,
        "summary": summary,
    }


def _parse_flex_xml(path: Path) -> list:
    """Parse a FlexReport XML file and return list of SimpleNamespace trade objects."""
    tree = ET.parse(path)
    root = tree.getroot()
    trades = []
    for trade_elem in root.iter("Trade"):
        trades.append(SimpleNamespace(**trade_elem.attrib))
    return trades


async def _fetch_via_api(
    port: int,
    account: str | None,
    all_accounts: bool,
    symbol: str | None,
    start_date: str,
    end_date: str,
) -> dict:
    """Fetch executions using reqExecutionsAsync (limited to ~7 days)."""
    try:
        async with ib_connection(port, CLIENT_IDS["trades"]) as ib:
            managed = ib.managedAccounts()
            if not managed:
                return {"connected": True, "error": "No managed accounts found"}

            # Determine which accounts to query
            if all_accounts:
                accounts_to_fetch = managed
            elif account:
                if account not in managed:
                    return {
                        "connected": True,
                        "error": f"Account {account} not found. Available: {managed}",
                    }
                accounts_to_fetch = [account]
            else:
                accounts_to_fetch = [managed[0]]

            all_executions = []
            for acct in accounts_to_fetch:
                exec_filter = ExecutionFilter(acctCode=acct)
                if symbol:
                    exec_filter.symbol = symbol

                fills = await ib.reqExecutionsAsync(exec_filter)
                for fill in fills:
                    all_executions.append(_normalize_fill(fill))

            # Apply date filtering client-side
            all_executions = _filter_by_date(all_executions, start_date, end_date)

            summary = _aggregate_executions(all_executions)

            filters = {
                "start_date": start_date,
                "end_date": end_date,
                "symbol": symbol,
                "account": accounts_to_fetch if all_accounts else accounts_to_fetch[0],
            }

            return {
                "connected": True,
                "source": "reqExecutionsAsync",
                "filters": filters,
                "data_limitation": (
                    "reqExecutionsAsync only returns executions from approximately "
                    "the last 7 days. For full history, use --flex-token and "
                    "--flex-query-id to query via FlexReport."
                ),
                "execution_count": len(all_executions),
                "executions": all_executions,
                "summary": summary,
            }

    except ConnectionError as e:
        return {
            "connected": False,
            "error": f"{e}. Is TWS/Gateway running?",
        }


async def _fetch_via_flex(
    port: int,
    account: str | None,
    all_accounts: bool,
    symbol: str | None,
    start_date: str,
    end_date: str,
    flex_token: str,
    flex_query_ids: list[str],
) -> dict:
    """Fetch executions using FlexReport (supports full date range).

    Accepts multiple query IDs — each is fetched independently and
    the results are merged and deduplicated by tradeID.
    """
    try:
        loop = asyncio.get_event_loop()

        # Fetch all queries (could be parallelized, but IBKR rate-limits)
        raw_trades = []
        for qid in flex_query_ids:
            trades = await loop.run_in_executor(
                None,
                lambda q=qid: _download_flex_trades(flex_token, q),
            )
            raw_trades.extend(trades)

        # Deduplicate by tradeID (overlapping queries may return same trades)
        seen_ids = set()
        unique_trades = []
        for trade in raw_trades:
            trade_id = getattr(trade, "tradeID", None)
            if trade_id and trade_id in seen_ids:
                continue
            if trade_id:
                seen_ids.add(trade_id)
            unique_trades.append(trade)
        raw_trades = unique_trades

        all_executions = []
        for trade in raw_trades:
            normalized = _normalize_flex_trade(trade)
            all_executions.append(normalized)

        # Apply filters client-side
        all_executions = _filter_by_date(all_executions, start_date, end_date)

        if symbol:
            all_executions = [e for e in all_executions if e["symbol"] == symbol.upper()]

        if account:
            all_executions = [e for e in all_executions if e["account"] == account]
        elif not all_accounts:
            # If not all_accounts and no specific account, try connecting to get
            # the default account
            try:
                async with ib_connection(port, CLIENT_IDS["trades"]) as ib:
                    managed = ib.managedAccounts()
                    if managed:
                        default_acct = managed[0]
                        all_executions = [e for e in all_executions if e["account"] == default_acct]
            except ConnectionError:
                pass  # If can't connect, return all accounts from flex

        summary = _aggregate_executions(all_executions)

        filters = {
            "start_date": start_date,
            "end_date": end_date,
            "symbol": symbol,
            "account": account or ("all" if all_accounts else "default"),
        }

        return {
            "connected": True,
            "source": "FlexReport",
            "filters": filters,
            "execution_count": len(all_executions),
            "executions": all_executions,
            "summary": summary,
        }

    except Exception as e:
        return {
            "connected": False,
            "error": f"FlexReport failed: {e}",
        }


_FLEX_BASE = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService"


def _download_flex_trades(token: str, query_id: str, max_retries: int = 5) -> list:
    """Download FlexReport trades directly via IBKR API (bypasses ib_async cache).

    Uses v=3 parameter to ensure a fresh report is generated.
    Returns list of SimpleNamespace objects matching FlexReport trade attributes.
    """
    # Step 1: Request report generation
    send_url = f"{_FLEX_BASE}.SendRequest?t={token}&q={query_id}&v=3"
    resp = requests.get(send_url, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    status = root.findtext("Status")
    if status != "Success":
        error_msg = root.findtext("ErrorMessage") or "Unknown error"
        raise RuntimeError(f"FlexReport request failed: {error_msg}")

    ref_code = root.findtext("ReferenceCode")

    # Step 2: Poll for the report
    get_url = f"{_FLEX_BASE}.GetStatement?q={ref_code}&t={token}&v=3"
    for attempt in range(max_retries):
        time.sleep(3 + attempt * 2)
        resp = requests.get(get_url, timeout=60)
        resp.raise_for_status()

        # Check if still generating
        if resp.text.strip().startswith("<FlexStatementResponse"):
            check = ET.fromstring(resp.text)
            if check.findtext("Status") == "Warn":
                continue  # Still generating, retry
            error_msg = check.findtext("ErrorMessage") or "Unknown error"
            raise RuntimeError(f"FlexReport fetch failed: {error_msg}")

        # Parse the completed report
        report_root = ET.fromstring(resp.content)
        trades = []
        for trade_elem in report_root.iter("Trade"):
            # Convert XML attributes to SimpleNamespace (same interface as ib_async)
            trades.append(SimpleNamespace(**trade_elem.attrib))
        return trades

    raise RuntimeError("FlexReport timed out after max retries")


def _normalize_fill(fill) -> dict:
    """Convert an ib-async Fill object to a plain dict."""
    execution = fill.execution
    contract = fill.contract
    commission_report = fill.commissionReport

    result = {
        "account": execution.acctNumber,
        "symbol": contract.symbol,
        "secType": contract.secType,
        "side": execution.side,
        "quantity": execution.shares,
        "price": execution.price,
        "avgPrice": execution.avgPrice,
        "datetime": execution.time.isoformat() if execution.time else None,
        "exchange": execution.exchange,
        "commission": commission_report.commission if commission_report else None,
        "realizedPnL": commission_report.realizedPNL if commission_report else None,
    }

    if contract.secType in ("OPT", "FOP"):
        result.update(
            {
                "strike": contract.strike,
                "expiry": contract.lastTradeDateOrContractMonth,
                "right": contract.right,
            }
        )

    return result


def _normalize_flex_trade(trade) -> dict:
    """Convert a FlexReport trade record to the same dict format as _normalize_fill."""
    sec_type = getattr(trade, "assetCategory", None)
    # Map FlexReport assetCategory to IB secType
    sec_type_map = {"STK": "STK", "OPT": "OPT", "FUT": "FUT", "FOP": "FOP"}
    sec_type = sec_type_map.get(sec_type, sec_type)

    # Infer sec_type from putCall/strike when assetCategory is missing (compact format)
    if not sec_type:
        put_call = getattr(trade, "putCall", None)
        strike = getattr(trade, "strike", None)
        if put_call or (strike and str(strike) not in ("", "0")):
            sec_type = "OPT"

    # For options, use underlyingSymbol (symbol field is OCC format like
    # "AMD   260320C00225000"); for stocks, use symbol directly
    if sec_type in ("OPT", "FOP"):
        symbol = getattr(trade, "underlyingSymbol", None) or getattr(trade, "symbol", None)
    else:
        symbol = getattr(trade, "symbol", None)

    # Map buySell field (SELL/BUY) to IB side convention (SLD/BOT)
    buy_sell = getattr(trade, "buySell", None)
    if buy_sell:
        side_map = {"BUY": "BOT", "SELL": "SLD"}
        side = side_map.get(buy_sell, buy_sell)
    else:
        quantity = getattr(trade, "quantity", 0)
        side = "BOT" if float(quantity) > 0 else "SLD"

    quantity = abs(float(getattr(trade, "quantity", 0)))

    dt = _parse_flex_datetime(trade)

    result = {
        "account": getattr(trade, "accountId", None),
        "symbol": symbol,
        "secType": sec_type,
        "side": side,
        "quantity": quantity,
        "price": float(getattr(trade, "tradePrice", 0)),
        "avgPrice": float(getattr(trade, "tradePrice", 0)),
        "datetime": dt,
        "exchange": getattr(trade, "exchange", None),
        "commission": float(getattr(trade, "ibCommission", 0)),
        "realizedPnL": float(getattr(trade, "fifoPnlRealized", 0)),
    }

    if sec_type in ("OPT", "FOP"):
        expiry_raw = getattr(trade, "expiry", None)
        if expiry_raw and not isinstance(expiry_raw, str):
            expiry_raw = str(expiry_raw)
        result.update(
            {
                "strike": float(getattr(trade, "strike", 0)),
                "expiry": expiry_raw,
                "right": getattr(trade, "putCall", None),
            }
        )

    return result


def _parse_flex_datetime(trade) -> str | None:
    """Parse FlexReport datetime into ISO format (YYYY-MM-DDTHH:MM:SS).

    FlexReport uses 'YYYYMMDD;HHMMSS' format for dateTime, and integer
    YYYYMMDD for tradeDate.
    """
    dt = getattr(trade, "dateTime", None)
    if dt:
        dt = str(dt)
        # Format: '20260227;155707' -> '2026-02-27T15:57:07'
        if ";" in dt and len(dt) >= 15:
            date_part = dt[:8]
            time_part = dt[9:15]
            return (
                f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
                f"T{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
            )
        # Format: '20260227' -> '2026-02-27'
        if len(dt) >= 8 and dt[:8].isdigit():
            return f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
        return dt

    trade_date = getattr(trade, "tradeDate", None)
    if trade_date:
        td = str(trade_date)
        if len(td) >= 8 and td[:8].isdigit():
            return f"{td[:4]}-{td[4:6]}-{td[6:8]}"
        return td

    return None


def _filter_by_date(executions: list[dict], start_date: str, end_date: str) -> list[dict]:
    """Filter executions by date range."""
    filtered = []
    for ex in executions:
        dt_str = ex.get("datetime")
        if not dt_str:
            filtered.append(ex)
            continue
        # Extract date portion (handle both ISO and date-only formats)
        trade_date = dt_str[:10]
        if start_date <= trade_date <= end_date:
            filtered.append(ex)
    return filtered


def _aggregate_executions(executions: list[dict]) -> list[dict]:
    """Group executions by symbol and compute summary stats."""
    by_symbol: dict[str, dict] = {}

    for ex in executions:
        sym = ex.get("symbol", "UNKNOWN")
        if sym not in by_symbol:
            by_symbol[sym] = {
                "symbol": sym,
                "total_bought": 0.0,
                "total_sold": 0.0,
                "net_quantity": 0.0,
                "total_commission": 0.0,
                "total_realized_pnl": 0.0,
                "trade_count": 0,
                "first_trade": None,
                "last_trade": None,
            }

        entry = by_symbol[sym]
        qty = float(ex.get("quantity", 0))
        side = ex.get("side", "")

        if side == "BOT":
            entry["total_bought"] += qty
            entry["net_quantity"] += qty
        elif side == "SLD":
            entry["total_sold"] += qty
            entry["net_quantity"] -= qty

        commission = ex.get("commission")
        if commission is not None:
            entry["total_commission"] += float(commission)

        pnl = ex.get("realizedPnL")
        if pnl is not None:
            entry["total_realized_pnl"] += float(pnl)

        entry["trade_count"] += 1

        dt = ex.get("datetime")
        if dt:
            if entry["first_trade"] is None or dt < entry["first_trade"]:
                entry["first_trade"] = dt
            if entry["last_trade"] is None or dt > entry["last_trade"]:
                entry["last_trade"] = dt

    return sorted(by_symbol.values(), key=lambda x: x["symbol"])
