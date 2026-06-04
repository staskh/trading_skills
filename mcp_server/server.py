#!/usr/bin/env python3
# ABOUTME: MCP server providing trading analysis tools.
# ABOUTME: Exposes market data, options, IB broker, portfolio, and report tools.

import os
import sys

# Ensure unbuffered output for MCP protocol (equivalent to python -u)
os.environ["PYTHONUNBUFFERED"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(write_through=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(write_through=True)

from importlib.metadata import version as pkg_version

from mcp.server.fastmcp import FastMCP

from trading_skills.broker.account import get_account_summary
from trading_skills.broker.collar import find_collar_candidates
from trading_skills.broker.delta_exposure import get_delta_exposure
from trading_skills.broker.options import (
    get_expiries as ib_get_expiries,
)
from trading_skills.broker.options import (
    get_option_chain as ib_get_option_chain,
)
from trading_skills.broker.pmcc_advisor import get_pmcc_data
from trading_skills.broker.portfolio import get_portfolio
from trading_skills.broker.portfolio_action import (
    analyze_portfolio,
    get_portfolio_data,
)
from trading_skills.broker.roll import find_roll_candidates
from trading_skills.broker.stop_loss import get_stop_loss_data
from trading_skills.broker.trades import get_trades
from trading_skills.broker.trailing_stop import get_trailing_stop_data
from trading_skills.correlation import compute_correlation
from trading_skills.earnings import get_earnings_info, get_multiple_earnings
from trading_skills.fundamentals import get_fundamentals
from trading_skills.greeks import calculate_greeks
from trading_skills.history import get_history
from trading_skills.insider_trading import (
    get_insider_transactions,
    get_multiple_insider_transactions,
)
from trading_skills.massive.whales import whales_hunter
from trading_skills.news import get_news
from trading_skills.options import get_expiries, get_option_chain
from trading_skills.piotroski import calculate_piotroski_score
from trading_skills.quote import get_quote
from trading_skills.report import generate_report_data
from trading_skills.risk import calculate_risk_metrics
from trading_skills.scanner_bullish import compute_bullish_score, scan_symbols
from trading_skills.scanner_pmcc import analyze_pmcc, format_scan_results
from trading_skills.spreads import (
    analyze_diagonal,
    analyze_iron_condor,
    analyze_straddle,
    analyze_strangle,
    analyze_vertical,
)
from trading_skills.technicals import compute_indicators

# Create MCP server
mcp = FastMCP("trading-skills")


# ============================================================================
# SERVER INFO
# ============================================================================


@mcp.tool()
def get_version() -> dict:
    """Return the current version of the trading-skills package."""
    return {"version": pkg_version("trading-skills")}


# ============================================================================
# MARKET DATA TOOLS
# ============================================================================


@mcp.tool()
def stock_quote(symbol: str) -> dict:
    """Get real-time stock quote with price, volume, change, and key metrics.

    Args:
        symbol: Ticker symbol (e.g., AAPL, MSFT)
    """
    return get_quote(symbol.upper())


@mcp.tool()
def price_history(
    symbol: str,
    period: str = "1mo",
    interval: str = "1d",
) -> dict:
    """Get historical OHLCV price data.

    Args:
        symbol: Ticker symbol
        period: Time period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
        interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo)
    """
    return get_history(symbol.upper(), period, interval)


@mcp.tool()
def news_sentiment(symbol: str, limit: int = 10) -> dict:
    """Get recent news headlines for a stock.

    Args:
        symbol: Ticker symbol
        limit: Number of articles to return (default 10)
    """
    return get_news(symbol.upper(), limit)


@mcp.tool()
def insider_trading(symbols: str, days_back: int = 90) -> dict:
    """Get insider trading activity (SEC Form 4) for one or more stocks.

    Returns transactions with insider name, role, transaction type, shares,
    price, value, date, and net buying/selling sentiment summary.

    Args:
        symbols: Single ticker or comma-separated list (e.g., 'NVDA' or 'NVDA,PLTR,GOOG')
        days_back: Trailing days to look back (default 90)
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",")]
    if len(symbol_list) == 1:
        return get_insider_transactions(symbol_list[0], days_back)
    return get_multiple_insider_transactions(symbol_list, days_back)


# ============================================================================
# FUNDAMENTAL ANALYSIS TOOLS
# ============================================================================


@mcp.tool()
def fundamentals(symbol: str, data_type: str = "all") -> dict:
    """Get fundamental financial data including metrics, financials, and earnings.

    Args:
        symbol: Ticker symbol
        data_type: Type of data - 'all', 'info', 'financials', or 'earnings'
    """
    return get_fundamentals(symbol.upper(), data_type)


@mcp.tool()
def piotroski_score(symbol: str) -> dict:
    """Calculate Piotroski F-Score (0-9) evaluating financial strength.

    Scores 9 fundamental criteria including profitability, leverage,
    liquidity, and operating efficiency.

    Args:
        symbol: Ticker symbol
    """
    return calculate_piotroski_score(symbol.upper())


@mcp.tool()
def earnings_calendar(symbols: str) -> dict:
    """Get upcoming earnings dates with timing (BMO/AMC) and EPS estimates.

    Args:
        symbols: Single symbol or comma-separated list (e.g., 'AAPL' or 'AAPL,MSFT,GOOGL')
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",")]
    if len(symbol_list) == 1:
        return get_earnings_info(symbol_list[0])
    return get_multiple_earnings(symbol_list)


