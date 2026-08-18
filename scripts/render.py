#!/usr/bin/env python3
"""Render immutable Markdown as a polished, self-contained HTML reading view."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Sequence
from xml.etree import ElementTree

from latex2mathml.converter import convert as latex_to_mathml
from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound


SKILL_ROOT = Path(__file__).resolve().parent.parent
THEME_PATH = SKILL_ROOT / "assets" / "theme.css"

ADMONITION_RE = re.compile(
    r"^\[!(CAUTION|WARNING|NOTE|IMPORTANT|TIP)\](?:\n|$)"
)
DEFINITION_ITEM_RE = re.compile(r"^\*\*(?=\S)([^*\n]+?)\*\*[:：][ \t]?\S")
FILE_SUFFIX_RE = re.compile(r"\.([A-Za-z0-9]+)$")
WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)
MATH_ANNOTATION_ENCODING = "application/x-tex"
MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"
MATH_TOKEN_TYPES = {"math_inline", "math_inline_double", "math_block"}
CODE_FORMATTER = HtmlFormatter(nowrap=True, classprefix="tok-")
ALLOWED_MATHML_ELEMENTS = {
    "maligngroup",
    "malignmark",
    "menclose",
    "merror",
    "mfenced",
    "mfrac",
    "mi",
    "mlabeledtr",
    "mlongdiv",
    "mmultiscripts",
    "mn",
    "mo",
    "mover",
    "mpadded",
    "mphantom",
    "mprescripts",
    "mroot",
    "mrow",
    "ms",
    "mscarries",
    "mscarry",
    "msgroup",
    "msline",
    "mspace",
    "msqrt",
    "msrow",
    "mstack",
    "mstyle",
    "msub",
    "msubsup",
    "msup",
    "mtable",
    "mtd",
    "mtext",
    "mtr",
    "munder",
    "munderover",
    "none",
}
ALLOWED_MATHML_ATTRIBUTES = {
    "accent",
    "accentunder",
    "align",
    "bevelled",
    "border-color",
    "charalign",
    "close",
    "columnalign",
    "columnlines",
    "columnspacing",
    "columnspan",
    "columnwidth",
    "depth",
    "dir",
    "display",
    "displaystyle",
    "edge",
    "equalcolumns",
    "equalrows",
    "fence",
    "form",
    "frame",
    "framespacing",
    "height",
    "indentalign",
    "indentalignfirst",
    "indentalignlast",
    "indentshift",
    "indentshiftfirst",
    "indentshiftlast",
    "indenttarget",
    "infixlinebreakstyle",
    "largeop",
    "length",
    "linebreak",
    "linebreakmultchar",
    "linebreakstyle",
    "lineleading",
    "linethickness",
    "location",
    "longdivstyle",
    "lspace",
    "mathbackground",
    "mathcolor",
    "mathsize",
    "mathvariant",
    "maxsize",
    "minlabelspacing",
    "minsize",
    "movablelimits",
    "notation",
    "numalign",
    "open",
    "position",
    "rowalign",
    "rowlines",
    "rowspacing",
    "rowspan",
    "rspace",
    "scriptlevel",
    "scriptminsize",
    "scriptsizemultiplier",
    "selection",
    "separator",
    "separators",
    "shift",
    "side",
    "stackalign",
    "stretchy",
    "subscriptshift",
    "superscriptshift",
    "symmetric",
    "voffset",
    "width",
}

ElementTree.register_namespace("", MATHML_NAMESPACE)

STATUS_GLYPHS = ("✅", "⚠️", "🔴", "❌")
KNOWN_EXTENSIONS = {
    "py",
    "js",
    "ts",
    "md",
    "go",
    "rs",
    "java",
    "sh",
    "json",
    "yaml",
    "css",
    "html",
}

CURRENCY_SYMBOLS = r"\$€£¥￥₩₹"
CURRENCY_CODES = r"USD|CNY|RMB|EUR|GBP|JPY|KRW|INR"
NUMBER_CORE = r"[+-]?(?:\d+(?:[,_ ]\d{3})*(?:\.\d+)?|\.\d+)"
NUMERIC_CELL_RE = re.compile(
    rf"^(?:[{CURRENCY_SYMBOLS}]\s*|(?:{CURRENCY_CODES})\s+)?"
    rf"{NUMBER_CORE}"
    rf"(?:\s*(?:%|％|[{CURRENCY_SYMBOLS}]|{CURRENCY_CODES}))?$"
)

RULE_NAMES = {
    1: "h1",
    2: "lede",
    3: "section-heading",
    4: "caution",
    5: "note",
    6: "tip",
    7: "quiet-quote",
    8: "status-list",
    9: "definition-list",
    10: "plain-list",
    11: "file-chip",
    12: "inline-code",
    13: "table",
    14: "code-fence",
    15: "figure",
    16: "base-style",
    17: "inline-math",
    18: "display-math",
}


class RenderError(RuntimeError):
    """A safe rendering failure that must not produce a new HTML file."""


def math_placeholder(index: int) -> str:
    """Return an audit-only marker that fixes a formula's document position."""
    return f"\ue000formula:{index}\ue001"


