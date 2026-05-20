#!/usr/bin/env python3
# ABOUTME: Converts a markdown file to PDF using pure-Python markdown and fpdf2.
# ABOUTME: Discovers a Unicode TTF font at runtime; falls back to ASCII substitution.

# Dependencies: markdown>=3.7, fpdf2>=2.8  (pip install markdown fpdf2)

import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import markdown as md_lib
from fpdf import FPDF

# ---------------------------------------------------------------------------
# Unicode TTF font discovery — searched in order, first match wins.
# Each entry is (regular_path, bold_path); bold_path=None → reuse regular.
# ---------------------------------------------------------------------------
_FONT_CANDIDATES = [
    # (regular, bold, italic)  — None means reuse regular
    # macOS
    ("/Library/Fonts/Arial Unicode.ttf", None, None),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf",
     "/Library/Fonts/Arial Italic.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
     "/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
    # Linux
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
     "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
     "/usr/share/fonts/truetype/noto/NotoSans-Italic.ttf"),
    # Windows
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf",
     "C:/Windows/Fonts/ariali.ttf"),
    ("C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrib.ttf",
     "C:/Windows/Fonts/calibrii.ttf"),
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
_BODY_SIZE_PT = 9
_LINE_HEIGHT = 1.5
_PT_TO_MM = 0.352778

_HEADING_SPLIT_RE = re.compile(r"(<h[1-3]>.*?</h[1-3]>)", re.DOTALL)
_HEADING_TAG_RE = re.compile(r"<h([1-3])>(.*?)</h\1>", re.DOTALL)
_HEADING_SIZES = {1: 22, 2: 16, 3: 12}


def _render_html(pdf: FPDF, html: str, font_family: str) -> None:
    """Render HTML, drawing h1-h3 headings manually to prevent font-size bleed.

    fpdf2 changes the active font size when processing heading tags and does not
    fully restore it before rendering subsequent <ul> content, causing list bullets
    to appear on their own line. Splitting at heading boundaries and rendering them
    with pdf.set_font() / multi_cell() — then explicitly resetting to body size —
    eliminates the bleed.
    """
    for part in _HEADING_SPLIT_RE.split(html):
        chunk = part.strip()
        if not chunk:
            continue
        m = _HEADING_TAG_RE.fullmatch(chunk)
        if m:
            level = int(m.group(1))
            text = re.sub(r"<[^>]+>", "", m.group(2))
            size_pt = _HEADING_SIZES[level]
            pdf.ln(3)
            pdf.set_font(font_family, "B", size_pt)
            pdf.set_text_color(*_NAVY)
            pdf.multi_cell(0, size_pt * _PT_TO_MM * _LINE_HEIGHT, text)
            pdf.ln(1)
            pdf.set_font(font_family, "", _BODY_SIZE_PT)
            pdf.set_text_color(0, 0, 0)
        else:
            pdf.write_html(chunk, font_family=font_family, table_line_separators=True)


def _fix_table_alignment(html: str) -> str:
    """Inject align=left into td/th tags; fpdf2 otherwise defaults to CENTER."""
    html = re.sub(r"<td(\b)", r'<td align="left"\1', html)
    html = re.sub(r"<th(\b)", r'<th align="left"\1', html)
    return html


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
    for regular, bold, italic in _FONT_CANDIDATES:
        if Path(regular).exists():
            try:
                pdf.add_font("DocFont", style="", fname=regular)
                bold_path = bold if (bold and Path(bold).exists()) else regular
                italic_path = italic if (italic and Path(italic).exists()) else regular
                pdf.add_font("DocFont", style="B", fname=bold_path)
                pdf.add_font("DocFont", style="I", fname=italic_path)
                pdf.add_font("DocFont", style="BI", fname=bold_path)
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


def _fix_tight_lists(text: str) -> str:
    """Insert blank line before list items that directly follow non-list content.

    The markdown library requires a blank line between a paragraph and a list.
    Without it, `**Header:**\n- item` lands in one <p> tag instead of a <ul>.
    Only inserts when the preceding line is NOT itself a list item.
    """
    return re.sub(
        r"^((?![ \t]*[-*+] ).+)\n([ \t]*[-*+] )",
        r"\1\n\n\2",
        text,
        flags=re.MULTILINE,
    )


def convert(input_path: str, output_path: str | None = None) -> dict:
    input_file = Path(input_path)
    if not input_file.exists():
        return {"success": False, "error": f"File not found: {input_path}"}

    out = output_path or default_output_path(input_path)

    try:
        raw_md = input_file.read_text(encoding="utf-8")
        raw_md = _fix_tight_lists(raw_md)
        body_html = md_lib.markdown(
            raw_md,
            extensions=["tables", "fenced_code"],
        )

        pdf = FPDF()
        pdf.set_margins(20, 20, 20)
        pdf.add_page()

        font_family = _setup_font(pdf) or "helvetica"
        pdf.set_font(font_family, size=_BODY_SIZE_PT)
        has_unicode = font_family != "helvetica"
        body_html = _sanitize(body_html, unicode_font=has_unicode)
        body_html = _fix_table_alignment(body_html)
        body_html = re.sub(r"<p(\b)", rf'<p line-height="{_LINE_HEIGHT}"\1', body_html)

        _render_html(pdf, body_html, font_family)
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
