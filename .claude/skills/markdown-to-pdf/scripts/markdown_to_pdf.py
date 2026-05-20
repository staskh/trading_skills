#!/usr/bin/env python3
# ABOUTME: Converts a markdown file to PDF using pure-Python markdown and fpdf2.
# ABOUTME: Discovers a Unicode TTF font at runtime; falls back to ASCII substitution.

# Dependencies: markdown>=3.7, fpdf2>=2.8  (pip install markdown fpdf2)

import json
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import markdown as md_lib
from fpdf import FPDF, FontFace

# ---------------------------------------------------------------------------
# Unicode TTF font discovery — searched in order, first match wins.
# Each entry is (regular_path, bold_path); bold_path=None → reuse regular.
# ---------------------------------------------------------------------------
_FONT_CANDIDATES = [
    # macOS
    ("/Library/Fonts/Arial Unicode.ttf", None),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    # Linux
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
     "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
    # Windows
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrib.ttf"),
]

# ---------------------------------------------------------------------------
# Substitutions always applied (emoji / symbols absent from most TTF fonts)
# ---------------------------------------------------------------------------
_ALWAYS_SUBS = {
    # Medal / ranking emoji
    "\U0001f947": "1st", "\U0001f948": "2nd", "\U0001f949": "3rd",
    # Status symbols
    "✓": "OK", "✔": "OK",   # ✓ ✔
    "✗": "X",  "✘": "X",    # ✗ ✘
    "⚠": "(!)",                   # ⚠
    "✅": "OK", "❌": "X",    # ✅ ❌
    # Arrows beyond Latin-1
    "↑": "^", "↓": "v",     # ↑ ↓
    "→": "->", "←": "<-",   # → ←
    # Typographic
    "’": "'", "‘": "'",
    "“": '"', "”": '"',
    "–": "-", "—": "--",
    "…": "...",
}

# Substitutions applied only when no Unicode font is available
_LATIN1_SUBS = {
    # Greek — options greeks and stats
    "α": "alpha",  "β": "beta",   "γ": "gamma",  "Γ": "Gamma",
    "δ": "delta",  "Δ": "Delta",  "θ": "theta",  "Θ": "Theta",
    "λ": "lambda", "μ": "mu",     "ν": "nu",     "ρ": "rho",
    "σ": "sigma",  "Σ": "Sigma",  "τ": "tau",    "φ": "phi",
    "Φ": "Phi",    "ψ": "psi",    "ω": "omega",  "Ω": "Omega",
    "ε": "epsilon","η": "eta",    "κ": "kappa",  "χ": "chi",
    "ξ": "xi",     "π": "pi",
    # Math / comparison
    "≥": ">=", "≤": "<=", "≠": "!=", "≈": "~=",
    "×": "x",  "÷": "/",  "±": "+/-","∞": "inf",
    "√": "sqrt","∑": "sum",
    # Currency
    "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR",
    # Misc
    "°": "deg", "©": "(c)", "®": "(R)", "™": "(TM)",
    "½": "1/2", "¼": "1/4", "¾": "3/4",
    "•": "-", "·": ".",
}

# ---------------------------------------------------------------------------
# PDF visual style
# ---------------------------------------------------------------------------
_NAVY = (26, 58, 92)
_WHITE = (255, 255, 255)

_TAG_STYLES = {
    "h1": FontFace(size_pt=18, color=_NAVY, emphasis="BOLD"),
    "h2": FontFace(size_pt=14, color=_NAVY, emphasis="BOLD"),
    "h3": FontFace(size_pt=11, color=_NAVY, emphasis="BOLD"),
}


def default_output_path(input_path: str) -> str:
    return str(Path(input_path).with_suffix(".pdf"))


def _generated_at() -> str:
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M ET")


def _setup_font(pdf: FPDF) -> str | None:
    """Register first available Unicode TTF font. Returns family name or None."""
    for regular, bold in _FONT_CANDIDATES:
        if Path(regular).exists():
            try:
                pdf.add_font("DocFont", style="", fname=regular)
                bold_path = bold if (bold and Path(bold).exists()) else regular
                pdf.add_font("DocFont", style="B", fname=bold_path)
                return "DocFont"
            except Exception:
                continue
    return None


def _sanitize(html: str, unicode_font: bool) -> str:
    """Replace characters unsupported by the chosen font."""
    for ch, rep in _ALWAYS_SUBS.items():
        html = html.replace(ch, rep)

    if unicode_font:
        return html

    for ch, rep in _LATIN1_SUBS.items():
        html = html.replace(ch, rep)

    # Remaining non-Latin-1: NFKD decompose → keep ASCII part, else "?"
    result = []
    for ch in html:
        if ord(ch) < 256:
            result.append(ch)
        else:
            normalized = unicodedata.normalize("NFKD", ch)
            ascii_part = normalized.encode("ascii", "ignore").decode("ascii")
            result.append(ascii_part if ascii_part else "?")
    return "".join(result)


def convert(input_path: str, output_path: str | None = None) -> dict:
    input_file = Path(input_path)
    if not input_file.exists():
        return {"success": False, "error": f"File not found: {input_path}"}

    out = output_path or default_output_path(input_path)

    try:
        body_html = md_lib.markdown(
            input_file.read_text(encoding="utf-8"),
            extensions=["tables", "fenced_code"],
        )

        pdf = FPDF()
        pdf.set_margins(20, 20, 20)
        pdf.add_page()

        font_family = _setup_font(pdf)
        has_unicode = font_family is not None
        body_html = _sanitize(body_html, unicode_font=has_unicode)

        pdf.write_html(
            body_html,
            table_line_separators=True,
            tag_styles=_TAG_STYLES,
            font_family=font_family or "helvetica",
        )
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
