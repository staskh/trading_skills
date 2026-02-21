# Trading Skills MCP Server

MCP server providing trading analysis tools for stock quotes, technical analysis, options, and scanners.

## Running the Server

```bash
# Using the project's virtual environment Python
.venv/bin/python -m mcp_server.server
```

## Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "trading-skills": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/staskh/trading_skills.git", "trading-skills"]
    }
  }
}
```

## Available Tools (23)

### Market Data
- **stock_quote** - Get real-time quote with price, volume, change
- **price_history** - Get historical OHLCV data
- **news_sentiment** - Get recent news headlines

### Fundamental Analysis
- **fundamentals** - Get financial metrics, statements, earnings
- **piotroski_score** - Calculate Piotroski F-Score (0-9)
- **earnings_calendar** - Get upcoming earnings dates

### Technical Analysis
- **technical_indicators** - Compute RSI, MACD, Bollinger Bands, SMA, EMA, ATR, ADX
- **price_correlation** - Compute correlation matrix between symbols
- **risk_assessment** - Calculate volatility, beta, VaR, drawdown, Sharpe ratio

### Options
- **option_expiries** - List available expiration dates
- **option_chain** - Get full chain (calls/puts) for an expiry
- **option_greeks** - Calculate delta, gamma, theta, vega, IV

### Spread Analysis
- **spread_vertical** - Analyze bull/bear call/put spreads
- **spread_diagonal** - Analyze diagonal spreads (PMCC)
- **spread_straddle** - Analyze long straddles
- **spread_strangle** - Analyze long strangles
- **spread_iron_condor** - Analyze iron condors

### Scanners
- **scan_bullish** - Scan for bullish trends using technical indicators
- **scan_pmcc** - Scan for Poor Man's Covered Call suitability

### Interactive Brokers (requires TWS/Gateway)
- **ib_account** - Get account summary (cash, buying power, margin)
- **ib_portfolio** - Get portfolio positions with market prices
- **ib_find_short_roll** - Find roll options for short positions
- **ib_portfolio_action_report** - Generate comprehensive portfolio action report

## Example Usage

```python
from mcp_server.server import stock_quote, technical_indicators

# Get stock quote
quote = stock_quote("AAPL")
print(f"AAPL: ${quote['price']}")

# Get technical indicators
technicals = technical_indicators("AAPL", period="3mo", indicators="rsi,macd")
print(f"RSI: {technicals['indicators']['rsi']['value']}")
```
