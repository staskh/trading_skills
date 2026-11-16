# ABOUTME: Renders a daily candlestick chart with fast/slow EMAs, their crossovers and an RSI
# ABOUTME: panel to a JPG, and returns the latest indicator values and crossovers as a dict.

from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402
import pandas_ta as ta  # noqa: E402
import yfinance as yf  # noqa: E402

from trading_skills.utils import generated_at_str  # noqa: E402

PERIOD_DAYS = {"1mo": 31, "3mo": 92, "6mo": 183, "1y": 365, "2y": 730}
# Extra calendar days downloaded before the plotted window so EMAs and RSI are settled.
WARMUP_DAYS = 120
SMA_COLORS = ("tab:green", "tab:red", "tab:brown", "tab:gray")
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
# The yahoo style asks for a semibold title, which DejaVu Sans lacks (matplotlib logs a warning).
CHART_STYLE = mpf.make_mpf_style(base_mpf_style="yahoo", rc={"figure.titleweight": "bold"})


def ema_crossovers(fast: pd.Series, slow: pd.Series) -> list[dict]:
    """Dates where the fast line crosses the slow one: `golden` upward, `death` downward.

    Bars where the lines are equal or either is missing don't count as a side; the cross is
    dated on the first bar the fast line is clearly on the new side.
    """
    diff = (fast - slow).dropna()
    sides = diff[diff != 0].apply(lambda d: 1 if d > 0 else -1)
    changed = sides[sides != sides.shift()].iloc[1:]
    return [
        {
            "date": date.strftime("%Y-%m-%d"),
            "type": "golden" if side > 0 else "death",
            "ema_fast": round(float(fast[date]), 2),
        }
        for date, side in changed.items()
    ]


def sma_lines(close: pd.Series, lengths, in_window) -> dict[int, pd.Series]:
    """SMA series (restricted to `in_window`) per length; uncomputable lengths are left out.

    pandas_ta returns None when the series is shorter than the length, and a line that is NaN
    across the whole window has nothing to draw.
    """
    lines = {}
    for n in lengths:
        line = ta.sma(close, length=n)
        if line is not None and line[in_window].notna().any():
            lines[n] = line[in_window]
    return lines


def _markers(bars: pd.DataFrame, crosses: list[dict], kind: str) -> pd.Series:
    """Marker y-values for one crossover type: under the low (golden), over the high (death)."""
    marks = pd.Series(float("nan"), index=bars.index)
    for c in crosses:
        if c["type"] != kind:
            continue
        date = pd.Timestamp(c["date"])
        if kind == "golden":
            marks[date] = bars.at[date, "Low"] * 0.985
        else:
            marks[date] = bars.at[date, "High"] * 1.015
    return marks


