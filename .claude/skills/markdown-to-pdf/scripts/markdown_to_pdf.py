#!/usr/bin/env python3
# ABOUTME: Converts a markdown file to PDF using pure-Python markdown and fpdf2.
# ABOUTME: No system dependencies required; all logic is self-contained.

# Dependencies: markdown>=3.7, fpdf2>=2.8  (pip install markdown fpdf2)

import json
import sys
from datetime import datetime
from pathlib import Path

import unicodedata

import markdown as md_lib
from fpdf import FPDF

# ASCII substitutions for characters outside Latin-1 (Helvetica's range).
# Covers Greeks (options greeks), arrows, math operators, and typography.
_UNICODE_SUBS = {
    # Greek — options greeks and stats
    "α": "alpha", "β": "beta", "γ": "gamma", "Γ": "Gamma",
    "δ": "delta", "Δ": "Delta", "θ": "theta", "Θ": "Theta",
    "λ": "lambda", "μ": "mu", "ν": "nu", "ρ": "rho",
    "σ": "sigma", "Σ": "Sigma", "τ": "tau", "φ": "phi", "Φ": "Phi",
    "ψ": "psi", "ω": "omega", "Ω": "Omega", "ε": "epsilon", "η": "eta",
    "κ": "kappa", "χ": "chi", "ξ": "xi", "π": "pi",
    # Arrows
    "→": "->", "←": "<-", "↑": "^", "↓": "v",
    "⇒": "=>", "⇐": "<=", "⟶": "->", "⟵": "<-",
    # Math / comparison
    "≥": ">=", "≤": "<=", "≠": "!=", "≈": "~=",
    "×": "x", "÷": "/", "±": "+/-", "∞": "inf",
    "√": "sqrt", "∑": "sum", "∏": "prod",
    # Typographic
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "--", "…": "...",
    # Currency
    "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR",
    # Misc
    "•": "-", "·": ".", "°": "deg", "©": "(c)", "®": "(R)", "™": "(TM)",
    "½": "1/2", "¼": "1/4", "¾": "3/4",
}


def _sanitize(text: str) -> str:
    """Replace non-Latin-1 chars with ASCII equivalents; drop anything remaining."""
    result = []
    for ch in text:
        if ord(ch) < 256:
            result.append(ch)
        elif ch in _UNICODE_SUBS:
            result.append(_UNICODE_SUBS[ch])
        else:
            # Try NFKD decomposition, keep only ASCII part
            normalized = unicodedata.normalize("NFKD", ch)
            ascii_part = normalized.encode("ascii", "ignore").decode("ascii")
            result.append(ascii_part if ascii_part else "?")
    return "".join(result)


_CSS = """
<style>
  body { font-family: Helvetica; font-size: 11pt; color: #222; }
  h1 { font-size: 20pt; color: #1a3a5c; margin-bottom: 6pt; }
  h2 { font-size: 15pt; color: #1a3a5c; margin-bottom: 4pt; }
  h3 { font-size: 12pt; color: #1a3a5c; }
  table { border: 1px solid #aaa; border-collapse: collapse; width: 100%; }
  th { background-color: #1a3a5c; color: #fff; padding: 4pt; }
  td { border: 1px solid #ccc; padding: 4pt; }
</style>
"""


def default_output_path(input_path: str) -> str:
    return str(Path(input_path).with_suffix(".pdf"))


def _generated_at() -> str:
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M ET")


def convert(input_path: str, output_path: str | None = None) -> dict:
    input_file = Path(input_path)
    if not input_file.exists():
        return {"success": False, "error": f"File not found: {input_path}"}

    out = output_path or default_output_path(input_path)

    try:
        html = md_lib.markdown(
            input_file.read_text(encoding="utf-8"),
            extensions=["tables", "fenced_code"],
        )
        html = _sanitize(f"<html><head>{_CSS}</head><body>{html}</body></html>")

        pdf = FPDF()
        pdf.set_margins(20, 20, 20)
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        pdf.write_html(html)
        pdf.output(out)
    except Exception as exc:
        return {"success": False, "error": str(exc), "input": input_path, "output": out}

    return {
        "success": True,
        "input": str(input_file.resolve()),
        "output": str(Path(out).resolve()),
        "generated_at": _generated_at(),
        "data_delay": "real-time",
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: markdown_to_pdf.py <input.md> [output.pdf]"}))
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    result = convert(input_path, output_path)
    print(json.dumps(result, indent=2))

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