# ============================================================================
# TECHNICAL ANALYSIS TOOLS
# ============================================================================


@mcp.tool()
def technical_indicators(
    symbol: str,
    period: str = "3mo",
    indicators: str = "rsi,macd,bb,sma,ema,atr,adx",
    include_earnings: bool = False,
) -> dict:
    """Compute technical indicators for a stock.

    Args:
        symbol: Ticker symbol or comma-separated list
        period: Historical period (1mo, 3mo, 6mo, 1y)
        indicators: Comma-separated indicators (rsi, macd, bb, sma, ema, atr, adx)
        include_earnings: Include earnings data
    """
    indicator_list = [i.strip() for i in indicators.split(",")]
    symbols = [s.strip().upper() for s in symbol.split(",")]

    if len(symbols) == 1:
        return compute_indicators(symbols[0], period, indicator_list, include_earnings)

    # Multi-symbol
    results = []
    for sym in symbols:
        result = compute_indicators(sym, period, indicator_list, include_earnings)
        results.append(result)
    return {"results": results}


@mcp.tool()
def price_correlation(symbols: str, period: str = "3mo") -> dict:
    """Compute price correlation matrix between multiple symbols.

    Useful for portfolio diversification analysis.

    Args:
        symbols: Comma-separated ticker symbols (minimum 2)
        period: Historical period (1mo, 3mo, 6mo, 1y)
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",")]
    return compute_correlation(symbol_list, period)


@mcp.tool()
def risk_assessment(
    symbol: str,
    period: str = "1y",
    position_size: float | None = None,
) -> dict:
    """Assess risk metrics including volatility, beta, VaR, and drawdown.

    Args:
        symbol: Ticker symbol
        period: Analysis period (default 1y)
        position_size: Optional position size in dollars for position-specific metrics
    """
    return calculate_risk_metrics(symbol.upper(), period, position_size)


# ============================================================================
# OPTIONS TOOLS
# ============================================================================


@mcp.tool()
def option_expiries(symbol: str) -> dict:
    """List available option expiration dates for a symbol.

    Args:
        symbol: Ticker symbol
    """
    expiries = get_expiries(symbol.upper())
    if not expiries:
        return {"error": f"No options found for {symbol}"}
    return {"symbol": symbol.upper(), "expiries": expiries}


@mcp.tool()
def option_chain(symbol: str, expiry: str) -> dict:
    """Get option chain data (calls and puts) for a specific expiration.

    Args:
        symbol: Ticker symbol
        expiry: Expiration date (YYYY-MM-DD)
    """
    return get_option_chain(symbol.upper(), expiry)


@mcp.tool()
def option_greeks(
    spot: float,
    strike: float,
    option_type: str,
    expiry: str | None = None,
    dte: int | None = None,
    market_price: float | None = None,
    volatility: float | None = None,
    rate: float = 0.05,
) -> dict:
    """Calculate option Greeks (delta, gamma, theta, vega) using Black-Scholes.

    Computes implied volatility from market price if provided.

    Args:
        spot: Current underlying price
        strike: Option strike price
        option_type: 'call' or 'put'
        expiry: Expiration date (YYYY-MM-DD) - use this OR dte
        dte: Days to expiration (alternative to expiry)
        market_price: Option market price (for IV calculation)
        volatility: Override volatility (decimal, e.g., 0.30)
        rate: Risk-free rate (default 0.05)
    """
    return calculate_greeks(
        spot=spot,
        strike=strike,
        option_type=option_type,
        expiry=expiry,
        dte=dte,
        market_price=market_price,
        rate=rate,
        volatility=volatility,
    )


# ============================================================================
# SPREAD ANALYSIS TOOLS
# ============================================================================


@mcp.tool()
def spread_vertical(
    symbol: str,
    expiry: str,
    option_type: str,
    long_strike: float,
    short_strike: float,
) -> dict:
    """Analyze vertical spread (bull/bear call/put spread).

    Args:
        symbol: Ticker symbol
        expiry: Expiration date (YYYY-MM-DD)
        option_type: 'call' or 'put'
        long_strike: Strike price for long leg
        short_strike: Strike price for short leg
    """
    return analyze_vertical(symbol.upper(), expiry, option_type, long_strike, short_strike)


@mcp.tool()
def spread_diagonal(
    symbol: str,
    option_type: str,
    long_expiry: str,
    long_strike: float,
    short_expiry: str,
    short_strike: float,
) -> dict:
    """Analyze diagonal spread (different expiries and strikes).

    Includes Poor Man's Covered Call/Put analysis.

    Args:
        symbol: Ticker symbol
        option_type: 'call' or 'put'
        long_expiry: Long leg expiration (YYYY-MM-DD)
        long_strike: Long leg strike
        short_expiry: Short leg expiration (YYYY-MM-DD)
        short_strike: Short leg strike
    """
    return analyze_diagonal(
        symbol.upper(), option_type, long_expiry, long_strike, short_expiry, short_strike
    )


@mcp.tool()
def spread_straddle(symbol: str, expiry: str, strike: float) -> dict:
    """Analyze long straddle (buy call + put at same strike).

    Args:
        symbol: Ticker symbol
        expiry: Expiration date (YYYY-MM-DD)
        strike: Strike price for both legs
    """
    return analyze_straddle(symbol.upper(), expiry, strike)


@mcp.tool()
def spread_strangle(
    symbol: str,
    expiry: str,
    put_strike: float,
    call_strike: float,
) -> dict:
    """Analyze long strangle (buy OTM call + OTM put).

    Args:
        symbol: Ticker symbol
        expiry: Expiration date (YYYY-MM-DD)
        put_strike: Put strike (below current price)
        call_strike: Call strike (above current price)
    """
    return analyze_strangle(symbol.upper(), expiry, put_strike, call_strike)


@mcp.tool()
def spread_iron_condor(
    symbol: str,
    expiry: str,
    put_long: float,
    put_short: float,
    call_short: float,
    call_long: float,
) -> dict:
    """Analyze iron condor (sell strangle + buy protective wings).

    Args:
        symbol: Ticker symbol
        expiry: Expiration date (YYYY-MM-DD)
        put_long: Long put strike (lowest)
        put_short: Short put strike
        call_short: Short call strike
        call_long: Long call strike (highest)
    """
    return analyze_iron_condor(symbol.upper(), expiry, put_long, put_short, call_short, call_long)


# ============================================================================
# SCANNER TOOLS
# ============================================================================


@mcp.tool()
def scan_bullish(
    symbols: str,
    top_n: int = 30,
    period: str = "3mo",
) -> dict:
    """Scan symbols for bullish trends using SMA, RSI, MACD, ADX.

    Returns top N symbols ranked by composite bullish score.

    Args:
        symbols: Comma-separated ticker symbols
        top_n: Number of top symbols to return (default 30)
        period: Historical period (1mo, 3mo, 6mo)
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",")]

    if len(symbol_list) == 1:
        # Single symbol - return detailed score
        result = compute_bullish_score(symbol_list[0], period)
        return result if result else {"error": f"Could not analyze {symbol_list[0]}"}

    # Multi-symbol scan
    return scan_symbols(symbol_list, top_n, period)


