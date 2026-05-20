# ABOUTME: Tests for the markdown-to-PDF skill script.
# ABOUTME: Loads the script directly; no src module dependency.

import importlib.util
import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / ".claude/skills/markdown-to-pdf/scripts/markdown_to_pdf.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("markdown_to_pdf", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_script()
convert = _mod.convert
default_output_path = _mod.default_output_path
_sanitize = _mod._sanitize
_fix_table_alignment = _mod._fix_table_alignment


class TestDefaultOutputPath:
    def test_replaces_md_extension(self, tmp_path):
        md = tmp_path / "report.md"
        assert default_output_path(str(md)) == str(tmp_path / "report.pdf")

    def test_nested_path(self, tmp_path):
        md = tmp_path / "sub" / "analysis.md"
        assert default_output_path(str(md)) == str(tmp_path / "sub" / "analysis.pdf")

    def test_no_extension(self, tmp_path):
        md = tmp_path / "report"
        assert default_output_path(str(md)) == str(tmp_path / "report.pdf")


class TestConvert:
    def test_missing_input_returns_error(self, tmp_path):
        result = convert(str(tmp_path / "nonexistent.md"))
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_success_creates_pdf(self, tmp_path):
        md = tmp_path / "report.md"
        md.write_text("# Hello\n\nWorld paragraph.")
        result = convert(str(md))
        assert result["success"] is True
        assert Path(result["output"]).exists()
        assert result["output"] == str(tmp_path / "report.pdf")

    def test_default_output_path_used(self, tmp_path):
        md = tmp_path / "report.md"
        md.write_text("# Test")
        result = convert(str(md))
        assert result["output"] == str(tmp_path / "report.pdf")
        assert result["input"] == str(md.resolve())

    def test_custom_output_path(self, tmp_path):
        md = tmp_path / "report.md"
        md.write_text("# Test")
        custom = str(tmp_path / "custom.pdf")
        result = convert(str(md), custom)
        assert result["success"] is True
        assert result["output"] == custom
        assert Path(custom).exists()

    def test_result_has_metadata(self, tmp_path):
        md = tmp_path / "report.md"
        md.write_text("# Test")
        result = convert(str(md))
        assert "generated_at" in result
        assert result["data_delay"] == "real-time"

    def test_markdown_table_renders(self, tmp_path):
        md = tmp_path / "table.md"
        md.write_text("# Report\n\n| Symbol | Price |\n|--------|-------|\n| AAPL   | 200   |\n")
        result = convert(str(md))
        assert result["success"] is True
        assert Path(result["output"]).exists()


class TestFixTableAlignment:
    def test_td_gets_left_align(self):
        assert '<td align="left">' in _fix_table_alignment("<td>text</td>")

    def test_th_gets_left_align(self):
        assert '<th align="left">' in _fix_table_alignment("<th>header</th>")

    def test_existing_td_attrs_preserved(self):
        result = _fix_table_alignment('<td colspan="2">text</td>')
        assert 'align="left"' in result
        assert 'colspan="2"' in result

    def test_non_table_tags_unchanged(self):
        assert _fix_table_alignment("<p>hello</p>") == "<p>hello</p>"


class TestSanitize:
    def test_greek_letters_replaced_without_unicode_font(self):
        assert _sanitize("δ theta Δ", unicode_font=False) == "delta theta Delta"

    def test_greek_letters_kept_with_unicode_font(self):
        result = _sanitize("δ Δ", unicode_font=True)
        assert "δ" in result and "Δ" in result

    def test_arrows_always_replaced(self):
        # Arrows are in _ALWAYS_SUBS, substituted regardless of font
        assert _sanitize("→ ←", unicode_font=False) == "-> <-"
        assert _sanitize("→ ←", unicode_font=True) == "-> <-"

    def test_latin1_chars_unchanged(self):
        assert _sanitize("Hello, world! 100%", unicode_font=False) == "Hello, world! 100%"

    def test_unknown_unicode_decomposed_without_font(self):
        result = _sanitize("café", unicode_font=False)
        assert "caf" in result  # 'é' decomposes to 'e' via NFKD

    def test_convert_with_greek_chars(self, tmp_path):
        md = tmp_path / "greeks.md"
        md.write_text("# Greeks\n\nDelta: δ, Theta: θ, Gamma: γ\n")
        result = convert(str(md))
        assert result["success"] is True
        assert Path(result["output"]).exists()


class TestCLI:
    def test_missing_args_exits_nonzero(self):
        result = subprocess.run(
            ["python", str(SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "error" in json.loads(result.stdout)

    def test_converts_file(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("# Test\n\nContent paragraph.")
        result = subprocess.run(
            ["uv", "run", "python", str(SCRIPT), str(md)],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        output = json.loads(result.stdout)
        assert output["success"] is True
        assert Path(output["output"]).exists()
