#!/usr/bin/env python3
# ABOUTME: Converts a markdown file to PDF using mistune (parser) and reportlab (renderer).
# ABOUTME: Discovers a Unicode TTF font at runtime; falls back to Helvetica with ASCII substitution.

# Dependencies: mistune>=3.2, reportlab>=4.0  (pip install mistune reportlab)

import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import mistune
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Unicode TTF font discovery — searched in order, first match wins.
# ---------------------------------------------------------------------------
_FONT_CANDIDATES = [
    # (regular, bold, italic)  — None means reuse regular
    # macOS
    ("/Library/Fonts/Arial Unicode.ttf", None, None),
    (
        "/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial Italic.ttf",
    ),
    (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
    ),
    # Linux
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    ),
    (
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
    ),
    (
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Italic.ttf",
    ),
    # Windows
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf"),
]

# ---------------------------------------------------------------------------
# Substitutions always applied (emoji / symbols absent from most TTF fonts)
# ---------------------------------------------------------------------------
_ALWAYS_SUBS = {
    "\U0001f947": "1st",
    "\U0001f948": "2nd",
    "\U0001f949": "3rd",
    # Color circles → sentinels resolved to colored ■ after XML escaping
    "\U0001f534": "\x03RED\x03",  # 🔴
    "\U0001f7e1": "\x03YEL\x03",  # 🟡
    "\U0001f7e2": "\x03GRN\x03",  # 🟢
    # Trend emoji → sentinels resolved to colored ▲▼ after XML escaping
    "\U0001f4c8": "\x03TUP\x03",  # 📈
    "\U0001f4c9": "\x03TDN\x03",  # 📉
    "➡": "\x03RGT\x03",
    "⚠": "(!)",
    "✅": "OK",
    "❌": "X",
    "↑": "^",
    "↓": "v",
    "→": "->",
    "←": "<-",
    "'": "'",
    """: '"', """: '"',
    "–": "-",
    "—": "--",
    "…": "...",
}

# Substitutions applied only when no Unicode font is available
_LATIN1_SUBS = {
    "✓": "OK",
    "✔": "OK",
    "✗": "X",
    "✘": "X",
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "Γ": "Gamma",
    "δ": "delta",
    "Δ": "Delta",
    "θ": "theta",
    "Θ": "Theta",
    "λ": "lambda",
    "μ": "mu",
    "ν": "nu",
    "ρ": "rho",
    "σ": "sigma",
    "Σ": "Sigma",
    "τ": "tau",
    "φ": "phi",
    "Φ": "Phi",
    "ψ": "psi",
    "ω": "omega",
    "Ω": "Omega",
    "ε": "epsilon",
    "η": "eta",
    "κ": "kappa",
    "χ": "chi",
    "ξ": "xi",
    "π": "pi",
    "≥": ">=",
    "≤": "<=",
    "≠": "!=",
    "≈": "~=",
    "×": "x",
    "÷": "/",
    "±": "+/-",
    "∞": "inf",
    "√": "sqrt",
    "∑": "sum",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "°": "deg",
    "©": "(c)",
    "®": "(R)",
    "™": "(TM)",
    "½": "1/2",
    "¼": "1/4",
    "¾": "3/4",
    "•": "-",
    "·": ".",
}

# ---------------------------------------------------------------------------
# Sentinel bytes for passing structured data through string-concat pipeline
# ---------------------------------------------------------------------------
_CELL_SEP = "\x00C\x00"
_HEAD_ROW = "\x01H\x01"
_BODY_ROW = "\x01R\x01"
_LIST_ITEM = "\x02I\x02"

# ---------------------------------------------------------------------------
# Visual constants
# ---------------------------------------------------------------------------
_NAVY = colors.HexColor("#1a3a5c")
_BODY_PT = 9
_LINE_SPACING = 14


def _setup_font() -> str:
    """Register first available Unicode TTF font. Returns family name or 'Helvetica'.

    reportlab's font registry is process-global. When this script is loaded as
    more than one module instance (e.g. report-stock imports it via sys.path
    while the tests load it via importlib), the base "DocFont" can end up
    registered without its bold/italic family map, which breaks <b>/<i> at build
    time ("Can't map determine family/bold/italic for DocFont"). So register the
    TTFont files only once (re-registering corrupts the map), but always reassert
    the family mapping, which is cheap and idempotent.
    """
    variants = {"DocFont", "DocFont-Bold", "DocFont-Italic", "DocFont-BoldItalic"}
    if not variants <= set(pdfmetrics.getRegisteredFontNames()):
        for regular, bold, italic in _FONT_CANDIDATES:
            if Path(regular).exists():
                try:
                    pdfmetrics.registerFont(TTFont("DocFont", regular))
                    bold_path = bold if (bold and Path(bold).exists()) else regular
                    italic_path = italic if (italic and Path(italic).exists()) else regular
                    pdfmetrics.registerFont(TTFont("DocFont-Bold", bold_path))
                    pdfmetrics.registerFont(TTFont("DocFont-Italic", italic_path))
                    pdfmetrics.registerFont(TTFont("DocFont-BoldItalic", bold_path))
                    break
                except Exception:
                    continue

    if variants <= set(pdfmetrics.getRegisteredFontNames()):
        pdfmetrics.registerFontFamily(
            "DocFont",
            normal="DocFont",
            bold="DocFont-Bold",
            italic="DocFont-Italic",
            boldItalic="DocFont-BoldItalic",
        )
        return "DocFont"
    return "Helvetica"