@mcp.tool()
def scan_pmcc(
    symbols: str,
    min_leaps_days: int = 270,
    leaps_delta: float = 0.80,
    short_delta: float = 0.20,
) -> dict:
    """Scan symbols for Poor Man's Covered Call suitability.

    Analyzes LEAPS and short call options for delta, liquidity,
    spread tightness, IV, and yield.

    Args:
        symbols: Comma-separated ticker symbols
        min_leaps_days: Minimum days for LEAPS expiry (default 270)
        leaps_delta: Target delta for LEAPS (default 0.80)
        short_delta: Target delta for short call (default 0.20)
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",")]

    results = []
    for symbol in symbol_list:
        result = analyze_pmcc(
            symbol,
            min_leaps_days=min_leaps_days,
            leaps_delta=leaps_delta,
            short_delta=short_delta,
        )
        if result:
            results.append(result)

    output = format_scan_results(results)
    output["criteria"] = {
        "leaps_min_days": min_leaps_days,
        "leaps_target_delta": leaps_delta,
        "short_target_delta": short_delta,
    }
    return output


# ============================================================================
# WHALE HUNTING TOOLS
# ============================================================================


@mcp.tool()
def whale_hunting(
    symbol: str,
    max_months: int = 2,
    trading_date: str | None = None,
    sigma_z: float = 3.5,
    summary: bool = False,
) -> dict:
    """Detect institutional whale option activity for a given underlying.

    Uses a two-step approach:
    1. Crude scan via Yahoo Finance — finds contracts with anomalous daily investment.
    2. Precise drill-down via Massive API — per-second bars for each candidate.

    Requires MASSIVE_API_KEY environment variable for per-second data.
    Falls back to Yahoo-only daily data if unavailable.

    Args:
        symbol: Underlying ticker (e.g. AAPL, NVDA, SPY)
        max_months: Max months until expiration to consider (default 2)
        trading_date: Date to analyze YYYY-MM-DD (default: latest trading day)
        sigma_z: Modified Z-Score threshold for outlier detection (default 3.5)
        summary: If True, include per-ticker aggregate summary in result
    """
    import pandas as pd

    result = whales_hunter(
        symbol.upper(),
        max_months=max_months,
        precise=True,
        sigma_z=sigma_z,
        trading_date=trading_date,
    )

    whales = result["whales"]
    call_invested = sum(
        w["invested"] for w in whales if w.get("type") == "call" and w.get("invested")
    )
    put_invested = sum(
        w["invested"] for w in whales if w.get("type") == "put" and w.get("invested")
    )

    output = {
        "underlying": symbol.upper(),
        "trading_date": str(result["trading_date"]),
        "source": result["source"],
        "total_whales": len(whales),
        "total_call_invested": round(call_invested, 2),
        "total_put_invested": round(put_invested, 2),
        "call_put_ratio": round(call_invested / put_invested, 4) if put_invested > 0 else None,
        "whales": [
            {**w, "timestamp": str(w["timestamp"]), "expiry": str(w["expiry"])} for w in whales
        ],
    }

    if summary and whales:
        df = pd.DataFrame(whales)
        agg = (
            df.groupby(["ticker", "type", "strike", "expiry"])
            .agg(
                whale_count=("invested", "count"),
                total_invested=("invested", "sum"),
                break_even=("break_even", "first"),
            )
            .reset_index()
            .sort_values("total_invested", ascending=False)
        )
        agg["total_invested"] = agg["total_invested"].round(2)
        agg["expiry"] = agg["expiry"].astype(str)
        output["summary"] = agg.to_dict("records")

    return output


# ============================================================================
# REPORT TOOLS
# ============================================================================


@mcp.tool()
def report_stock(symbol: str) -> dict:
    """Generate comprehensive stock analysis data with trend, PMCC, and fundamental analysis.

    Returns detailed data including bullish score, PMCC viability, fundamentals,
    Piotroski F-Score, spread strategies, and an overall recommendation.

    Args:
        symbol: Ticker symbol (e.g., AAPL, MSFT)
    """
    return generate_report_data(symbol.upper())


# ============================================================================
# INTERACTIVE BROKERS TOOLS (Requires TWS/Gateway)
# ============================================================================


@mcp.tool()
async def ib_account(port: int = 7496) -> dict:
    """Get account summary from Interactive Brokers.

    Returns cash balance, buying power, net liquidation value, and margin info.
    Requires TWS or IB Gateway running locally.

    Args:
        port: IB port (7496 for live, 7497 for paper)
    """
    return await get_account_summary(port, all_accounts=True)


@mcp.tool()
async def ib_portfolio(port: int = 7496, account: str | None = None) -> dict:
    """Get portfolio positions from Interactive Brokers.

    Returns all positions including stocks and options with market prices.
    Requires TWS or IB Gateway running locally.

    Args:
        port: IB port (7496 for live, 7497 for paper)
        account: Specific account ID (optional, uses first if not specified)
    """
    return await get_portfolio(port, account, all_accounts=True)


@mcp.tool()
async def ib_find_short_roll(
    symbol: str,
    port: int = 7496,
    account: str | None = None,
    strike: float | None = None,
    expiry: str | None = None,
    right: str = "C",
) -> dict:
    """Find roll, spread, or covered call/put candidates using real-time IB data.

    Auto-detects mode based on existing positions:
    - Short option found: roll candidates with credit/debit analysis
    - Long option found: short candidates to create a vertical spread
    - Long stock found: covered call/put candidates
    Requires TWS or IB Gateway running locally.

    Args:
        symbol: Ticker symbol (e.g., GOOG)
        port: IB port (7496 for live, 7497 for paper)
        account: Account ID (optional)
        strike: Current short strike (optional, auto-detects from portfolio)
        expiry: Current expiry YYYYMMDD (optional, auto-detects from portfolio)
        right: 'C' for call or 'P' for put (default: C)
    """
    return await find_roll_candidates(
        symbol=symbol, port=port, account=account, strike=strike, expiry=expiry, right=right
    )


@mcp.tool()
async def ib_portfolio_action_report(
    port: int = 7496,
    account: str | None = None,
) -> dict:
    """Analyze portfolio positions with earnings dates and risk assessment.

    Fetches positions, groups into spreads, categorizes by urgency,
    and returns structured analysis with recommendations.
    Requires TWS or IB Gateway running locally.

    Args:
        port: IB port (7496 for live, 7497 for paper)
        account: Specific account ID (optional)
    """
    data = await get_portfolio_data(port, account)

    if "error" in data:
        return {"error": data["error"]}

    return analyze_portfolio(data)


@mcp.tool()
async def ib_option_expiries(symbol: str, port: int = 7496) -> dict:
    """List available option expiration dates from Interactive Brokers.

    Requires TWS or IB Gateway running locally.

    Args:
        symbol: Ticker symbol
        port: IB port (7496 for live, 7497 for paper)
    """
    return await ib_get_expiries(symbol.upper(), port=port)


@mcp.tool()
async def ib_option_chain(symbol: str, expiry: str, port: int = 7496) -> dict:
    """Get option chain data from Interactive Brokers with real-time quotes.

    Returns calls and puts with strikes, bids, asks, volume, and implied volatility.
    Requires TWS or IB Gateway running locally.

    Args:
        symbol: Ticker symbol
        expiry: Expiration date (YYYYMMDD)
        port: IB port (7496 for live, 7497 for paper)
    """
    return await ib_get_option_chain(symbol.upper(), expiry, port=port)


@mcp.tool()
async def ib_delta_exposure(port: int = 7496) -> dict:
    """Calculate delta-adjusted notional exposure across all IBKR accounts.

    Computes option deltas using Black-Scholes and reports long/short exposure
    by account and underlying symbol.
    Requires TWS or IB Gateway running locally.

    Args:
        port: IB port (7496 for live, 7497 for paper)
    """
    return await get_delta_exposure(port)


@mcp.tool()
async def ib_pmcc_advisor(
    port: int = 7496,
    account: str | None = None,
    symbols: str | None = None,
    min_roll_dte: int = 7,
    price_mode: str = "mid",
) -> dict:
    """Analyze PMCC (diagonal call spread) positions and recommend roll actions.

    For each spread: reports assignment probability, P&L projections, roll
    candidates ranked by delta improvement and credit, and a comparison table.
    Requires TWS or IB Gateway running locally.

    Args:
        port: IB port (7496 for live, 7497 for paper)
        account: Specific account ID (optional)
        symbols: Comma-separated symbols to filter (optional, e.g. 'NVDA,WMT')
        min_roll_dte: Minimum DTE for roll candidates (default 7)
        price_mode: Option price source — 'mid' (bid+ask)/2 or 'last'
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    return await get_pmcc_data(
        port=port,
        account=account,
        min_roll_dte=min_roll_dte,
        price_mode=price_mode,
        symbols=symbol_list,
    )


