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

        tampered = html.replace(
            "E = mc^2</annotation>", "E = mc^3</annotation>", 1
        )
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
            markdown_path.write_text(
                invalid_source, encoding="utf-8", newline="\n"
            )
            with self.assertRaises(render.RenderError):
                render.render_file(markdown_path)

            self.assertEqual(output_path.read_bytes(), valid_output)
            self.assertEqual(
                markdown_path.read_text(encoding="utf-8"), invalid_source
            )

    def test_currency_like_text_is_not_inferred_as_math(self) -> None:
        tokens = render.build_parser().parse("价格为 $100，折扣后 $80。")
        child_types = [
            child.type
            for token in tokens
            for child in (token.children or [])
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
                with self.assertRaisesRegex(
                    render.RenderError, "unsafe|malformed"
                ):
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


if __name__ == "__main__":
    unittest.main()
