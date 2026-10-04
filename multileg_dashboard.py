#!/usr/bin/env python3
"""
Multi-Leg Options Dashboard: strategy proposals and P&L monitoring (absolute and % of risk).
Launch: uv run streamlit run multileg_dashboard.py
Proposals only. No orders are placed. Tracked positions are a local journal in sandbox/multileg/.
"""

import asyncio
import json
import math
import random
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ib_async (eventkit) needs an event loop at import time; Streamlit's script thread has none.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from trading_skills.black_scholes import black_scholes_delta, black_scholes_price
from trading_skills.broker.multileg import (
    assemble_proposal,
    load_config,
    mark_positions,
    propose_trades,
)
from trading_skills.multileg import BUILDERS, Chain, Leg, Opt, leg_key, pl_at_expiry, position_pnl

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
DATA = ROOT / "sandbox" / "multileg"
JOURNAL = DATA / "journal.json"
HISTORY = DATA / "pnl_history.csv"
CONFIG = ROOT / ".claude/skills/ib-multileg-options/references/multileg_options_config.yaml"
DATA.mkdir(parents=True, exist_ok=True)
NY = ZoneInfo("America/New_York")
MULT = 100

STATUS_ICON = {
    "valid": "✅",
    "failed_validation": "❌",
    "gated": "⛔",
    "disabled_in_config": "🚫",
    "build_failed": "⚠️",
}