@mcp.tool()
async def ib_collar(
    symbol: str,
    port: int = 7496,
    account: str | None = None,
) -> dict:
    """Generate tactical collar strategy report for protecting PMCC positions.

    Analyzes existing long call (PMCC) positions and recommends put protection
    through earnings or high-risk events.
    Requires TWS or IB Gateway running locally.

    Args:
        symbol: Ticker symbol (e.g., AAPL)
        port: IB port (7496 for live, 7497 for paper)
        account: Account ID (optional)
    """
    return await find_collar_candidates(symbol, port, account)


@mcp.tool()
async def ib_stop_loss(
    port: int = 7496,
    account: str | None = None,
    symbols: str | None = None,
    stop_pct: float = 40.0,
    short_near_strike_pct: float = 5.0,
    price_mode: str = "mid",
    execute: bool = False,
    forced: bool = False,
) -> dict:
    """Analyze and manage downside stop-loss orders for PMCC, naked LEAPS, and stock positions.

    Default mode is dry-run — no orders are placed unless execute=True.
    Stop price = basis × (1 - stop_pct/100). Basis is max(current_mid, avg_cost)
    normally; current_mid only when forced=True (can lower existing stops).
    In execute mode: orphan SL_FALL_ orders are cancelled, then new conditional
    stop orders are placed. PMCC stops use combo BAG orders (atomic LEAPS + shorts).
    Requires TWS or IB Gateway running locally.

    Args:
        port: IB port (7496 for live, 7497 for paper)
        account: Specific account ID (optional)
        symbols: Comma-separated symbols to filter (optional, e.g. 'NVDA,QQQ')
        stop_pct: Loss % that triggers exit (default 40)
        short_near_strike_pct: Alert when spot is within this % of short strike (default 5)
        price_mode: Option pricing — 'mid' (bid+ask)/2 or 'last'
        execute: Place conditional stop-loss orders (default False = dry-run)
        forced: Use current mid as basis, can lower existing stops (requires execute=True)
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    return await get_stop_loss_data(
        port=port,
        account=account,
        symbols=symbol_list,
        stop_pct=stop_pct,
        short_near_strike_pct=short_near_strike_pct,
        price_mode=price_mode,
        dry_run=not execute,
        forced=forced,
    )


@mcp.tool()
async def ib_trailing_stop(
    port: int = 7496,
    account: str | None = None,
    symbols: str | None = None,
    trail_pct: float | None = 20.0,
    trail_amt: float | None = None,
    price_mode: str = "mid",
    execute: bool = False,
    forced: bool = False,
) -> dict:
    """Manage IB native TRAIL orders for stocks and naked LEAPS positions.

    Default mode is dry-run — no orders are placed unless execute=True.
    PMCC positions are excluded; use ib_stop_loss for those.
    Requires TWS or IB Gateway running locally.

    Args:
        port: IB port (7496 for live, 7497 for paper)
        account: Specific account ID (optional)
        symbols: Comma-separated symbols to filter (optional, e.g. 'JOBY,TSLA')
        trail_pct: Trail amount as % of reference price (default 20, mutually exclusive
            with trail_amt)
        trail_amt: Trail amount in dollars (mutually exclusive with trail_pct)
        price_mode: Option pricing — 'mid' (bid+ask)/2 or 'last' (LEAPS only)
        execute: Cancel orphan TS_ orders and place new TRAIL orders (default False = dry-run)
        forced: Cancel and replace existing TS_ orders with current parameters
            (requires execute=True)
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    return await get_trailing_stop_data(
        port=port,
        account=account,
        symbols=symbol_list,
        trail_pct=trail_pct,
        trail_amt=trail_amt,
        price_mode=price_mode,
        dry_run=not execute,
        forced=forced,
    )