def xml_name(value: str) -> tuple[str | None, str]:
    """Split an ElementTree expanded name into namespace and local name."""
    if value.startswith("{") and "}" in value:
        namespace, local_name = value[1:].split("}", 1)
        return namespace, local_name
    return None, value


def validate_mathml(root: ElementTree.Element, display: str) -> None:
    """Reject converter output outside a static presentation-only subset."""
    root_namespace, root_name = xml_name(root.tag)
    if root_namespace != MATHML_NAMESPACE or root_name != "math":
        raise RenderError("math converter returned a non-MathML root")
    if root.attrib.get("display") != display:
        raise RenderError("math converter returned an unexpected display mode")

    for element in root.iter():
        namespace, local_name = xml_name(element.tag)
        if element is not root and (
            namespace != MATHML_NAMESPACE
            or local_name not in ALLOWED_MATHML_ELEMENTS
        ):
            raise RenderError(
                f"math converter returned unsafe element: {local_name}"
            )
        for attribute_name in element.attrib:
            attribute_namespace, attribute_local_name = xml_name(attribute_name)
            if (
                attribute_namespace is not None
                or attribute_local_name not in ALLOWED_MATHML_ATTRIBUTES
            ):
                raise RenderError(
                    "math converter returned unsafe attribute: "
                    f"{attribute_local_name}"
                )


