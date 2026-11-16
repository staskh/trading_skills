#!/usr/bin/env python3
# ABOUTME: CLI wrapper that converts a markdown file to PDF via trading_skills.markdown_pdf.
# ABOUTME: Prints the conversion result as JSON and exits non-zero on failure.

import json
import sys

from trading_skills.markdown_pdf import convert


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