@mcp.tool()
async def ib_trades_history(
    port: int = 7496,
    account: str | None = None,
    symbol: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    flex_token: str | None = None,
    flex_query_id: str | list[str] | None = None,
) -> dict:
    """Fetch trade executions from Interactive Brokers.

    Returns individual trade executions with fills, commissions, and realized P&L,
    plus aggregated summary by symbol. Uses live API (~7 days history) by default,
    or FlexReport for full history when token and query ID are provided.
    Requires TWS or IB Gateway running locally.

    Args:
        port: IB port (7496 for live, 7497 for paper)
        account: Specific account ID (optional, fetches all if not specified)
        symbol: Filter trades by symbol (e.g., AAPL)
        start_date: Start date in YYYY-MM-DD format (default: Jan 1 of current year)
        end_date: End date in YYYY-MM-DD format (default: today)
        flex_token: FlexReport token for extended history beyond ~7 days
        flex_query_id: FlexReport query ID (required with flex_token). Pass a list
            of IDs to merge and deduplicate results from multiple queries — useful
            for spans exceeding the FlexReport 365-day per-query limit.
    """
    return await get_trades(
        port=port,
        account=account,
        all_accounts=(account is None),
        symbol=symbol.upper() if symbol else None,
        start_date=start_date,
        end_date=end_date,
        flex_token=flex_token,
        flex_query_id=flex_query_id,
    )


def main():
    mcp.run()


if __name__ == "__main__":
    main()
