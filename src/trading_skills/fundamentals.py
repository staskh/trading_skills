# ABOUTME: Fetches fundamental financial data from Yahoo Finance.
# ABOUTME: Returns financials, earnings, and key company metrics.

import yfinance as yf

from trading_skills.utils import safe_value


def get_fundamentals(symbol: str, data_type: str = "all") -> dict:
    """Fetch fundamental data for a symbol."""
    ticker = yf.Ticker(symbol)
    result = {"symbol": symbol.upper()}

    # Handle each data type separately to avoid one failure blocking others
    if data_type in ["all", "info"]:
        try:
            info = ticker.info
            result["info"] = {
                "name": info.get("shortName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "marketCap": info.get("marketCap"),
                "enterpriseValue": info.get("enterpriseValue"),
                "trailingPE": info.get("trailingPE"),
                "forwardPE": info.get("forwardPE"),
                "pegRatio": info.get("pegRatio"),
                "priceToBook": info.get("priceToBook"),
                "eps": info.get("trailingEps"),
                "forwardEps": info.get("forwardEps"),
                "dividendYield": info.get("dividendYield"),
                "dividendRate": info.get("dividendRate"),
                "payoutRatio": info.get("payoutRatio"),
                "beta": info.get("beta"),
                "profitMargin": info.get("profitMargins"),
                "operatingMargin": info.get("operatingMargins"),
                "returnOnEquity": info.get("returnOnEquity"),
                "returnOnAssets": info.get("returnOnAssets"),
                "revenueGrowth": info.get("revenueGrowth"),
                "earningsGrowth": info.get("earningsGrowth"),
                "currentRatio": info.get("currentRatio"),
                "debtToEquity": info.get("debtToEquity"),
                "freeCashflow": info.get("freeCashflow"),
                "sharesOutstanding": info.get("sharesOutstanding"),
                "floatShares": info.get("floatShares"),
                "shortRatio": info.get("shortRatio"),
            }
        except Exception as e:
            result["info_error"] = str(e)
            result["info"] = {}

    if data_type in ["all", "financials"]:
        try:
            # Get quarterly financials
            financials = ticker.quarterly_financials
            if not financials.empty:
                # Get last 4 quarters
                fin_data = []
                for col in financials.columns[:4]:
                    quarter_data = {"period": col.strftime("%Y-%m-%d")}
                    for idx in financials.index:
                        quarter_data[idx] = safe_value(financials.loc[idx, col])
                    fin_data.append(quarter_data)
                result["financials"] = fin_data
            else:
                result["financials"] = []
        except Exception as e:
            result["financials_error"] = str(e)
            result["financials"] = []

    if data_type in ["all", "earnings"]:
        try:
            # Get earnings data
            earnings = ticker.earnings_dates
            if earnings is not None and not earnings.empty:
                earnings_data = []
                for date, row in earnings.head(8).iterrows():
                    earnings_data.append(
                        {
                            "date": date.strftime("%Y-%m-%d"),
                            "epsEstimate": safe_value(row.get("EPS Estimate")),
                            "epsActual": safe_value(row.get("Reported EPS")),
                            "surprise": safe_value(row.get("Surprise(%)")),
                        }
                    )
                result["earnings"] = earnings_data
            else:
                result["earnings"] = []
        except Exception as e:
            # Handle specific error types
            error_msg = str(e)
            if isinstance(e, KeyError) and "Earnings Date" in error_msg:
                result["earnings_error"] = f"Earnings data unavailable: {error_msg}"
            else:
                result["earnings_error"] = error_msg
            result["earnings"] = []

    return result
