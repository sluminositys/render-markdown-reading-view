from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RENDER_PATH = PROJECT_ROOT / "scripts" / "render.py"
SPEC = importlib.util.spec_from_file_location("reading_view_render", RENDER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load renderer from {RENDER_PATH}")
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


class FormulaRenderingTests(unittest.TestCase):
    def test_mathml_is_static_deterministic_and_source_locked(self) -> None:
        source = (
            "# Formula audit\n\n"
            "Inline $ E = mc^2 $ stays in the sentence.\n\n"
            "$$\n"
            "\\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}\n"
            "$$\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            markdown_path = Path(directory) / "formula.md"
            markdown_path.write_text(source, encoding="utf-8", newline="\n")
            original_bytes = markdown_path.read_bytes()

            output_path, counts = render.render_file(markdown_path)
            first_bytes = output_path.read_bytes()
            _, second_counts = render.render_file(markdown_path)

            self.assertEqual(original_bytes, markdown_path.read_bytes())
            self.assertEqual(first_bytes, output_path.read_bytes())
            self.assertEqual(counts, second_counts)
            self.assertEqual(counts[17], 1)
            self.assertEqual(counts[18], 1)

            html = output_path.read_text(encoding="utf-8")
            self.assertIn('<math xmlns="http://www.w3.org/1998/Math/MathML"', html)
            self.assertIn('<annotation encoding="application/x-tex">', html)
            self.assertNotIn("<script", html.lower())

            tokens = render.build_parser().parse(source)
            _, expected_formulas = render.markdown_audit_payload(tokens)
            _, actual_formulas = render.html_audit_payload(html)
            self.assertEqual(expected_formulas, actual_formulas)
            self.assertEqual(expected_formulas[0], " E = mc^2 ")

    def test_formula_annotation_tampering_fails_audit(self) -> None:
        source = "# Audit\n\nFormula $E = mc^2$.\n"
        parser = render.build_parser()
        tokens = parser.parse(source)
        counts = render.annotate_tokens(tokens)
        body = parser.renderer.render(tokens, parser.options, {})
        html = render.build_document("Audit", "", body)
        self.assertEqual(counts[17], 1)

        tampered = html.replace("E = mc^2</annotation>", "E = mc^3</annotation>", 1)
        with self.assertRaisesRegex(
            render.RenderError, "formula-source equivalence check failed"
        ):
            render.assert_text_equivalent(tokens, tampered)

    def test_invalid_formula_never_replaces_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            markdown_path = Path(directory) / "formula.md"
            markdown_path.write_text(
                "# Formula\n\nValid $x^2$.\n", encoding="utf-8", newline="\n"
            )
            output_path, _ = render.render_file(markdown_path)
            valid_output = output_path.read_bytes()

            invalid_source = "# Formula\n\nInvalid $x_{$.\n"
            markdown_path.write_text(invalid_source, encoding="utf-8", newline="\n")
            with self.assertRaises(render.RenderError):
                render.render_file(markdown_path)

            self.assertEqual(output_path.read_bytes(), valid_output)
            self.assertEqual(markdown_path.read_text(encoding="utf-8"), invalid_source)

    def test_currency_like_text_is_not_inferred_as_math(self) -> None:
        tokens = render.build_parser().parse("价格为 $100，折扣后 $80。")
        child_types = [
            child.type for token in tokens for child in (token.children or [])
        ]
        self.assertNotIn("math_inline", child_types)

    def test_unsafe_mathml_elements_and_attributes_are_rejected(self) -> None:
        unsafe_formulas = (
            r"\text{</math><script>alert(1)</script>}",
            r"\href{javascript:alert(1)}{x}",
            r"\style{background:url(javascript:alert(1))}{x}",
        )
        for formula in unsafe_formulas:
            with self.subTest(formula=formula):
                with self.assertRaisesRegex(render.RenderError, "unsafe|malformed"):
                    render.render_mathml(formula, "inline")

    def test_common_math_structures_pass_safety_allowlist(self) -> None:
        formula = (
            r"\left(\sum_{i=1}^{n} x_i\right) + "
            r"\begin{bmatrix} a & b \\ c & d \end{bmatrix}"
        )
        mathml = render.render_mathml(formula, "block")
        self.assertIn("<mtable>", mathml)
        self.assertIn('stretchy="true"', mathml)
        self.assertNotIn("<script", mathml.lower())

    def test_known_fence_language_gets_static_exact_text_highlighting(self) -> None:
        source = (
            "# Code\n\n"
            "```python\n"
            'def render(value: str = "<script>") -> str:\n'
            "    return value  # unchanged\n"
            "```\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            markdown_path = Path(directory) / "code.md"
            markdown_path.write_text(source, encoding="utf-8", newline="\n")
            output_path, counts = render.render_file(markdown_path)
            html = output_path.read_text(encoding="utf-8")

            self.assertEqual(counts[14], 1)
            self.assertIn('class="code-block code-highlight"', html)
            self.assertIn('class="tok-k"', html)
            self.assertIn('class="tok-s2"', html)
            self.assertNotIn("<script>", html.lower())

            tokens = render.build_parser().parse(source)
            audit = render.parse_html_audit(html)
            self.assertEqual(
                render.markdown_fenced_code_sources(tokens),
                audit.fenced_code_sources,
            )

    def test_unknown_fence_language_stays_plain(self) -> None:
        code_html, highlighted = render.render_fenced_code(
            "a < b\n", "not-a-real-language"
        )
        self.assertFalse(highlighted)
        self.assertEqual(code_html, "a &lt; b\n")

    def test_fenced_code_whitespace_tampering_fails_exact_audit(self) -> None:
        source = "# Code\n\n```python\ndef f():\n    return 1\n```\n"
        parser = render.build_parser()
        tokens = parser.parse(source)
        render.annotate_tokens(tokens)
        body = parser.renderer.render(tokens, parser.options, {})
        html = render.build_document("Code", "", body)
        tampered = html.replace(
            '\n    <span class="tok-k">return</span>',
            '\n  <span class="tok-k">return</span>',
            1,
        )
        self.assertNotEqual(html, tampered)
        with self.assertRaisesRegex(
            render.RenderError, "fenced-code source equivalence check failed"
        ):
            render.assert_text_equivalent(tokens, tampered)


class DocumentSyntaxCompatibilityTests(unittest.TestCase):
    def render_source(
        self, source: str, filename: str = "document.md"
    ) -> tuple[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            markdown_path = Path(directory) / filename
            markdown_path.write_text(source, encoding="utf-8", newline="\n")
            original = markdown_path.read_bytes()
            output_path, counts = render.render_file(markdown_path)
            html = output_path.read_text(encoding="utf-8")
            self.assertEqual(original, markdown_path.read_bytes())
            return html, counts

    def test_front_matter_is_metadata_not_a_false_heading(self) -> None:
        source = "---\ntitle: Demo\ntags: [a, b]\n---\n\n# Body\n"
        html, counts = self.render_source(source)

        self.assertIn('<pre class="front-matter"><code>title: Demo', html)
        self.assertIn('<h1 id="body">Body</h1>', html)
        self.assertNotIn("<h2>title: Demo", html)
        self.assertEqual(counts[19], 1)

    def test_gfm_tasks_strikethrough_autolinks_and_heading_ids(self) -> None:
        source = (
            "## Install Guide\n\n"
            "- [x] shipped\n"
            "- [ ] pending\n"
            "- ordinary sibling\n\n"
            "Keep ~~obsolete~~ notes at https://example.com/docs、**粗体**。\n\n"
            "## Install Guide\n"
        )
        html, counts = self.render_source(source)

        self.assertIn('<h2 id="install-guide">Install Guide</h2>', html)
        self.assertIn('<h2 id="install-guide-1">Install Guide</h2>', html)
        self.assertIn('class="task-checkbox is-checked"', html)
        self.assertIn('class="task-checkbox"', html)
        self.assertNotIn("[x] shipped", html)
        self.assertIn("<s>obsolete</s>", html)
        self.assertIn(
            '<a href="https://example.com/docs">https://example.com/docs</a>',
            html,
        )
        self.assertIn("、<strong>粗体</strong>。", html)
        self.assertEqual(counts[20], 2)
        self.assertEqual(counts[21], 1)
        self.assertEqual(counts[23], 1)
        self.assertEqual(counts[24], 2)

    def test_footnotes_definition_lists_and_bracket_math(self) -> None:
        source = (
            "Term\n: Definition **text**\n\n"
            r"Inline \(x^2\) has a note[^proof]." + "\n\n"
            "\\[\n"
            "y = \\frac{1}{2}\n"
            "\\]\n\n"
            "[^proof]: Preserved source.\n\n"
            "After the definition.\n"
        )
        html, counts = self.render_source(source)

        self.assertIn("<dl>", html)
        self.assertIn("<dt>Term</dt>", html)
        self.assertIn("<dd>Definition <strong>text</strong></dd>", html)
        self.assertIn('data-footnote-index="1"', html)
        self.assertIn("Preserved source.", html)
        self.assertLess(
            html.index("Preserved source."), html.index("After the definition.")
        )
        self.assertIn("<math", html)
        self.assertIn("x^2</annotation>", html)
        self.assertEqual(counts[22], 1)
        self.assertEqual(counts[25], 2)
        self.assertEqual(counts[26], 1)

    def test_inline_and_standalone_images_use_distinct_components(self) -> None:
        source = (
            "Status ![green badge](badge.svg) remains inline.\n\n"
            "![Standalone figure](figure.svg)\n"
        )
        html, counts = self.render_source(source)

        self.assertIn("reading-figure reading-figure-inline", html)
        self.assertIn('<figure class="reading-figure"><img src="figure.svg"', html)
        self.assertEqual(counts[15], 1)
        self.assertEqual(counts[27], 1)

    def test_safe_html_allowlist_and_unsafe_html_escaping(self) -> None:
        source = (
            "<details open>\n"
            "<summary>More</summary>\n\n"
            "Press <kbd>Ctrl</kbd> and mark <mark>this</mark>.<br>Next line.\n\n"
            "</details>\n\n"
            "<script>alert(1)</script>\n\n"
            "<img src=x onerror=alert(2)>\n\n"
            "<!-- internal note -->\n"
        )
        html, counts = self.render_source(source)

        self.assertIn("<details open>", html)
        self.assertIn("<summary>More</summary>", html)
        self.assertIn("<kbd>Ctrl</kbd>", html)
        self.assertIn("<mark>this</mark>", html)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;img src=x onerror=alert(2)&gt;", html)
        self.assertNotIn("internal note", html)
        self.assertGreaterEqual(counts[28], 1)

    def test_mermaid_remains_an_exact_plain_source_block(self) -> None:
        source = "```mermaid\ngraph TD\n  A --> B\n```\n"
        html, counts = self.render_source(source)

        self.assertIn('class="code-block code-plain"', html)
        self.assertIn("graph TD\n  A --&gt; B\n", html)
        self.assertEqual(counts[14], 1)

    def test_partial_status_and_definition_lists_stay_plain(self) -> None:
        sources = (
            "- ✅ explicit state\n- ordinary item\n",
            "- **Owner**: Lin\n- Due Friday\n",
        )
        for index, source in enumerate(sources):
            with self.subTest(index=index):
                html, counts = self.render_source(source, f"mixed-{index}.md")
                self.assertIn('<ul class="plain-list">', html)
                self.assertNotIn('class="status-list"', html)
                self.assertNotIn('class="definition-list"', html)
                self.assertEqual(counts[10], 1)


if __name__ == "__main__":
    unittest.main()
