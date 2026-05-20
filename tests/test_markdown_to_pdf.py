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
_fix_tight_lists = _mod._fix_tight_lists
_Renderer = _mod._Renderer
_build_styles = _mod._build_styles
_setup_font = _mod._setup_font


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

    def test_convert_with_headings_followed_by_list(self, tmp_path):
        md = tmp_path / "h2_list.md"
        md.write_text("## Section\n\n- item1\n- item2\n")
        result = convert(str(md))
        assert result["success"] is True
        assert Path(result["output"]).exists()

    def test_convert_renders_tight_list_as_list(self, tmp_path):
        md = tmp_path / "tight.md"
        md.write_text("**Strengths:**\n- Strong trend\n- Good fundamentals\n")
        result = convert(str(md))
        assert result["success"] is True
        assert Path(result["output"]).exists()

    def test_convert_with_greek_chars(self, tmp_path):
        md = tmp_path / "greeks.md"
        md.write_text("# Greeks\n\nDelta: δ, Theta: θ, Gamma: γ\n")
        result = convert(str(md))
        assert result["success"] is True
        assert Path(result["output"]).exists()


class TestRenderer:
    def _make_renderer(self):
        font = _setup_font()
        styles = _build_styles(font)
        return _Renderer(styles=styles, unicode_font=(font != "Helvetica"))

    def test_paragraph_added_to_story(self):
        r = self._make_renderer()
        r.paragraph("Hello world")
        assert len(r.story) == 1

    def test_heading_added_to_story(self):
        r = self._make_renderer()
        r.heading("Section title", level=2)
        assert len(r.story) == 1

    def test_thematic_break_added_to_story(self):
        r = self._make_renderer()
        r.thematic_break()
        assert len(r.story) == 1

    def test_list_items_all_added(self):
        r = self._make_renderer()
        item1 = r.list_item("first")
        item2 = r.list_item("second")
        r.list(item1 + item2, ordered=False)
        assert len(r.story) == 2

    def test_ordered_list(self):
        r = self._make_renderer()
        item1 = r.list_item("one")
        item2 = r.list_item("two")
        r.list(item1 + item2, ordered=True)
        assert len(r.story) == 2

    def test_table_adds_flowables(self):
        r = self._make_renderer()
        c1 = r.table_cell("Symbol", head=True)
        c2 = r.table_cell("Price", head=True)
        head = r.table_head(c1 + c2)
        c3 = r.table_cell("AAPL")
        c4 = r.table_cell("200")
        row = r.table_row(c3 + c4)
        body = r.table_body(row)
        r.table(head + body)
        assert len(r.story) >= 1

    def test_strong_returns_bold_markup(self):
        r = self._make_renderer()
        result = r.strong("bold text")
        assert result == "<b>bold text</b>"

    def test_emphasis_returns_italic_markup(self):
        r = self._make_renderer()
        result = r.emphasis("italic text")
        assert result == "<i>italic text</i>"

    def test_text_escapes_xml(self):
        r = self._make_renderer()
        result = r.text("a < b & c > d")
        assert "&lt;" in result
        assert "&amp;" in result
        assert "&gt;" in result


class TestFixTightLists:
    def test_inserts_blank_line_before_list_after_bold_header(self):
        text = "**Strengths:**\n- item1\n- item2"
        result = _fix_tight_lists(text)
        assert result == "**Strengths:**\n\n- item1\n- item2"

    def test_already_separated_list_unchanged(self):
        text = "**Strengths:**\n\n- item1\n- item2"
        assert _fix_tight_lists(text) == text

    def test_list_after_plain_paragraph(self):
        text = "Some text here\n- item"
        result = _fix_tight_lists(text)
        assert result == "Some text here\n\n- item"

    def test_consecutive_list_items_not_affected(self):
        text = "- item1\n- item2\n- item3"
        assert _fix_tight_lists(text) == text

    def test_asterisk_and_plus_list_markers_also_fixed(self):
        text = "Header:\n* item\nHeader2:\n+ item2"
        result = _fix_tight_lists(text)
        assert "Header:\n\n* item" in result
        assert "Header2:\n\n+ item2" in result


class TestSanitize:
    def test_greek_letters_replaced_without_unicode_font(self):
        assert _sanitize("δ theta Δ", unicode_font=False) == "delta theta Delta"

    def test_greek_letters_kept_with_unicode_font(self):
        result = _sanitize("δ Δ", unicode_font=True)
        assert "δ" in result and "Δ" in result

    def test_arrows_always_replaced(self):
        assert _sanitize("→ ←", unicode_font=False) == "-&gt; &lt;-"
        assert _sanitize("→ ←", unicode_font=True) == "-&gt; &lt;-"

    def test_latin1_chars_unchanged(self):
        assert _sanitize("Hello, world! 100%", unicode_font=False) == "Hello, world! 100%"

    def test_unknown_unicode_decomposed_without_font(self):
        result = _sanitize("café", unicode_font=False)
        assert "caf" in result


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
