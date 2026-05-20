---
name: markdown-to-pdf
description: Convert a markdown file to PDF using pandoc. Use when the user wants to convert a .md file to PDF, or when another skill needs to produce a PDF from markdown output.
user_invocable: true
arguments:
  - name: file
    description: Path to the input markdown file
    required: true
  - name: output
    description: Output PDF path. Defaults to same directory and basename as the input file.
    required: false
dependencies: ["trading-skills"]
---

# Markdown to PDF Converter

Converts a markdown file to a professionally formatted PDF. Pure Python — no system tools required.

## Dependencies

Requires two Python packages (already in `pyproject.toml`):

```
markdown>=3.7
fpdf2>=2.8
```

Install with: `uv sync` (or `pip install markdown fpdf2`)

## Instructions

```bash
uv run python scripts/markdown_to_pdf.py <input.md> [output.pdf]
```

- `input.md` — path to the markdown file (required)
- `output.pdf` — output path (optional; defaults to same directory and basename as input)

## Output

The script returns JSON with:
- `success` — `true` or `false`
- `input` — resolved absolute path of the input file
- `output` — resolved absolute path of the generated PDF
- `error` — error message if `success` is `false`
- `generated_at` — NY timezone timestamp
- `data_delay` — always `"real-time"`

After conversion, tell the user the output PDF path.

## Examples

```bash
# Convert sandbox/report.md → sandbox/report.pdf (default output)
uv run python scripts/markdown_to_pdf.py sandbox/report.md

# Explicit output path
uv run python scripts/markdown_to_pdf.py sandbox/report.md sandbox/AAPL_Report_2026-05-20_1430.pdf
```

## Supported Markdown

- Headings (H1–H3)
- Paragraphs, bold, italic
- Tables (pipe syntax)
- Fenced code blocks
- Unordered and ordered lists