def run_async(coro):
    """Run an IB coroutine on a fresh loop bound to this Streamlit thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def money(v: float) -> str:
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def now_ny() -> datetime:
    return datetime.now(NY)


# ── Journal ───────────────────────────────────────────────────────────────────


def load_journal() -> list[dict]:
    if JOURNAL.exists():
        return json.loads(JOURNAL.read_text(encoding="utf-8"))
    return []


def save_journal(rows: list[dict]) -> None:
    JOURNAL.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def track(proposal: dict, cand: dict, contracts: int, mode: str) -> None:
    rows = load_journal()
    rows.append(
        {
            "id": uuid.uuid4().hex[:8],
            "mode": mode,
            "status": "open",
            "opened_at": now_ny().strftime("%Y-%m-%d %H:%M"),
            "symbol": proposal["symbol"],
            "expiry": proposal["expiry"],
            "trading_class": proposal.get("trading_class", ""),
            "strategy": cand["strategy"],
            "proposal_status": cand["status"],
            "contracts": contracts,
            "spot_at_entry": proposal["underlying_price"],
            "legs": cand["legs"],
            "analysis": cand["analysis"],
            "exit_plan": cand["exit_plan"],
            "regime": proposal["regime"],
        }
    )
    save_journal(rows)


def close_position(pid: str, mark: dict) -> None:
    rows = load_journal()
    for r in rows:
        if r["id"] == pid:
            r["status"] = "closed"
            r["closed_at"] = now_ny().strftime("%Y-%m-%d %H:%M")
            r["realized_pnl"] = mark.get("pnl")
            r["realized_pct_of_risk"] = mark.get("pct_of_risk")
    save_journal(rows)


def append_history(rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    df.to_csv(HISTORY, mode="a", header=not HISTORY.exists(), index=False)


# ── Demo data (no IB) ─────────────────────────────────────────────────────────

DEMO_SPOTS = {"SPX": 5000.0, "RUT": 2200.0, "NDX": 18000.0, "SPY": 500.0, "QQQ": 440.0}


def demo_chain(spot, dte, base_iv, r=0.04, skew=0.6):
    t = max(dte, 1 / 24) / 365
    step = 5 if spot > 1000 else 1
    opts = []
    for k in np.arange(round(spot * 0.8 / step) * step, spot * 1.2, step):
        k = float(k)
        iv = max(0.06, base_iv - skew * base_iv * math.log(k / spot))
        for right, kind in (("C", "call"), ("P", "put")):
            mid = black_scholes_price(spot, k, t, r, iv, kind)
            if mid < 0.05:
                continue
            half = max(0.05, mid * 0.01)
            opts.append(
                Opt(
                    k,
                    right,
                    round(max(0.01, mid - half), 2),
                    round(mid + half, 2),
                    black_scholes_delta(spot, k, t, r, iv, kind),
                    iv,
                )
            )
    return Chain(opts, spot, t, r)


def demo_proposal(symbol, target_dte, cfg, **kw):
    rng = random.Random(f"{symbol}{date.today()}")
    spot = DEMO_SPOTS.get(symbol, 100.0 + rng.random() * 400)
    drift = rng.choice([-0.003, 0.0, 0.003])
    closes = [spot * (1 + drift) ** (i - 250) * (1 + rng.gauss(0, 0.006)) for i in range(251)]
    bars = [SimpleNamespace(close=c, high=c * 1.005, low=c * 0.995) for c in closes]
    base_iv = rng.choice([0.13, 0.18, 0.24])
    iv_series = [max(0.08, base_iv + 0.06 * math.sin(i / 30)) for i in range(250)]
    iv_series.append(iv_series[-1] * rng.choice([0.97, 1.0, 1.03]))
    exp_date = date.today() + timedelta(days=int(target_dte))
    while exp_date.weekday() != 4:  # Friday
        exp_date += timedelta(days=1)
    dte = (exp_date - date.today()).days + 0.3
    out = assemble_proposal(
        symbol,
        demo_chain(spot, dte, iv_series[-1]),
        bars=bars,
        iv_series=iv_series,
        cfg=cfg,
        expiry=exp_date.strftime("%Y%m%d"),
        trading_class=symbol,
        dte=dte,
        source="demo",
        **kw,
    )
    out["underlying_price"] = round(spot, 2)
    return out


def demo_marks(positions, days_elapsed, move_pct, r=0.04):
    spots, mids = {}, {}
    for p in positions:
        spot = p["spot_at_entry"] * (1 + move_pct / 100)
        spots[p["symbol"]] = spot
        exp = datetime.strptime(p["expiry"], "%Y%m%d").date()
        opened = datetime.strptime(p["opened_at"][:10], "%Y-%m-%d").date()
        t = max((exp - opened).days - days_elapsed, 1 / 24) / 365
        for leg in p["legs"]:
            kind = "call" if leg["right"] == "C" else "put"
            iv = leg.get("iv") or 0.2
            mids[leg_key(p["symbol"], p["expiry"], leg["strike"], leg["right"])] = (
                black_scholes_price(spot, leg["strike"], t, r, iv, kind)
            )
    return {"success": True, "spots": spots, "mids": mids}


# ── Charts ────────────────────────────────────────────────────────────────────


def payoff_chart(legs: list[dict], spot: float, contracts: int, bes=None, title=""):
    objs = [
        Leg(
            leg["qty"] if leg["action"] == "BUY" else -leg["qty"],
            Opt(leg["strike"], leg["right"], leg["mid"], leg["mid"], None, None),
        )
        for leg in legs
    ]
    ks = [leg["strike"] for leg in legs]
    lo, hi = min(min(ks), spot) * 0.97, max(max(ks), spot) * 1.03
    xs = np.linspace(lo, hi, 400)
    ys = [pl_at_expiry(objs, x) * MULT * contracts for x in xs]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=xs, y=ys, mode="lines", name="P/L at expiry", line=dict(color="#4c78a8"))
    )
    fig.add_hline(y=0, line_color="gray", line_width=1)
    fig.add_vline(x=spot, line_dash="dash", line_color="#f58518", annotation_text="spot")
    for be in bes or []:
        fig.add_vline(x=be, line_dash="dot", line_color="#e45756", annotation_text="BE")
    fig.update_layout(
        title=title, height=300, margin=dict(l=10, r=10, t=40, b=10), yaxis_title="$ P/L"
    )
    return fig


# ── Sidebar ───────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Multi-Leg Options", page_icon="🦆", layout="wide")
st.title("🦆 Multi-Leg Options: Proposals & P&L")
st.caption("Proposals only. No orders are placed. Enter trades yourself, then track them here.")

with st.sidebar:
    st.header("Settings")
    mode = st.radio("Data source", ["Live IB", "Demo (synthetic)"], horizontal=True)
    demo = mode.startswith("Demo")
    port = st.number_input("IB port (7497 paper, 7496 live)", value=7497, step=1, disabled=demo)
    watchlist = st.text_input("Watchlist", "SPX, SPY, QQQ, IWM")
    target_dte = st.slider("Target DTE", 1, 45, 14)
    account_value = st.number_input("Account value ($)", value=50000.0, step=5000.0)
    with st.expander("Overrides"):
        strat_override = st.multiselect("Strategies (empty = auto from regime)", list(BUILDERS))
        direction = st.selectbox("Direction", ["auto", "BULL", "BEAR", "NEUTRAL"])
        earnings = st.checkbox("Earnings before expiry")
    st.divider()
    refresh_s = st.select_slider(
        "Auto-refresh P&L",
        [0, 30, 60, 120, 300],
        value=0,
        format_func=lambda s: "off" if s == 0 else f"{s}s",
    )
    if demo:
        st.subheader("Demo simulation")
        demo_days = st.slider("Days elapsed since entry", 0, 21, 0)
        demo_move = st.slider("Underlying move since entry (%)", -10.0, 10.0, 0.0, 0.5)

cfg = load_config(CONFIG)
symbols = [s.strip().upper() for s in watchlist.split(",") if s.strip()]
tab_prop, tab_pnl, tab_closed = st.tabs(["📡 Proposals", "💰 P&L Monitor", "📕 Closed"])


# ── Proposals ─────────────────────────────────────────────────────────────────


def run_scan() -> dict:
    kw = dict(
        strategies=strat_override or None,
        direction=None if direction == "auto" else direction,
        earnings=earnings,
        account_value=account_value,
    )
    out = {}
    progress = st.progress(0.0, "Scanning…")
    for i, sym in enumerate(symbols):
        progress.progress(i / len(symbols), f"Scanning {sym}…")
        if demo:
            out[sym] = demo_proposal(sym, target_dte, cfg, **kw)
        else:
            out[sym] = run_async(
                propose_trades(
                    sym, port=int(port), target_dte=target_dte, config_path=str(CONFIG), **kw
                )
            )
    progress.empty()
    stamp = now_ny().strftime("%Y-%m-%d_%H%M")
    (DATA / f"proposals_{stamp}.json").write_text(json.dumps(out, indent=2, default=float))
    return out


def latest_saved() -> dict:
    files = sorted(DATA.glob("proposals_*.json"))
    return json.loads(files[-1].read_text()) if files else {}


with tab_prop:
    c1, c2 = st.columns([1, 4])
    if c1.button("🔎 Scan watchlist", type="primary"):
        st.session_state["proposals"] = run_scan()
        st.session_state["scanned_at"] = now_ny().strftime("%Y-%m-%d %H:%M ET")
    if "proposals" not in st.session_state:
        st.session_state["proposals"] = latest_saved()
        st.session_state["scanned_at"] = "last saved scan"
    props = st.session_state["proposals"]
    c2.caption(f"Scanned: {st.session_state.get('scanned_at', '-')}")

    if not props:
        st.info("No proposals yet. Click **Scan watchlist**.")
    else:
        summary = []
        for sym, p in props.items():
            if not p.get("success"):
                summary.append({"Symbol": sym, "Error": p.get("error")})
                continue
            rg = p["regime"]
            summary.append(
                {
                    "Symbol": sym,
                    "Spot": p["underlying_price"],
                    "Expiry": p["expiry"],
                    "DTE": p["dte"],
                    "Direction": rg["direction"],
                    "IV level": rg["iv_level"],
                    "IV rank": rg["iv_rank"],
                    "IV trend": rg["iv_trend"],
                    "Call-rich": rg["call_rich"],
                    "Recommended": p["recommended"] or "—",
                }
            )
        st.dataframe(pd.DataFrame(summary), hide_index=True, use_container_width=True)

        for sym, p in props.items():
            if not p.get("success"):
                continue
            rg = p["regime"]
            head = (
                f"{sym} {p['underlying_price']:,} · {rg['direction']} · IV {rg['iv_level']} "
                f"({rg['iv_trend']}) · "
                + (f"✅ {p['recommended']}" if p["recommended"] else "no valid trade")
            )
            with st.expander(head, expanded=bool(p["recommended"])):
                for w in p.get("warnings", []):
                    st.warning(w)
                rows = []
                for c in p["candidates"]:
                    a = c.get("analysis", {})
                    rows.append(
                        {
                            "": STATUS_ICON.get(c["status"], "⏭️"),
                            "Strategy": c["strategy"],
                            "Status": c["status"],
                            "Net (+cr/−db)": a.get("net_price"),
                            "Max profit $": a.get("max_profit", 0) * MULT if a else None,
                            "Max loss $": a.get("max_loss", 0) * MULT if a else None,
                            "POP": a.get("pop"),
                            "Breakevens": ", ".join(f"{b:,.0f}" for b in a.get("breakevens", [])),
                            "Failed checks": ", ".join(
                                k for k, v in c.get("checks", {}).items() if not v
                            )
                            or (c.get("gate_reason") or ""),
                        }
                    )
                st.dataframe(
                    pd.DataFrame(rows),
                    hide_index=True,
                    use_container_width=True,
                    column_config={"POP": st.column_config.NumberColumn(format="percent")},
                )
                buildable = [c for c in p["candidates"] if "legs" in c]
                if not buildable:
                    continue
                default = next((i for i, c in enumerate(buildable) if c["status"] == "valid"), 0)
                choice = st.selectbox(
                    "Inspect candidate",
                    range(len(buildable)),
                    index=default,
                    format_func=lambda i: (
                        f"{STATUS_ICON.get(buildable[i]['status'], '')} {buildable[i]['strategy']}"
                    ),
                    key=f"sel_{sym}",
                )
                cand = buildable[choice]
                a = cand["analysis"]
                m = st.columns(5)
                m[0].metric(a["price_type"].title(), f"{abs(a['net_price']):.2f}")
                m[1].metric("Max profit", f"${a['max_profit'] * MULT:,.0f}")
                m[2].metric("Max loss", f"${a['max_loss'] * MULT:,.0f}")
                m[3].metric("POP", f"{a['pop']:.0%}")
                m[4].metric("Contracts (5% risk)", cand.get("sizing", {}).get("contracts", "—"))
                lc, rc = st.columns([3, 2])
                lc.dataframe(
                    pd.DataFrame(cand["legs"])[
                        ["action", "qty", "right", "strike", "delta", "bid", "ask", "mid"]
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
                rc.markdown(
                    "**Checks:** "
                    + " ".join(f"{'✅' if v else '❌'} `{k}`" for k, v in cand["checks"].items())
                )
                rc.json(cand["exit_plan"], expanded=False)
                st.plotly_chart(
                    payoff_chart(
                        cand["legs"],
                        p["underlying_price"],
                        1,
                        a["breakevens"],
                        "Payoff per contract",
                    ),
                    use_container_width=True,
                    key=f"pay_{sym}_{choice}",
                )
                t1, t2 = st.columns([1, 3])
                n = t1.number_input(
                    "Contracts",
                    min_value=1,
                    value=max(1, cand.get("sizing", {}).get("contracts", 1) or 1),
                    key=f"n_{sym}_{choice}",
                )
                if cand["status"] != "valid":
                    t2.warning(f"This candidate is **{cand['status']}**. Track only if intended.")
                if t1.button("📌 Track position", key=f"trk_{sym}_{choice}"):
                    track(p, cand, int(n), "demo" if demo else "live")
                    st.success(f"Tracking {sym} {cand['strategy']} × {n}. See P&L Monitor.")


# ── P&L Monitor ───────────────────────────────────────────────────────────────


def fetch_marks(open_rows):
    if demo:
        return demo_marks(open_rows, demo_days, demo_move)
    return run_async(mark_positions(open_rows, port=int(port)))


def pnl_monitor():
    rows = [r for r in load_journal() if r["status"] == "open"]
    rows = [r for r in rows if (r.get("mode") == "demo") == demo]
    if not rows:
        st.info(f"No open {'demo' if demo else 'live'} positions. Track one from Proposals.")
        return

    c1, c2 = st.columns([1, 4])
    clicked = c1.button("🔄 Refresh marks", type="primary")
    if clicked or demo or refresh_s or "marks" not in st.session_state:
        st.session_state["marks"] = fetch_marks(rows)
        st.session_state["marked_at"] = now_ny().strftime("%H:%M:%S ET")
    marks = st.session_state["marks"]
    c2.caption(f"Marked: {st.session_state.get('marked_at')}")
    if not marks.get("success"):
        st.error(marks.get("error"))
        return

    today = now_ny().strftime("%Y-%m-%d")
    if demo:
        today = (now_ny() + timedelta(days=demo_days)).strftime("%Y-%m-%d")
    table, hist = [], []
    results = {}
    for r in rows:
        spot = marks["spots"].get(r["symbol"])
        res = position_pnl(r, marks["mids"], spot, today, MULT)
        results[r["id"]] = res
        exp = datetime.strptime(r["expiry"], "%Y%m%d").date()
        table.append(
            {
                "ID": r["id"],
                "Symbol": r["symbol"],
                "Strategy": r["strategy"],
                "Expiry": exp.isoformat(),
                "DTE": (exp - date.fromisoformat(today)).days,
                "Qty": r["contracts"],
                "Spot": round(spot, 2) if spot else None,
                "Entry net": r["analysis"]["net_price"],
                "Now value": res.get("current_value"),
                "Risk $": res.get("risk"),
                "P&L $": res.get("pnl"),
                "P&L % risk": res.get("pct_of_risk"),
                "% max profit": res.get("pct_of_max_profit"),
                "Signals": " | ".join(res["signals"]),
            }
        )
        if not res.get("missing"):
            hist.append(
                {
                    "ts": now_ny().strftime("%Y-%m-%d %H:%M:%S"),
                    "mode": r.get("mode"),
                    "id": r["id"],
                    "label": f"{r['symbol']} {r['strategy']}",
                    "pnl": res["pnl"],
                    "pct_of_risk": res["pct_of_risk"],
                }
            )
    if not demo:
        append_history(hist)

    df = pd.DataFrame(table)
    total_risk = df["Risk $"].sum(skipna=True)
    total_pnl = df["P&L $"].sum(skipna=True)
    k = st.columns(5)
    k[0].metric("Open positions", len(df))
    k[1].metric("Capital at risk", f"${total_risk:,.0f}")
    k[2].metric("Unrealized P&L", money(total_pnl))
    k[3].metric("P&L % of risk", f"{100 * total_pnl / total_risk:.1f}%" if total_risk else "—")
    k[4].metric("Positions with signals", int((df["Signals"] != "").sum()))
    if total_risk and account_value:
        st.caption(f"Risk is {100 * total_risk / account_value:.1f}% of account (course cap: 30%).")

    def color(v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return ""
        return "color: #2ca02c" if v > 0 else "color: #d62728" if v < 0 else ""

    st.dataframe(
        df.style.map(color, subset=["P&L $", "P&L % risk"]).format(
            {
                "P&L $": "{:,.0f}",
                "Risk $": "{:,.0f}",
                "P&L % risk": "{:.1f}%",
                "% max profit": "{:.0f}%",
                "Spot": "{:,.2f}",
            },
            na_rep="—",
        ),
        hide_index=True,
        use_container_width=True,
    )

    ch1, ch2 = st.columns(2)
    bar = go.Figure(
        go.Bar(
            x=[f"{t['Symbol']} {t['Strategy']} ({t['ID']})" for t in table],
            y=[t["P&L % risk"] or 0 for t in table],
            marker_color=["#2ca02c" if (t["P&L % risk"] or 0) >= 0 else "#d62728" for t in table],
        )
    )
    bar.update_layout(
        title="P&L as % of max risk", height=320, margin=dict(t=40, b=10), yaxis_title="% of risk"
    )
    ch1.plotly_chart(bar, use_container_width=True)

    if HISTORY.exists() and not demo:
        h = pd.read_csv(HISTORY)
        h = h[h["id"].isin(df["ID"])]
        if not h.empty:
            tot = h.groupby("ts", as_index=False)["pnl"].sum()
            line = go.Figure(go.Scatter(x=tot["ts"], y=tot["pnl"], mode="lines+markers"))
            line.update_layout(
                title="Unrealized P&L over time ($)", height=320, margin=dict(t=40, b=10)
            )
            ch2.plotly_chart(line, use_container_width=True)
    else:
        ch2.caption("P&L history is recorded on each live refresh.")

    st.subheader("Positions")
    for r in rows:
        res = results[r["id"]]
        tag = "🚨 " if res["signals"] and not res.get("missing") else ""
        pnl_txt = (
            f"{money(res['pnl'])} ({res['pct_of_risk']:.1f}% of risk)"
            if not res.get("missing")
            else "no mark"
        )
        with st.expander(f"{tag}{r['symbol']} {r['strategy']} × {r['contracts']} · {pnl_txt}"):
            for s in res["signals"]:
                (st.error if s.startswith(("STOP", "ALERT")) else st.warning)(s)
            legs = pd.DataFrame(r["legs"])[["action", "qty", "right", "strike", "mid"]]
            legs = legs.rename(columns={"mid": "entry mid"})
            legs["now mid"] = [
                marks["mids"].get(leg_key(r["symbol"], r["expiry"], lg["strike"], lg["right"]))
                for lg in r["legs"]
            ]
            a, b = st.columns([2, 3])
            a.dataframe(legs, hide_index=True, use_container_width=True)
            a.json(r["exit_plan"], expanded=False)
            spot = marks["spots"].get(r["symbol"]) or r["spot_at_entry"]
            b.plotly_chart(
                payoff_chart(r["legs"], spot, r["contracts"], r["analysis"]["breakevens"]),
                use_container_width=True,
                key=f"pp_{r['id']}",
            )
            if a.button("Close at current mark", key=f"close_{r['id']}"):
                close_position(r["id"], res)
                st.rerun()


with tab_pnl:
    if refresh_s:
        st.fragment(run_every=refresh_s)(pnl_monitor)()
    else:
        pnl_monitor()


# ── Closed ────────────────────────────────────────────────────────────────────

with tab_closed:
    closed = [r for r in load_journal() if r["status"] == "closed"]
    if not closed:
        st.info("No closed positions yet.")
    else:
        cdf = pd.DataFrame(
            [
                {
                    "ID": r["id"],
                    "Mode": r.get("mode"),
                    "Symbol": r["symbol"],
                    "Strategy": r["strategy"],
                    "Opened": r["opened_at"],
                    "Closed": r["closed_at"],
                    "Qty": r["contracts"],
                    "Risk $": r["analysis"]["max_loss"] * MULT * r["contracts"],
                    "P&L $": r.get("realized_pnl"),
                    "P&L % risk": r.get("realized_pct_of_risk"),
                }
                for r in closed
            ]
        )
        wins = (cdf["P&L $"] > 0).mean()
        k = st.columns(4)
        k[0].metric("Closed trades", len(cdf))
        k[1].metric("Realized P&L", money(cdf["P&L $"].sum()))
        k[2].metric("Win rate", f"{wins:.0%}")
        k[3].metric("Avg P&L % of risk", f"{cdf['P&L % risk'].mean():.1f}%")
        st.dataframe(cdf, hide_index=True, use_container_width=True)
        cum = cdf.sort_values("Closed").assign(cum=lambda d: d["P&L $"].cumsum())
        fig = go.Figure(go.Scatter(x=cum["Closed"], y=cum["cum"], mode="lines+markers"))
        fig.update_layout(title="Cumulative realized P&L ($)", height=300, margin=dict(t=40))
        st.plotly_chart(fig, use_container_width=True)
