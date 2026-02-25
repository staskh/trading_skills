# ABOUTME: Calculates Piotroski's F-Score for a stock.
# ABOUTME: Returns a score from 0-9 based on 9 fundamental criteria.

import pandas as pd
import yfinance as yf

from trading_skills.utils import safe_value


def calculate_piotroski_score(symbol: str, ticker=None) -> dict:
    """Calculate Piotroski F-Score for a stock."""
    ticker = ticker or yf.Ticker(symbol)
    result = {"symbol": symbol.upper(), "score": 0, "max_score": 9, "criteria": {}}

    try:
        # Get quarterly financial statements for criteria 1-4 (most recent year)
        financials = ticker.quarterly_financials
        cashflow = ticker.quarterly_cashflow

        # Get annual financial statements for criteria 5-9 (year-over-year comparison)
        annual_financials = ticker.financials
        annual_balance_sheet = ticker.balance_sheet

        if financials.empty or cashflow.empty:
            result["error"] = "Insufficient quarterly financial data"
            return result

        if annual_financials.empty or annual_balance_sheet.empty:
            result["error"] = "Insufficient annual financial data"
            return result

        # Most recent year (last 4 quarters) for criteria 1-4
        recent_fin = financials.iloc[:, :4] if financials.shape[1] >= 4 else financials
        recent_cf = cashflow.iloc[:, :4] if cashflow.shape[1] >= 4 else cashflow

        # Annual data for year-over-year comparisons (criteria 5-9)
        recent_annual_fin = (
            annual_financials.iloc[:, 0] if annual_financials.shape[1] >= 1 else None
        )
        prev_annual_fin = annual_financials.iloc[:, 1] if annual_financials.shape[1] >= 2 else None

        recent_annual_bs = (
            annual_balance_sheet.iloc[:, 0] if annual_balance_sheet.shape[1] >= 1 else None
        )
        prev_annual_bs = (
            annual_balance_sheet.iloc[:, 1] if annual_balance_sheet.shape[1] >= 2 else None
        )

        def get_value(df, index_name):
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return None
            try:
                if isinstance(df, pd.Series):
                    if index_name in df.index:
                        return safe_value(df.loc[index_name])
                elif isinstance(df, pd.DataFrame):
                    if index_name in df.index:
                        val = df.loc[index_name]
                        if isinstance(val, pd.Series):
                            return val.sum() if len(val) > 0 else None
                        return safe_value(val)
            except Exception:
                pass
            return None

        # Get recent year totals (from quarterly data for criteria 1-4)
        recent_ni = get_value(recent_fin, "Net Income")

        # Operating cash flow (from quarterly data)
        recent_ocf = get_value(recent_cf, "Operating Cash Flow")

        # Balance sheet items - use annual data for year-over-year comparison
        recent_current_assets = (
            get_value(recent_annual_bs, "Current Assets") if recent_annual_bs is not None else None
        )
        recent_current_liab = (
            get_value(recent_annual_bs, "Current Liabilities")
            if recent_annual_bs is not None
            else None
        )
        recent_total_assets = (
            get_value(recent_annual_bs, "Total Assets") if recent_annual_bs is not None else None
        )
        recent_lt_debt = (
            get_value(recent_annual_bs, "Long Term Debt") if recent_annual_bs is not None else None
        )

        prev_current_assets = (
            get_value(prev_annual_bs, "Current Assets") if prev_annual_bs is not None else None
        )
        prev_current_liab = (
            get_value(prev_annual_bs, "Current Liabilities") if prev_annual_bs is not None else None
        )
        prev_total_assets = (
            get_value(prev_annual_bs, "Total Assets") if prev_annual_bs is not None else None
        )
        prev_lt_debt = (
            get_value(prev_annual_bs, "Long Term Debt") if prev_annual_bs is not None else None
        )

        # Shares outstanding - use annual data
        recent_shares = (
            get_value(recent_annual_bs, "Share Issued") if recent_annual_bs is not None else None
        )
        prev_shares = (
            get_value(prev_annual_bs, "Share Issued") if prev_annual_bs is not None else None
        )

        # Gross margin and asset turnover - use annual data for comparison
        recent_annual_revenue = (
            get_value(recent_annual_fin, "Total Revenue") if recent_annual_fin is not None else None
        )
        prev_annual_revenue = (
            get_value(prev_annual_fin, "Total Revenue") if prev_annual_fin is not None else None
        )
        recent_annual_gross_profit = (
            get_value(recent_annual_fin, "Gross Profit") if recent_annual_fin is not None else None
        )
        prev_annual_gross_profit = (
            get_value(prev_annual_fin, "Gross Profit") if prev_annual_fin is not None else None
        )

        # Calculate ROA
        recent_roa = (
            (recent_ni / recent_total_assets) if recent_ni and recent_total_assets else None
        )

        # Calculate current ratio
        recent_current_ratio = (
            (recent_current_assets / recent_current_liab)
            if recent_current_assets and recent_current_liab
            else None
        )
        prev_current_ratio = (
            (prev_current_assets / prev_current_liab)
            if prev_current_assets and prev_current_liab
            else None
        )

        # Calculate gross margin - use annual data
        recent_gross_margin = (
            (recent_annual_gross_profit / recent_annual_revenue)
            if recent_annual_gross_profit and recent_annual_revenue
            else None
        )
        prev_gross_margin = (
            (prev_annual_gross_profit / prev_annual_revenue)
            if prev_annual_gross_profit and prev_annual_revenue
            else None
        )

        # Calculate asset turnover - use annual data
        recent_asset_turnover = (
            (recent_annual_revenue / recent_total_assets)
            if recent_annual_revenue and recent_total_assets
            else None
        )
        prev_asset_turnover = (
            (prev_annual_revenue / prev_total_assets)
            if prev_annual_revenue and prev_total_assets
            else None
        )

        # Criterion 1: Positive Net Income
        criterion_1 = bool(recent_ni > 0) if recent_ni is not None else False
        result["criteria"]["1_positive_net_income"] = {
            "passed": criterion_1,
            "value": safe_value(recent_ni),
            "description": "Net Income > 0",
        }
        if criterion_1:
            result["score"] += 1

        # Criterion 2: Positive ROA
        criterion_2 = bool(recent_roa > 0) if recent_roa is not None else False
        result["criteria"]["2_positive_roa"] = {
            "passed": criterion_2,
            "value": safe_value(recent_roa),
            "description": "Return on Assets > 0",
        }
        if criterion_2:
            result["score"] += 1

        # Criterion 3: Positive Operating Cash Flow
        criterion_3 = bool(recent_ocf > 0) if recent_ocf is not None else False
        result["criteria"]["3_positive_ocf"] = {
            "passed": criterion_3,
            "value": safe_value(recent_ocf),
            "description": "Operating Cash Flow > 0",
        }
        if criterion_3:
            result["score"] += 1

        # Criterion 4: Cash Flow > Net Income
        criterion_4 = (
            bool(recent_ocf > recent_ni)
            if recent_ocf is not None and recent_ni is not None
            else False
        )
        result["criteria"]["4_cashflow_greater_ni"] = {
            "passed": criterion_4,
            "value": {"ocf": safe_value(recent_ocf), "ni": safe_value(recent_ni)},
            "description": "Operating Cash Flow > Net Income",
        }
        if criterion_4:
            result["score"] += 1

        # Criterion 5: Lower Long-Term Debt
        criterion_5 = (
            bool(recent_lt_debt < prev_lt_debt)
            if recent_lt_debt is not None and prev_lt_debt is not None
            else False
        )
        result["criteria"]["5_lower_leverage"] = {
            "passed": criterion_5,
            "value": {"recent": safe_value(recent_lt_debt), "previous": safe_value(prev_lt_debt)},
            "description": "Long-Term Debt decreased",
            "data_available": recent_lt_debt is not None and prev_lt_debt is not None,
        }
        if criterion_5:
            result["score"] += 1

        # Criterion 6: Higher Current Ratio
        criterion_6 = (
            bool(recent_current_ratio > prev_current_ratio)
            if recent_current_ratio is not None and prev_current_ratio is not None
            else False
        )
        result["criteria"]["6_higher_liquidity"] = {
            "passed": criterion_6,
            "value": {
                "recent": safe_value(recent_current_ratio),
                "previous": safe_value(prev_current_ratio),
            },
            "description": "Current Ratio increased",
            "data_available": recent_current_ratio is not None and prev_current_ratio is not None,
        }
        if criterion_6:
            result["score"] += 1

        # Criterion 7: No New Shares Issued
        criterion_7 = (
            bool(recent_shares <= prev_shares)
            if recent_shares is not None and prev_shares is not None
            else False
        )
        result["criteria"]["7_no_dilution"] = {
            "passed": criterion_7,
            "value": {"recent": safe_value(recent_shares), "previous": safe_value(prev_shares)},
            "description": "No new shares issued (or decreased)",
            "data_available": recent_shares is not None and prev_shares is not None,
        }
        if criterion_7:
            result["score"] += 1

        # Criterion 8: Higher Gross Margin
        criterion_8 = (
            bool(recent_gross_margin > prev_gross_margin)
            if recent_gross_margin is not None and prev_gross_margin is not None
            else False
        )
        result["criteria"]["8_higher_gross_margin"] = {
            "passed": criterion_8,
            "value": {
                "recent": safe_value(recent_gross_margin),
                "previous": safe_value(prev_gross_margin),
            },
            "description": "Gross Margin increased",
            "data_available": recent_gross_margin is not None and prev_gross_margin is not None,
        }
        if criterion_8:
            result["score"] += 1

        # Criterion 9: Higher Asset Turnover
        criterion_9 = (
            bool(recent_asset_turnover > prev_asset_turnover)
            if recent_asset_turnover is not None and prev_asset_turnover is not None
            else False
        )
        result["criteria"]["9_higher_asset_turnover"] = {
            "passed": criterion_9,
            "value": {
                "recent": safe_value(recent_asset_turnover),
                "previous": safe_value(prev_asset_turnover),
            },
            "description": "Asset Turnover increased",
            "data_available": recent_asset_turnover is not None and prev_asset_turnover is not None,
        }
        if criterion_9:
            result["score"] += 1

        # Add interpretation
        if result["score"] >= 8:
            result["interpretation"] = "Excellent - Very strong financial health"
        elif result["score"] >= 6:
            result["interpretation"] = "Good - Strong financial health"
        elif result["score"] >= 4:
            result["interpretation"] = "Fair - Moderate financial health"
        else:
            result["interpretation"] = "Poor - Weak financial health"

    except Exception as e:
        result["error"] = str(e)

    return result
