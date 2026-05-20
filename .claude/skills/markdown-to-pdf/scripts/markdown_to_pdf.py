#!/usr/bin/env python3
# ABOUTME: Converts a markdown file to PDF using pure-Python markdown and fpdf2.
# ABOUTME: No system dependencies required; all logic is self-contained.

# Dependencies: markdown>=3.7, fpdf2>=2.8  (pip install markdown fpdf2)

import json
import sys
from datetime import datetime
from pathlib import Path

import markdown as md_lib
from fpdf import FPDF

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
        html = f"<html><head>{_CSS}</head><body>{html}</body></html>"

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