def render_chart(
    symbol: str,
    period: str = "6mo",
    fast: int = 9,
    slow: int = 20,
    rsi_length: int = 14,
    output: str | Path | None = None,
    sma: tuple[int, ...] = (),
    levels: dict[str, float] | None = None,
) -> dict:
    """Plot daily candles with EMA(fast)/EMA(slow), crossover markers and RSI to a JPG.

    `output` defaults to `sandbox/<SYMBOL>_ema_rsi_YYYY-MM-DD_HHmm.jpg`. `sma` adds simple moving
    averages (extra history is fetched so they are defined across the whole window; one that can't
    be computed is skipped) and `levels` adds labelled horizontal lines, e.g. pivot supports.
    The result's `sma` and `levels` list what was drawn.
    """
    if fast >= slow:
        raise ValueError(f"fast EMA ({fast}) must be shorter than slow EMA ({slow})")
    if period not in PERIOD_DAYS:
        raise ValueError(f"period must be one of {sorted(PERIOD_DAYS)}")

    symbol = symbol.upper()
    levels = dict(levels or {})
    # ~1.5 calendar days per trading bar, plus slack for holidays.
    sma_days = int(max(sma) * 1.5) + 10 if sma else 0
    start = datetime.now() - timedelta(days=PERIOD_DAYS[period] + max(WARMUP_DAYS, sma_days))
    history = yf.Ticker(symbol).history(start=start.strftime("%Y-%m-%d"), interval="1d")
    if history.empty or len(history) <= slow:
        return {"symbol": symbol, "error": "No price history"}

    history.index = history.index.tz_localize(None)
    close = history["Close"]
    ema_fast = ta.ema(close, length=fast)
    ema_slow = ta.ema(close, length=slow)
    rsi = ta.rsi(close, length=rsi_length)

    window_start = pd.Timestamp(datetime.now() - timedelta(days=PERIOD_DAYS[period]))
    in_window = history.index >= window_start
    bars = history.loc[in_window, ["Open", "High", "Low", "Close", "Volume"]]
    ema_fast, ema_slow, rsi = ema_fast[in_window], ema_slow[in_window], rsi[in_window]
    crosses = ema_crossovers(ema_fast, ema_slow)
    sma_by_length = sma_lines(close, sma, in_window)

    if output is None:
        stamp = generated_at_str().replace(" ET", "").replace(":", "").replace(" ", "_")
        output = Path("sandbox") / f"{symbol}_ema_rsi_{stamp}.jpg"
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    rsi_panel = dict(panel=1, ylim=(0, 100), ylabel=f"RSI {rsi_length}")
    band = dict(color="gray", linestyle="--", width=0.8, **rsi_panel)
    plots = [
        mpf.make_addplot(ema_fast, color="tab:blue", width=1.2),
        mpf.make_addplot(ema_slow, color="tab:orange", width=1.2),
        mpf.make_addplot(rsi, color="purple", width=1.0, **rsi_panel),
        mpf.make_addplot(pd.Series(RSI_OVERBOUGHT, index=bars.index), **band),
        mpf.make_addplot(pd.Series(RSI_OVERSOLD, index=bars.index), **band),
    ]
    for kind, marker, color in (("golden", "^", "green"), ("death", "v", "red")):
        marks = _markers(bars, crosses, kind)
        if marks.notna().any():
            plots.append(
                mpf.make_addplot(marks, type="scatter", marker=marker, markersize=120, color=color)
            )

    for n, color in zip(sma_by_length, SMA_COLORS):
        plots.append(mpf.make_addplot(sma_by_length[n], color=color, width=1.2, linestyle="--"))

    last_close = round(float(bars["Close"].iloc[-1]), 2)
    last_rsi = round(float(rsi.iloc[-1]), 2)
    sma_legend = "".join(f"  SMA{n} ({c[4:]})" for n, c in zip(sma_by_length, SMA_COLORS))
    title = (
        f"{symbol} daily  close {last_close}  EMA{fast} (blue) / EMA{slow} (orange)"
        f"{sma_legend}  RSI {last_rsi}"
    )
    hlines = dict(hlines=list(levels.values()), colors="gray", linestyle=":", linewidths=0.9)
    fig, axes = mpf.plot(
        bars,
        type="candle",
        style=CHART_STYLE,
        addplot=plots,
        volume=False,
        panel_ratios=(3, 1),
        title=title,
        figsize=(14, 8),
        tight_layout=True,
        returnfig=True,
        **(dict(hlines=hlines) if levels else {}),
    )
    price_ax = axes[0]
    low, high = price_ax.get_ylim()
    if levels:
        pad = (max(high, *levels.values()) - min(low, *levels.values())) * 0.03
        low, high = min(low, *levels.values()) - pad, max(high, *levels.values()) + pad
        price_ax.set_ylim(low, high)
    for label, value in levels.items():
        price_ax.annotate(
            f"{label} {value:g}",
            xy=(0.995, value),
            xycoords=("axes fraction", "data"),
            fontsize=9,
            color="black",
            ha="right",
            va="bottom",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="gray", alpha=0.9),
        )
    fig.savefig(str(output), dpi=120, pil_kwargs={"quality": 90})
    matplotlib.pyplot.close(fig)

    return {
        "symbol": symbol,
        "path": str(output),
        "period": period,
        "last_date": bars.index[-1].strftime("%Y-%m-%d"),
        "close": last_close,
        "ema_fast_length": fast,
        "ema_slow_length": slow,
        "ema_fast": round(float(ema_fast.iloc[-1]), 2),
        "ema_slow": round(float(ema_slow.iloc[-1]), 2),
        "trend": "bullish" if ema_fast.iloc[-1] > ema_slow.iloc[-1] else "bearish",
        "rsi": last_rsi,
        "bars_fetched": len(history),
        "sma": list(sma_by_length),
        "levels": levels,
        "price_ylim": [round(float(low), 2), round(float(high), 2)],
        "crossovers": crosses,
        "generated_at": generated_at_str(),
        "data_delay": "15min",
    }