class VisibleTextParser(HTMLParser):
    """Collect visible prose and exact TeX annotations from the document body."""

    IGNORED_ELEMENTS = {"head", "script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.formula_sources: list[str] = []
        self.fenced_code_sources: list[str] = []
        self._ignored_depth = 0
        self._math_depth = 0
        self._annotation_depth = 0
        self._annotation_parts: list[str] = []
        self._formula_index = 0
        self._code_capture = False
        self._code_parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in self.IGNORED_ELEMENTS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "math":
            if not self._math_depth:
                self.parts.append(math_placeholder(self._formula_index))
                self._formula_index += 1
            self._math_depth += 1
            return
        if tag == "pre":
            classes = (dict(attrs).get("class") or "").split()
            if "code-block" in classes:
                self._code_capture = True
                self._code_parts = []
        if tag == "annotation" and self._math_depth:
            attributes = dict(attrs)
            if attributes.get("encoding") == MATH_ANNOTATION_ENCODING:
                self._annotation_depth += 1
                if self._annotation_depth == 1:
                    self._annotation_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in self.IGNORED_ELEMENTS and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == "annotation" and self._annotation_depth:
            self._annotation_depth -= 1
            if not self._annotation_depth:
                self.formula_sources.append("".join(self._annotation_parts))
                self._annotation_parts = []
            return
        if tag == "pre" and self._code_capture:
            self.fenced_code_sources.append("".join(self._code_parts))
            self._code_capture = False
            self._code_parts = []
        if tag == "math" and self._math_depth:
            self._math_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._code_capture:
            self._code_parts.append(data)
        if self._annotation_depth:
            self._annotation_parts.append(data)
        elif not self._math_depth:
            self.parts.append(data)

    @property
    def text(self) -> str:
        return "".join(self.parts)


def render_mathml(source: str, display: str) -> str:
    """Compile TeX to MathML and embed the exact token source for auditing."""
    visual_source = source.strip()
    if not visual_source:
        raise RenderError("formula source is empty")
    try:
        mathml = latex_to_mathml(visual_source, display=display)
    except Exception as error:
        preview = normalize_whitespace(source)[:80]
        raise RenderError(
            f"invalid {display} formula {preview!r}: "
            f"{type(error).__name__}: {error}"
        ) from error

    try:
        root = ElementTree.fromstring(mathml)
    except ElementTree.ParseError as error:
        raise RenderError(
            "math converter returned unsafe or malformed MathML"
        ) from error
    validate_mathml(root, display)

    semantics = ElementTree.Element(f"{{{MATHML_NAMESPACE}}}semantics")
    for child in list(root):
        root.remove(child)
        semantics.append(child)
    annotation = ElementTree.SubElement(
        semantics,
        f"{{{MATHML_NAMESPACE}}}annotation",
        {"encoding": MATH_ANNOTATION_ENCODING},
    )
    annotation.text = source
    root.append(semantics)
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)


def render_fenced_code(source: str, info: str) -> tuple[str, bool]:
    """Return exact-text code HTML and whether a known lexer was applied."""
    language = info.strip().split(maxsplit=1)[0].lower() if info.strip() else ""
    if not language:
        return escapeHtml(source), False
    try:
        lexer = get_lexer_by_name(
            language,
            stripnl=False,
            stripall=False,
            ensurenl=False,
            tabsize=0,
        )
    except ClassNotFound:
        return escapeHtml(source), False
    try:
        return highlight(source, lexer, CODE_FORMATTER), True
    except Exception as error:
        raise RenderError(
            f"syntax highlighting failed for language {language!r}: "
            f"{type(error).__name__}: {error}"
        ) from error