def _build_styles(font: str) -> dict:
    bold = font + "-Bold" if font != "Helvetica" else "Helvetica-Bold"

    def s(name, fn=None, **kw):
        return ParagraphStyle(name, fontName=fn or font, **kw)

    return {
        "body": s("body", fontSize=_BODY_PT, leading=_LINE_SPACING, spaceAfter=4, spaceBefore=0),
        "h1": s(
            "h1_doc", fn=bold, fontSize=22, leading=28, textColor=_NAVY, spaceBefore=8, spaceAfter=4
        ),
        "h2": s(
            "h2_doc", fn=bold, fontSize=16, leading=20, textColor=_NAVY, spaceBefore=8, spaceAfter=4
        ),
        "h3": s(
            "h3_doc", fn=bold, fontSize=12, leading=16, textColor=_NAVY, spaceBefore=6, spaceAfter=3
        ),
        "code": s(
            "code",
            fn="Courier",
            fontSize=8,
            leading=11,
            backColor=colors.HexColor("#f5f5f5"),
            spaceAfter=6,
        ),
        "quote": s(
            "quote",
            fontSize=_BODY_PT,
            leading=_LINE_SPACING,
            leftIndent=20,
            textColor=colors.HexColor("#444444"),
            spaceAfter=4,
        ),
        "bullet": s(
            "bullet",
            fontSize=_BODY_PT,
            leading=_LINE_SPACING,
            leftIndent=20,
            bulletIndent=10,
            spaceAfter=2,
        ),
        "table_head": s(
            "table_head", fn=bold, fontSize=8, leading=11, alignment=TA_LEFT, textColor=colors.white
        ),
        "table_cell": s("table_cell", fontSize=8, leading=11, alignment=TA_LEFT),
    }


def _sanitize(text: str, unicode_font: bool) -> str:
    """Replace characters unsupported by the chosen font."""
    for ch, rep in _ALWAYS_SUBS.items():
        text = text.replace(ch, rep)
    if unicode_font:
        return text
    for ch, rep in _LATIN1_SUBS.items():
        text = text.replace(ch, rep)
    result = []
    for ch in text:
        if ord(ch) < 256:
            result.append(ch)
        else:
            normalized = unicodedata.normalize("NFKD", ch)
            ascii_part = normalized.encode("ascii", "ignore").decode("ascii")
            result.append(ascii_part if ascii_part else "?")
    return "".join(result)


def _fix_tight_lists(text: str) -> str:
    """Insert blank line before list items that directly follow non-list content."""
    return re.sub(
        r"^((?![ \t]*[-*+] ).+)\n([ \t]*[-*+] )",
        r"\1\n\n\2",
        text,
        flags=re.MULTILINE,
    )


