#!/usr/bin/env python3
# ABOUTME: CLI wrapper for risk metric calculation.
# ABOUTME: Returns volatility, beta, VaR, drawdown, Sharpe ratio.

import argparse
import json

from trading_skills.risk import calculate_risk_metrics
from trading_skills.utils import generated_at_str


def main():
    parser = argparse.ArgumentParser(description="Calculate risk metrics")
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument("--period", default="1y", help="Analysis period")
    parser.add_argument("--position-size", type=float, help="Position size in dollars")

    args = parser.parse_args()
    result = calculate_risk_metrics(args.symbol.upper(), args.period, args.position_size)
    result["generated_at"] = generated_at_str()
    result["data_delay"] = "15min"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