class ReadingViewRenderer(RendererHTML):
    """HTML renderer for the syntax-only reading-view mappings."""

    def code_inline(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options, env
        token = tokens[idx]
        value = escapeHtml(token.content)
        if token.meta.get("file_chip"):
            extension = token.meta["file_extension"]
            return (
                f'<code class="file-chip file-ext-{extension}">{value}</code>'
            )
        return f'<code class="inline-code">{value}</code>'

    def fence(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options, env
        token = tokens[idx]
        code_html, highlighted = render_fenced_code(token.content, token.info)
        style_class = "code-highlight" if highlighted else "code-plain"
        return (
            f'<pre class="code-block {style_class}"><code>'
            f"{code_html}</code></pre>\n"
        )

    def math_inline(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options, env
        mathml = render_mathml(tokens[idx].content, "inline")
        return f'<span class="math-inline">{mathml}</span>'

    def math_block(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options, env
        mathml = render_mathml(tokens[idx].content, "block")
        return f'<div class="math-block">\n{mathml}\n</div>\n'

    def image(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        token = tokens[idx]
        alt = self.renderInlineAsText(token.children, options, env)
        token.attrSet("alt", alt)
        token.attrJoin("class", "reading-image")
        image_html = f"<img{self.renderAttrs(token)}>"
        caption = (
            f"<figcaption>{escapeHtml(alt)}</figcaption>" if alt else ""
        )
        return f'<figure class="reading-figure">{image_html}{caption}</figure>'

    def table_open(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options, env
        return (
            '<div class="table-wrap">\n'
            f"<table{self.renderAttrs(tokens[idx])}>\n"
        )

    def table_close(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del tokens, idx, options, env
        return "</table>\n</div>\n"


def build_parser() -> MarkdownIt:
    """Create the one parser configuration used for rendering and auditing."""
    parser = MarkdownIt(
        "commonmark",
        {
            "breaks": False,
            "html": False,
            "linkify": False,
            "typographer": False,
        },
        renderer_cls=ReadingViewRenderer,
    ).enable("table")
    parser.use(
        dollarmath_plugin,
        allow_labels=False,
        allow_space=True,
        allow_digits=False,
        allow_blank_lines=False,
        double_inline=False,
    )
    parser.add_render_rule("math_inline", ReadingViewRenderer.math_inline)
    parser.add_render_rule("math_block", ReadingViewRenderer.math_block)
    return parser


def inline_plain_text(children: Sequence[Token] | None) -> str:
    """Extract author text from inline tokens without Markdown syntax."""
    parts: list[str] = []
    for token in children or []:
        if token.type in {"text", "code_inline", "html_inline"}:
            parts.append(token.content)
        elif token.type == "image":
            parts.append(inline_plain_text(token.children))
        elif token.type in MATH_TOKEN_TYPES:
            parts.append(token.content)
        elif token.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
    return "".join(parts)


def inline_audit_text(
    children: Sequence[Token] | None, formula_sources: list[str]
) -> str:
    """Extract prose while replacing formulas with positional audit markers."""
    parts: list[str] = []
    for token in children or []:
        if token.type in {"text", "code_inline", "html_inline"}:
            parts.append(token.content)
        elif token.type == "image":
            parts.append(inline_audit_text(token.children, formula_sources))
        elif token.type in MATH_TOKEN_TYPES:
            formula_index = len(formula_sources)
            formula_sources.append(token.content)
            parts.append(math_placeholder(formula_index))
        elif token.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
    return "".join(parts)


def markdown_audit_payload(tokens: Sequence[Token]) -> tuple[str, list[str]]:
    """Extract positioned prose and exact TeX sources from parsed Markdown."""
    parts: list[str] = []
    formula_sources: list[str] = []
    for token in tokens:
        if token.type == "inline":
            value = inline_audit_text(token.children, formula_sources)
            if value:
                parts.append(value)
        elif token.type in {"math_block", "math_block_label"}:
            formula_index = len(formula_sources)
            formula_sources.append(token.content)
            parts.append(math_placeholder(formula_index))
        elif token.type in {"fence", "code_block", "html_block"}:
            if token.content:
                parts.append(token.content)
    return "\n".join(parts), formula_sources


def markdown_fenced_code_sources(tokens: Sequence[Token]) -> list[str]:
    """Extract exact fenced-code sources in document order."""
    return [token.content for token in tokens if token.type == "fence"]


def normalize_whitespace(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip()


def parse_html_audit(html: str) -> VisibleTextParser:
    parser = VisibleTextParser()
    parser.feed(html)
    parser.close()
    return parser


def html_audit_payload(html: str) -> tuple[str, list[str]]:
    parser = parse_html_audit(html)
    return parser.text, parser.formula_sources


def text_diff(expected: str, actual: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            [expected + "\n"],
            [actual + "\n"],
            fromfile="markdown-visible-text",
            tofile="html-visible-text",
        )
    )


def formula_diff(expected: Sequence[str], actual: Sequence[str]) -> str:
    expected_lines = [f"{index}: {value!r}\n" for index, value in enumerate(expected)]
    actual_lines = [f"{index}: {value!r}\n" for index, value in enumerate(actual)]
    return "".join(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="markdown-formula-sources",
            tofile="html-mathml-annotations",
        )
    )


def code_diff(expected: Sequence[str], actual: Sequence[str]) -> str:
    expected_lines = [f"{index}: {value!r}\n" for index, value in enumerate(expected)]
    actual_lines = [f"{index}: {value!r}\n" for index, value in enumerate(actual)]
    return "".join(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="markdown-fenced-code-sources",
            tofile="html-fenced-code-text",
        )
    )


def find_matching_close(tokens: Sequence[Token], start: int) -> int:
    opening = tokens[start]
    if not opening.type.endswith("_open"):
        raise RenderError(f"internal error: {opening.type} is not an opening token")
    closing_type = opening.type.removesuffix("_open") + "_close"
    depth = 0
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token.type == opening.type:
            depth += 1
        elif token.type == closing_type:
            depth -= 1
            if depth == 0:
                return index
    raise RenderError(f"internal error: no closing token for {opening.type}")


def first_direct_inline(
    tokens: Sequence[Token], item_start: int, item_end: int
) -> Token | None:
    target_level = tokens[item_start].level + 2
    for token in tokens[item_start + 1 : item_end]:
        if token.type == "inline" and token.level == target_level:
            return token
    return None


def strip_admonition_marker(
    tokens: Sequence[Token], inline_index: int, marker: str
) -> None:
    inline = tokens[inline_index]
    inline.content = ADMONITION_RE.sub("", inline.content, count=1)
    children = list(inline.children or [])
    if children and children[0].type == "text":
        if children[0].content == marker:
            children.pop(0)
        elif children[0].content.startswith(marker):
            children[0].content = children[0].content[len(marker) :]
    if children and children[0].type in {"softbreak", "hardbreak"}:
        children.pop(0)
    inline.children = children

    if children:
        return
    if inline_index and tokens[inline_index - 1].type == "paragraph_open":
        tokens[inline_index - 1].hidden = True
    if (
        inline_index + 1 < len(tokens)
        and tokens[inline_index + 1].type == "paragraph_close"
    ):
        tokens[inline_index + 1].hidden = True


def annotate_headings(tokens: Sequence[Token], counts: Counter[int]) -> None:
    waiting_for_lede = False
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            if token.tag == "h1":
                counts[1] += 1
                if token.level == 0:
                    waiting_for_lede = True
            else:
                counts[3] += 1
                if token.tag in {"h4", "h5", "h6"}:
                    token.attrJoin("class", "heading-depth-3")
            continue

        if not waiting_for_lede:
            continue
        if token.type == "paragraph_open" and token.level == 0:
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            if inline and inline.type == "inline":
                has_image = any(
                    child.type == "image" for child in (inline.children or [])
                )
                if not has_image:
                    token.attrJoin("class", "lede")
                    counts[2] += 1
                    waiting_for_lede = False


def annotate_blockquotes(tokens: Sequence[Token], counts: Counter[int]) -> None:
    style_for_marker = {
        "CAUTION": ("caution", 4),
        "WARNING": ("caution", 4),
        "NOTE": ("note", 5),
        "IMPORTANT": ("note", 5),
        "TIP": ("tip", 6),
    }
    for index, token in enumerate(tokens):
        if token.type != "blockquote_open":
            continue
        end = find_matching_close(tokens, index)
        direct_inline_index = next(
            (
                child_index
                for child_index in range(index + 1, end)
                if tokens[child_index].type == "inline"
                and tokens[child_index].level == token.level + 2
            ),
            None,
        )
        match = (
            ADMONITION_RE.match(tokens[direct_inline_index].content)
            if direct_inline_index is not None
            else None
        )
        if not match:
            token.attrJoin("class", "quiet-quote")
            counts[7] += 1
            continue

        label = match.group(1)
        style, rule_number = style_for_marker[label]
        token.attrJoin("class", f"admonition admonition-{style}")
        token.attrSet("data-label", label)
        token.attrSet("aria-label", label)
        counts[rule_number] += 1
        strip_admonition_marker(
            tokens, direct_inline_index, f"[!{label}]"
        )


def annotate_lists(tokens: Sequence[Token], counts: Counter[int]) -> None:
    list_open_types = {"bullet_list_open", "ordered_list_open"}
    for index, token in enumerate(tokens):
        if token.type not in list_open_types:
            continue
        end = find_matching_close(tokens, index)
        item_indices = [
            item_index
            for item_index in range(index + 1, end)
            if tokens[item_index].type == "list_item_open"
            and tokens[item_index].level == token.level + 1
        ]
        first_lines: list[str] = []
        for item_index in item_indices:
            item_end = find_matching_close(tokens, item_index)
            inline = first_direct_inline(tokens, item_index, item_end)
            first_lines.append(inline.content if inline else "")

        if first_lines and all(
            line.startswith(STATUS_GLYPHS) for line in first_lines
        ):
            token.attrJoin("class", "status-list")
            counts[8] += 1
        elif first_lines and all(
            DEFINITION_ITEM_RE.match(line) for line in first_lines
        ):
            token.attrJoin("class", "definition-list")
            counts[9] += 1
        else:
            token.attrJoin("class", "plain-list")
            counts[10] += 1


def is_numeric_cell(value: str) -> bool:
    candidate = normalize_whitespace(value)
    if len(candidate) > 2 and candidate.startswith("(") and candidate.endswith(")"):
        candidate = candidate[1:-1].strip()
    return bool(NUMERIC_CELL_RE.fullmatch(candidate))


def annotate_tables(tokens: Sequence[Token], counts: Counter[int]) -> None:
    for index, token in enumerate(tokens):
        if token.type != "table_open":
            continue
        counts[13] += 1
        end = find_matching_close(tokens, index)
        in_body = False
        row_count = 0
        current_column = 0
        values_by_column: dict[int, list[str]] = {}
        cells_by_column: dict[int, list[Token]] = {}

        for cell_index in range(index + 1, end):
            cell = tokens[cell_index]
            if cell.type == "tbody_open":
                in_body = True
            elif cell.type == "tbody_close":
                in_body = False
            elif in_body and cell.type == "tr_open":
                row_count += 1
                current_column = 0
            elif in_body and cell.type == "td_open":
                inline = next(
                    (
                        candidate
                        for candidate in tokens[cell_index + 1 : end]
                        if candidate.type == "inline"
                        and candidate.level == cell.level + 1
                    ),
                    None,
                )
                value = inline_plain_text(inline.children) if inline else ""
                values_by_column.setdefault(current_column, []).append(value)
                cells_by_column.setdefault(current_column, []).append(cell)
                current_column += 1

        numeric_columns = {
            column
            for column, values in values_by_column.items()
            if len(values) == row_count and values and all(map(is_numeric_cell, values))
        }
        for column in numeric_columns:
            for cell in cells_by_column[column]:
                cell.attrJoin("class", "numeric-column")


def annotate_inline_rules(tokens: Sequence[Token], counts: Counter[int]) -> None:
    for index, token in enumerate(tokens):
        if token.type == "fence":
            counts[14] += 1
        elif token.type == "hr":
            counts[16] += 1
        elif token.type in {"math_block", "math_block_label"}:
            counts[18] += 1
        if token.type != "inline":
            continue

        has_image = False
        for child in token.children or []:
            if child.type == "code_inline":
                suffix = FILE_SUFFIX_RE.search(child.content)
                known_suffix = (
                    suffix.group(1).lower()
                    if suffix and suffix.group(1).lower() in KNOWN_EXTENSIONS
                    else None
                )
                if "/" in child.content or known_suffix:
                    child.meta["file_chip"] = True
                    child.meta["file_extension"] = known_suffix or "unknown"
                    counts[11] += 1
                else:
                    counts[12] += 1
            elif child.type == "image":
                has_image = True
                counts[15] += 1
            elif child.type in {"math_inline", "math_inline_double"}:
                counts[17] += 1
            elif child.type in {"link_open", "strong_open", "em_open"}:
                counts[16] += 1

        if has_image and index and tokens[index - 1].type == "paragraph_open":
            paragraph_open = tokens[index - 1]
            paragraph_open.tag = "div"
            paragraph_open.attrJoin("class", "image-paragraph")
            if (
                index + 1 < len(tokens)
                and tokens[index + 1].type == "paragraph_close"
            ):
                tokens[index + 1].tag = "div"


def annotate_tokens(tokens: Sequence[Token]) -> Counter[int]:
    counts: Counter[int] = Counter()
    annotate_headings(tokens, counts)
    annotate_blockquotes(tokens, counts)
    annotate_lists(tokens, counts)
    annotate_tables(tokens, counts)
    annotate_inline_rules(tokens, counts)
    return counts


def document_title(tokens: Sequence[Token], fallback: str) -> str:
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h1":
            if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
                title = inline_plain_text(tokens[index + 1].children).strip()
                if title:
                    return title
    return fallback


def build_document(title: str, css: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="und">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{escapeHtml(title)}</title>\n"
        "  <style>\n"
        f"{css.rstrip()}\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        '<main class="reading-view">\n'
        f"{body.rstrip()}\n"
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )


def assert_text_equivalent(tokens: Sequence[Token], html: str) -> None:
    expected_text, expected_formulas = markdown_audit_payload(tokens)
    expected_code = markdown_fenced_code_sources(tokens)
    html_audit = parse_html_audit(html)
    actual_text = html_audit.text
    actual_formulas = html_audit.formula_sources
    actual_code = html_audit.fenced_code_sources
    expected_text = normalize_whitespace(expected_text)
    actual_text = normalize_whitespace(actual_text)
    if expected_text != actual_text:
        raise RenderError(
            "visible-text and formula-position equivalence check failed\n"
            + text_diff(expected_text, actual_text)
        )
    if expected_formulas != actual_formulas:
        raise RenderError(
            "formula-source equivalence check failed\n"
            + formula_diff(expected_formulas, actual_formulas)
        )
    if expected_code != actual_code:
        raise RenderError(
            "fenced-code source equivalence check failed\n"
            + code_diff(expected_code, actual_code)
        )


def source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_source_unchanged(path: Path, expected_digest: str) -> None:
    if source_digest(path) != expected_digest:
        raise RenderError(f"source Markdown changed during rendering: {path}")


def render_file(input_path: Path) -> tuple[Path, Counter[int]]:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise RenderError(f"Markdown file not found: {input_path}")
    if input_path.suffix.lower() != ".md":
        raise RenderError("input must be a .md file")
    if not THEME_PATH.is_file():
        raise RenderError(f"theme not found: {THEME_PATH}")

    source_bytes = input_path.read_bytes()
    original_digest = hashlib.sha256(source_bytes).hexdigest()
    try:
        source = source_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RenderError(f"Markdown must be UTF-8: {error}") from error

    css = THEME_PATH.read_text(encoding="utf-8")
    parser = build_parser()
    environment: dict[str, Any] = {}
    tokens = parser.parse(source, environment)
    counts = annotate_tokens(tokens)
    body = parser.renderer.render(tokens, parser.options, environment)
    title = document_title(tokens, input_path.stem)
    html = build_document(title, css, body)

    assert_text_equivalent(tokens, html)
    assert_source_unchanged(input_path, original_digest)

    output_path = input_path.with_suffix(".html")
    if output_path.resolve() == input_path:
        raise RenderError("refusing to overwrite source Markdown")
    output_path.write_text(html, encoding="utf-8", newline="\n")
    assert_source_unchanged(input_path, original_digest)
    return output_path, counts


def format_report(counts: Counter[int]) -> str:
    triggered = ", ".join(
        f"{number}:{RULE_NAMES[number]}={counts[number]}"
        for number in sorted(RULE_NAMES)
        if counts[number]
    )
    return triggered or "none"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render immutable Markdown as a self-contained HTML reading view."
        )
    )
    parser.add_argument("input", type=Path, help="UTF-8 .md file to render")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output_path, counts = render_file(args.input)
    except (OSError, RenderError) as error:
        print(f"render failed: {error}", file=sys.stderr)
        return 1
    print(f"rendered {output_path} | rules: {format_report(counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
