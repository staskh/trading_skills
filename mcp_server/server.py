#!/usr/bin/env python3
# ABOUTME: MCP server providing trading analysis tools.
# ABOUTME: Exposes quote, technicals, options, fundamentals, and scanner tools.

import os
import sys
from pathlib import Path

# Ensure unbuffered output for MCP protocol (equivalent to python -u)
os.environ["PYTHONUNBUFFERED"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(write_through=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(write_through=True)

from mcp.server.fastmcp import FastMCP

from trading_skills.broker.account import get_account_summary
from trading_skills.broker.portfolio import get_portfolio
from trading_skills.broker.portfolio_action import (
    generate_report as generate_action_report,
    get_portfolio_data,
)
from trading_skills.broker.roll import (
    calculate_roll_options,
    fetch_earnings_date,
    generate_report as generate_roll_report,
    get_current_position,
    get_option_chain_params,
    get_option_quotes,
    get_underlying_price,
)
from trading_skills.correlation import compute_correlation
from trading_skills.earnings import get_earnings_info, get_multiple_earnings
from trading_skills.fundamentals import get_fundamentals
from trading_skills.greeks import calculate_greeks
from trading_skills.history import get_history
from trading_skills.news import get_news
from trading_skills.options import get_expiries, get_option_chain
from trading_skills.piotroski import calculate_piotroski_score
from trading_skills.quote import get_quote
from trading_skills.risk import calculate_risk_metrics
from trading_skills.scanner_bullish import compute_bullish_score, scan_symbols
from trading_skills.scanner_pmcc import analyze_pmcc
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
    return analyze_iron_condor(
        symbol.upper(), expiry, put_long, put_short, call_short, call_long
    )


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
    from datetime import datetime

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

    # Sort by score
    valid_results = [r for r in results if "pmcc_score" in r]
    valid_results.sort(
        key=lambda x: (x["pmcc_score"], x.get("metrics", {}).get("annual_yield_est_pct", 0)),
        reverse=True,
    )

    return {
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "criteria": {
            "leaps_min_days": min_leaps_days,
            "leaps_target_delta": leaps_delta,
            "short_target_delta": short_delta,
        },
        "count": len(valid_results),
        "results": valid_results,
        "errors": [r for r in results if "error" in r],
    }


# ============================================================================
# INTERACTIVE BROKERS TOOLS (Requires TWS/Gateway)
# ============================================================================


@mcp.tool()
async def ib_account(port: int = 7497) -> dict:
    """Get account summary from Interactive Brokers.

    Returns cash balance, buying power, net liquidation value, and margin info.
    Requires TWS or IB Gateway running locally.

    Args:
        port: IB port (7497 for paper trading, 7496 for live)
    """
    return await get_account_summary(port)


@mcp.tool()
async def ib_portfolio(port: int = 7497, account: str | None = None) -> dict:
    """Get portfolio positions from Interactive Brokers.

    Returns all positions including stocks and options with market prices.
    Requires TWS or IB Gateway running locally.

    Args:
        port: IB port (7497 for paper trading, 7496 for live)
        account: Specific account ID (optional, uses first if not specified)
    """
    return await get_portfolio(port, account)


@mcp.tool()
async def ib_find_short_roll(
    symbol: str,
    port: int = 7496,
    account: str | None = None,
    strike: float | None = None,
    expiry: str | None = None,
    right: str = "C",
) -> dict:
    """Find roll options for a short position using real-time IB data.

    Analyzes current short option position and finds roll candidates with
    credit/debit analysis. Generates a markdown report.
    Requires TWS or IB Gateway running locally.

    Args:
        symbol: Ticker symbol (e.g., GOOG)
        port: IB port (7496 for live, 7497 for paper)
        account: Account ID (optional)
        strike: Current short strike (optional, auto-detects from portfolio)
        expiry: Current expiry YYYYMMDD (optional, auto-detects from portfolio)
        right: 'C' for call or 'P' for put (default: C)
    """
    from datetime import datetime

    from ib_async import IB

    ib = IB()
    try:
        await ib.connectAsync("127.0.0.1", port, clientId=30)
    except Exception as e:
        return {"error": f"Could not connect to IB on port {port}: {e}"}

    try:
        # Get position or use provided params
        if strike and expiry:
            current_position = {
                "quantity": -1,
                "strike": strike,
                "expiry": expiry,
                "right": right,
                "account": account or "N/A",
            }
        else:
            current_position = await get_current_position(ib, symbol.upper(), account)
            if not current_position:
                return {
                    "error": f"No short option position found for {symbol}. "
                    "Use strike and expiry params to specify manually."
                }

        # Get underlying price
        underlying_price = await get_underlying_price(ib, symbol.upper())

        # Get option chain parameters
        chain_params = await get_option_chain_params(ib, symbol.upper())

        # Get current option quote
        current_quotes = await get_option_quotes(
            ib,
            symbol.upper(),
            current_position["expiry"],
            [current_position["strike"]],
            current_position["right"],
        )

        if not current_quotes:
            return {"error": "Could not get quote for current position"}

        current_quote = current_quotes[0]
        buy_price = current_quote["ask"]

        # Get future expirations
        current_exp = current_position["expiry"]
        future_exps = [e for e in chain_params["expirations"] if e > current_exp][:5]

        if not future_exps:
            return {"error": "No future expirations available"}

        # Determine strike range
        current_strike = current_position["strike"]
        all_strikes = chain_params["strikes"]

        if current_position["right"] == "C":
            target_strikes = [
                s
                for s in all_strikes
                if current_strike - 10 <= s <= current_strike + 50 and s % 5 == 0
            ]
        else:
            target_strikes = [
                s
                for s in all_strikes
                if current_strike - 50 <= s <= current_strike + 10 and s % 5 == 0
            ]

        target_strikes = sorted(target_strikes)[:10]

        # Fetch quotes for each target expiration
        roll_data = {}
        for exp in future_exps:
            quotes = await get_option_quotes(
                ib, symbol.upper(), exp, target_strikes, current_position["right"]
            )
            roll_data[exp] = calculate_roll_options(current_position, quotes, buy_price)

        # Fetch earnings date
        earnings_date = fetch_earnings_date(symbol.upper())

        # Generate report
        report = generate_roll_report(
            symbol.upper(),
            underlying_price,
            current_position,
            current_quote,
            roll_data,
            earnings_date,
        )

        # Save report
        sandbox_dir = Path(__file__).parent.parent / "sandbox"
        sandbox_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        report_path = sandbox_dir / f"ib_short_report_{symbol.upper()}_{timestamp}.md"
        report_path.write_text(report, encoding="utf-8")

        return {
            "success": True,
            "symbol": symbol.upper(),
            "current_position": {
                "strike": current_position["strike"],
                "expiry": current_position["expiry"],
                "right": current_position["right"],
                "quantity": current_position["quantity"],
            },
            "underlying_price": underlying_price,
            "buy_to_close": buy_price,
            "report_path": str(report_path),
            "expirations_analyzed": future_exps,
        }

    finally:
        ib.disconnect()


@mcp.tool()
async def ib_portfolio_action_report(
    output_dir: str,
    port: int = 7497,
    account: str | None = None,
) -> dict:
    """Generate comprehensive portfolio action report with earnings and risk assessment.

    Analyzes all positions, categorizes by urgency/risk, and generates
    a markdown report with recommendations.
    Requires TWS or IB Gateway running locally.

    Args:
        output_dir: Directory to store report
        port: IB port (7497 for paper trading, 7496 for live)
        account: Specific account ID (optional)
    """
    from datetime import datetime

    # Fetch portfolio data
    data = await get_portfolio_data(port, account)

    if "error" in data:
        return {"error": data["error"]}

    # Create output directory
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    # Generate report
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    accounts = data.get("accounts", [])
    account_suffix = accounts[0] if len(accounts) == 1 else "multi" if accounts else "unknown"
    md_path = report_dir / f"ib_portfolio_action_report_{account_suffix}_{timestamp}.md"

    generate_action_report(data, md_path)

    return {
        "success": True,
        "markdown_path": str(md_path),
        "accounts": data.get("accounts", []),
        "total_positions": sum(len(p) for p in data.get("positions", {}).values()),
    }


def main():
    mcp.run()


if __name__ == "__main__":
    main()