def _escape_xml(text: str) -> str:
    """Escape characters that are special in reportlab XML markup."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Sentinel → ReportLab font markup (applied after XML escaping, so tags are safe)
_MARKUP_SUBS = {
    "\x03RED\x03": '<font color="#cc2200" size="10">■</font>',
    "\x03YEL\x03": '<font color="#cc8800" size="10">■</font>',
    "\x03GRN\x03": '<font color="#228822" size="10">■</font>',
    "\x03TUP\x03": '<font color="#228822">▲</font>',
    "\x03TDN\x03": '<font color="#cc2200">▼</font>',
    "\x03RGT\x03": "&#8594;",  # → as XML entity
}


def _apply_markup_subs(text: str) -> str:
    """Replace sentinels with ReportLab XML font markup."""
    for sentinel, markup in _MARKUP_SUBS.items():
        text = text.replace(sentinel, markup)
    return text


class _Renderer(mistune.HTMLRenderer):
    """mistune renderer that builds a reportlab Platypus story.

    mistune 3.x HTMLRenderer.render_token() unpacks tokens before calling methods:
    - if token has 'raw': calls func(raw_text, **attrs)
    - if token has 'children': calls func(rendered_children, **attrs)
    - otherwise: calls func(**attrs) or func()
    So method signatures mirror HTMLRenderer, not BaseRenderer.
    """

    def __init__(self, styles: dict, unicode_font: bool):
        super().__init__()
        self.styles = styles
        self.unicode_font = unicode_font
        self.story: list = []

    # ------------------------------------------------------------------
    # Inline methods — return XML markup strings for Paragraph
    # ------------------------------------------------------------------

    def text(self, text: str) -> str:
        return _apply_markup_subs(_escape_xml(_sanitize(text, self.unicode_font)))

    def strong(self, text: str) -> str:
        return f"<b>{text}</b>"

    def emphasis(self, text: str) -> str:
        return f"<i>{text}</i>"

    def codespan(self, text: str) -> str:
        safe = _escape_xml(_sanitize(text, self.unicode_font))
        return f'<font face="Courier" size="8">{safe}</font>'

    def linebreak(self) -> str:
        return "<br/>"

    def softbreak(self) -> str:
        return " "

    def link(self, text: str, url: str, title=None) -> str:
        return f"<u>{text}</u>"

    def image(self, text: str, url: str, title=None) -> str:
        return ""

    def inline_html(self, html: str) -> str:
        return ""

    # ------------------------------------------------------------------
    # Block methods — append Flowables to self.story, return ''
    # ------------------------------------------------------------------

    def heading(self, text: str, level: int, **attrs) -> str:
        style = self.styles.get(f"h{level}", self.styles.get("h3", self.styles["body"]))
        self.story.append(Paragraph(text, style))
        return ""

    def paragraph(self, text: str) -> str:
        self.story.append(Paragraph(text, self.styles["body"]))
        return ""

    def thematic_break(self) -> str:
        self.story.append(
            HRFlowable(
                width="100%",
                thickness=0.5,
                color=colors.HexColor("#cccccc"),
                spaceAfter=4,
                spaceBefore=4,
            )
        )
        return ""

    def block_code(self, code: str, info=None) -> str:
        safe = _escape_xml(_sanitize(code, self.unicode_font))
        self.story.append(Preformatted(safe, self.styles["code"]))
        return ""

    def block_quote(self, text: str) -> str:
        self.story.append(Paragraph(text, self.styles["quote"]))
        return ""

    def blank_line(self) -> str:
        return ""

    def block_html(self, html: str) -> str:
        return ""

    def list(self, text: str, ordered: bool, **attrs) -> str:
        items = [item.strip() for item in text.split(_LIST_ITEM) if item.strip()]
        bullet = "•" if self.unicode_font else "-"
        for i, body in enumerate(items, 1):
            marker = f"{i}." if ordered else bullet
            self.story.append(Paragraph(f"{marker}&nbsp;&nbsp;{body}", self.styles["bullet"]))
        return ""

    def list_item(self, text: str) -> str:
        return _LIST_ITEM + text

    # ------------------------------------------------------------------
    # Table — collect cells via sentinels, build Table flowable
    # ------------------------------------------------------------------

    def table_cell(self, text: str, align=None, head=False) -> str:
        marker = "H" if head else "D"
        return _CELL_SEP + text + "|" + marker + _CELL_SEP

    def table_row(self, text: str) -> str:
        return _BODY_ROW + text

    def table_head(self, text: str) -> str:
        return _HEAD_ROW + text

    def table_body(self, text: str) -> str:
        return text

    def table(self, text: str) -> str:
        row_parts = re.split(r"(\x01[HR]\x01)", text)
        # pairs: (marker, content)
        rows = []
        i = 0
        while i < len(row_parts) - 1:
            if row_parts[i] in (_HEAD_ROW, _BODY_ROW):
                rows.append((row_parts[i], row_parts[i + 1]))
                i += 2
            else:
                i += 1

        table_data = []
        is_head_row = []

        for marker, row_str in rows:
            cells_raw = re.split(re.escape(_CELL_SEP), row_str)
            row_cells = []
            for cell in cells_raw:
                if not cell.strip():
                    continue
                parts = cell.rsplit("|", 1)
                if len(parts) == 2:
                    content, flag = parts[0], parts[1].strip()
                    head = flag == "H"
                    style = self.styles["table_head"] if head else self.styles["table_cell"]
                    row_cells.append(Paragraph(content, style))
            if row_cells:
                table_data.append(row_cells)
                is_head_row.append(marker == _HEAD_ROW)

        if not table_data:
            return ""

        col_count = max(len(r) for r in table_data)
        for row in table_data:
            while len(row) < col_count:
                row.append(Paragraph("", self.styles["table_cell"]))

        available_width = LETTER[0] - (2 * inch)
        col_width = available_width / col_count
        t = Table(table_data, colWidths=[col_width] * col_count, repeatRows=1)

        cmd = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for i, is_head in enumerate(is_head_row):
            if is_head:
                cmd.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#1a3a5c")))
                cmd.append(("TEXTCOLOR", (0, i), (-1, i), colors.white))
        t.setStyle(TableStyle(cmd))
        self.story.append(t)
        self.story.append(Spacer(1, 6))
        return ""


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
        raw_md = input_file.read_text(encoding="utf-8")
        raw_md = _fix_tight_lists(raw_md)

        font_family = _setup_font()
        unicode_font = font_family != "Helvetica"
        styles = _build_styles(font_family)

        renderer = _Renderer(styles=styles, unicode_font=unicode_font)
        md = mistune.create_markdown(renderer=renderer, plugins=["table"])
        md(raw_md)

        doc = SimpleDocTemplate(
            out,
            pagesize=LETTER,
            leftMargin=inch,
            rightMargin=inch,
            topMargin=inch,
            bottomMargin=inch,
        )
        doc.build(renderer.story)

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
