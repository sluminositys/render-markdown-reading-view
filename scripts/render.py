#!/usr/bin/env python3
"""Render immutable Markdown as a polished, self-contained HTML reading view."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Sequence
from xml.etree import ElementTree

from latex2mathml.converter import convert as latex_to_mathml
from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.renderer import RendererHTML
from markdown_it.rules_core import StateCore
from markdown_it.token import Token
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.texmath import texmath_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound


SKILL_ROOT = Path(__file__).resolve().parent.parent
THEME_PATH = SKILL_ROOT / "assets" / "theme.css"
RENDERER_VERSION = "1.0.0"
RENDERER_CLI_CONTRACT_VERSION = "1"
HEAD_INJECTION_MARKER = "<head>\n"

ADMONITION_RE = re.compile(r"^\[!(CAUTION|WARNING|NOTE|IMPORTANT|TIP)\](?:\n|$)")
DEFINITION_ITEM_RE = re.compile(r"^\*\*(?=\S)([^*\n]+?)\*\*[:：][ \t]?\S")
TASK_ITEM_RE = re.compile(r"^\[([ xX])\](?:[ \t]+|$)")
BARE_URL_RE = re.compile(
    r"https?://[^\s<>\"'`*、，。；：！？）】》」』]+",
    re.IGNORECASE,
)
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

SAFE_HTML_PAIRED_TAGS = {"details", "kbd", "mark", "sub", "summary", "sup"}
SAFE_HTML_VOID_TAGS = {"br"}

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
    19: "front-matter",
    20: "task-item",
    21: "strikethrough",
    22: "footnote",
    23: "auto-link",
    24: "heading-anchor",
    25: "bracket-math",
    26: "term-definition",
    27: "inline-image",
    28: "safe-html",
}

SOURCE_MAP_BLOCK_TAGS: dict[str, str | None] = {
    "front_matter": "pre",
    "heading_open": None,
    "paragraph_open": None,
    "blockquote_open": "blockquote",
    "bullet_list_open": "ul",
    "ordered_list_open": "ol",
    "table_open": "table",
    "dl_open": "dl",
    "fence": "pre",
    "code_block": "pre",
    "math_block": "div",
    "footnote_reference_open": "aside",
}


class RenderError(RuntimeError):
    """A safe rendering failure that must not produce a new HTML file."""


class RenderResult:
    """Committed renderer output and its deterministic machine report."""

    __slots__ = ("output_path", "counts", "report", "report_json")

    def __init__(
        self,
        output_path: Path,
        counts: Counter[int],
        report: dict[str, Any],
        report_json: str,
    ) -> None:
        self.output_path = output_path
        self.counts = counts
        self.report = report
        self.report_json = report_json


class SafeHtmlSanitizer(HTMLParser):
    """Render a tiny HTML allowlist and visibly escape everything else."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.syntax_count = 0

    def _original_start_tag(self, tag: str) -> str:
        return self.get_starttag_text() or f"<{tag}>"

    @staticmethod
    def _details_attributes_are_safe(
        attrs: list[tuple[str, str | None]],
    ) -> bool:
        return not attrs or (
            len(attrs) == 1
            and attrs[0][0].lower() == "open"
            and attrs[0][1] in {None, "", "open"}
        )

    def _safe_start_tag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        self_closing: bool,
    ) -> str | None:
        tag = tag.lower()
        if tag in SAFE_HTML_VOID_TAGS and not attrs:
            return "<br>"
        if self_closing or tag not in SAFE_HTML_PAIRED_TAGS:
            return None
        if tag == "details":
            if not self._details_attributes_are_safe(attrs):
                return None
            return "<details open>" if attrs else "<details>"
        if attrs:
            return None
        return f"<{tag}>"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        rendered = self._safe_start_tag(tag, attrs, self_closing=False)
        if rendered is None:
            self.parts.append(escapeHtml(self._original_start_tag(tag)))
            return
        self.syntax_count += 1
        self.parts.append(rendered)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        rendered = self._safe_start_tag(tag, attrs, self_closing=True)
        if rendered is None:
            self.parts.append(escapeHtml(self._original_start_tag(tag)))
            return
        self.syntax_count += 1
        self.parts.append(rendered)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SAFE_HTML_PAIRED_TAGS:
            self.syntax_count += 1
            self.parts.append(f"</{tag}>")
        else:
            self.parts.append(escapeHtml(f"</{tag}>"))

    def handle_data(self, data: str) -> None:
        self.parts.append(escapeHtml(data))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        del data
        self.syntax_count += 1

    def handle_decl(self, decl: str) -> None:
        self.parts.append(escapeHtml(f"<!{decl}>"))

    def handle_pi(self, data: str) -> None:
        self.parts.append(escapeHtml(f"<?{data}>"))

    def unknown_decl(self, data: str) -> None:
        self.parts.append(escapeHtml(f"<![{data}]>"))

    @property
    def html(self) -> str:
        return "".join(self.parts)


def sanitize_html(source: str) -> tuple[str, int]:
    """Return safe deterministic HTML and the consumed syntax-token count."""
    sanitizer = SafeHtmlSanitizer()
    sanitizer.feed(source)
    sanitizer.close()
    return sanitizer.html, sanitizer.syntax_count


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
            namespace != MATHML_NAMESPACE or local_name not in ALLOWED_MATHML_ELEMENTS
        ):
            raise RenderError(f"math converter returned unsafe element: {local_name}")
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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
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


def add_token_class(token: Token, class_name: str) -> None:
    """Add one CSS class to a token without duplicating existing classes."""
    classes = (token.attrGet("class") or "").split()
    if class_name not in classes:
        classes.append(class_name)
        token.attrSet("class", " ".join(classes))


class ReadingViewRenderer(RendererHTML):
    """HTML renderer for the syntax-only reading-view mappings."""

    def front_matter(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options, env
        token = tokens[idx]
        add_token_class(token, "front-matter")
        content = escapeHtml(token.content)
        return f"<pre{self.renderAttrs(token)}><code>{content}</code></pre>\n"

    def task_checkbox(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options, env
        checked = bool(tokens[idx].meta.get("checked"))
        state_class = " is-checked" if checked else ""
        aria_checked = "true" if checked else "false"
        return (
            f'<span class="task-checkbox{state_class}" role="checkbox" '
            f'aria-checked="{aria_checked}" aria-disabled="true"></span>'
        )

    def html_inline(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options, env
        rendered, _ = sanitize_html(tokens[idx].content)
        return rendered

    def html_block(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options, env
        rendered, safe_count = sanitize_html(tokens[idx].content)
        if not rendered.strip():
            return ""
        if safe_count:
            return rendered
        return f'<div class="html-block">{rendered.rstrip()}</div>\n'

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
            return f'<code class="file-chip file-ext-{extension}">{value}</code>'
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
        add_token_class(token, "code-block")
        add_token_class(token, style_class)
        return (
            f"<pre{self.renderAttrs(token)}><code>"
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
        token = tokens[idx]
        add_token_class(token, "math-block")
        mathml = render_mathml(token.content, "block")
        return f"<div{self.renderAttrs(token)}>\n{mathml}\n</div>\n"

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
        image_mode = token.meta.get("image_mode", "block")
        figure_class = "reading-figure"
        image_class = "reading-image"
        if image_mode == "inline":
            figure_class += " reading-figure-inline"
            image_class += " reading-image-inline"
        token.attrJoin("class", image_class)
        image_html = f"<img{self.renderAttrs(token)}>"
        caption = f"<figcaption>{escapeHtml(alt)}</figcaption>" if alt else ""
        return f'<figure class="{figure_class}">{image_html}{caption}</figure>'

    def footnote_ref(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options
        token = tokens[idx]
        number = str(token.meta["id"] + 1)
        prefix = f'-{env["docId"]}-' if isinstance(env.get("docId"), str) else ""
        anchor_name = prefix + number
        sub_id = int(token.meta.get("subId", 0))
        reference_id = anchor_name + (f":{sub_id}" if sub_id else "")
        caption = number + (f":{sub_id}" if sub_id else "")
        return (
            '<sup class="footnote-ref">'
            f'<a href="#fn{anchor_name}" id="fnref{reference_id}" '
            f'data-footnote-index="{caption}" aria-label="Footnote {caption}"></a>'
            "</sup>"
        )

    def footnote_reference_open(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options
        token = tokens[idx]
        label = str(token.meta["label"])
        footnotes = env.get("footnotes", {})
        reference_id = footnotes.get("refs", {}).get(f":{label}", -1)
        if isinstance(reference_id, int) and reference_id >= 0:
            number = str(reference_id + 1)
            identifier = number
        else:
            number = label
            identifier = f"label-{heading_slug(label)}"
        prefix = f'-{env["docId"]}-' if isinstance(env.get("docId"), str) else ""
        anchor_name = prefix + identifier
        token.attrSet("id", f"fn{anchor_name}")
        add_token_class(token, "footnote-definition")
        token.attrSet("data-footnote-index", number)
        return f"<aside{self.renderAttrs(token)}>"

    def footnote_reference_close(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del tokens, idx, options, env
        return "</aside>\n"

    def table_open(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del options, env
        return '<div class="table-wrap">\n' f"<table{self.renderAttrs(tokens[idx])}>\n"

    def table_close(
        self,
        tokens: Sequence[Token],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        del tokens, idx, options, env
        return "</table>\n</div>\n"


def bare_url_tokens(text: str, parser: MarkdownIt) -> list[Token]:
    """Split plain text into exact-text tokens and conservative HTTP links."""
    output: list[Token] = []
    cursor = 0
    for match in BARE_URL_RE.finditer(text):
        raw_match = match.group(0)
        url = raw_match.rstrip(".,;:!?)]}")
        if not url or url in {"http://", "https://"}:
            continue
        start = match.start()
        end = start + len(url)
        if start > cursor:
            plain = Token("text", "", 0)
            plain.content = text[cursor:start]
            output.append(plain)

        opening = Token("link_open", "a", 1)
        opening.attrSet("href", parser.normalizeLink(url))
        opening.markup = "bare-url"
        opening.info = "auto"
        output.append(opening)

        label = Token("text", "", 0)
        label.content = url
        output.append(label)

        closing = Token("link_close", "a", -1)
        closing.markup = "bare-url"
        closing.info = "auto"
        output.append(closing)
        cursor = end

    if cursor < len(text):
        plain = Token("text", "", 0)
        plain.content = text[cursor:]
        output.append(plain)
    return output or [Token("text", "", 0)]


def bare_url_core_rule(state: StateCore) -> None:
    """Link explicit HTTP(S) URLs after Markdown inline syntax is resolved."""
    for block_token in state.tokens:
        if block_token.type != "inline" or not block_token.children:
            continue
        children: list[Token] = []
        link_depth = 0
        for child in block_token.children:
            if child.type == "link_open":
                link_depth += 1
                children.append(child)
            elif child.type == "link_close":
                children.append(child)
                link_depth = max(0, link_depth - 1)
            elif child.type == "text" and link_depth == 0:
                children.extend(bare_url_tokens(child.content, state.md))
            else:
                children.append(child)
        block_token.children = children


def build_parser() -> MarkdownIt:
    """Create the one parser configuration used for rendering and auditing."""
    parser = MarkdownIt(
        "commonmark",
        {
            "breaks": False,
            "html": True,
            "linkify": False,
            "typographer": False,
        },
        renderer_cls=ReadingViewRenderer,
    ).enable(["table", "strikethrough"])
    parser.use(front_matter_plugin)
    parser.use(deflist_plugin)
    parser.use(footnote_plugin, inline=False, move_to_end=False)
    parser.use(
        dollarmath_plugin,
        allow_labels=False,
        allow_space=True,
        allow_digits=False,
        allow_blank_lines=False,
        double_inline=False,
    )
    parser.use(texmath_plugin, delimiters="brackets")
    parser.block.ruler.disable("math_block_eqno")
    parser.core.ruler.after("inline", "bare_url", bare_url_core_rule)
    parser.add_render_rule("front_matter", ReadingViewRenderer.front_matter)
    parser.add_render_rule("task_checkbox", ReadingViewRenderer.task_checkbox)
    parser.add_render_rule("html_inline", ReadingViewRenderer.html_inline)
    parser.add_render_rule("html_block", ReadingViewRenderer.html_block)
    parser.add_render_rule("math_inline", ReadingViewRenderer.math_inline)
    parser.add_render_rule("math_block", ReadingViewRenderer.math_block)
    parser.add_render_rule("footnote_ref", ReadingViewRenderer.footnote_ref)
    parser.add_render_rule(
        "footnote_reference_open", ReadingViewRenderer.footnote_reference_open
    )
    parser.add_render_rule(
        "footnote_reference_close", ReadingViewRenderer.footnote_reference_close
    )
    return parser


def inline_plain_text(children: Sequence[Token] | None) -> str:
    """Extract author text from inline tokens without Markdown syntax."""
    parts: list[str] = []
    for token in children or []:
        if token.type in {"text", "code_inline"}:
            parts.append(token.content)
        elif token.type == "html_inline":
            parts.append(sanitized_html_visible_text(token.content))
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
        if token.type in {"text", "code_inline"}:
            parts.append(token.content)
        elif token.type == "html_inline":
            parts.append(sanitized_html_visible_text(token.content))
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
        elif token.type == "front_matter":
            if token.content:
                parts.append(token.content)
        elif token.type == "html_block":
            value = sanitized_html_visible_text(token.content)
            if value:
                parts.append(value)
        elif token.type in {"fence", "code_block"}:
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


def sanitized_html_visible_text(source: str) -> str:
    """Return the visible text produced by the safe raw-HTML projection."""
    rendered, _ = sanitize_html(source)
    return parse_html_audit(rendered).text


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


def heading_slug(value: str) -> str:
    """Create a stable Unicode heading id without changing visible text."""
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    characters: list[str] = []
    for character in normalized:
        category = unicodedata.category(character)
        if character.isspace() or character == "-":
            characters.append("-")
        elif (
            character == "_"
            or category[0] in {"L", "N"}
            or category
            in {
                "Mc",
                "Mn",
            }
        ):
            characters.append(character)
    return re.sub(r"-+", "-", "".join(characters)).strip("-") or "section"


def annotate_headings(tokens: Sequence[Token], counts: Counter[int]) -> None:
    waiting_for_lede = False
    slug_counts: Counter[str] = Counter()
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            heading_text = (
                inline_plain_text(inline.children)
                if inline is not None and inline.type == "inline"
                else ""
            )
            base_slug = heading_slug(heading_text)
            duplicate_index = slug_counts[base_slug]
            slug_counts[base_slug] += 1
            slug = (
                base_slug if duplicate_index == 0 else f"{base_slug}-{duplicate_index}"
            )
            token.attrSet("id", slug)
            counts[24] += 1
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
        strip_admonition_marker(tokens, direct_inline_index, f"[!{label}]")


def annotate_task_item(item: Token, inline: Token) -> bool:
    """Consume an explicit GFM task marker and attach static checkbox chrome."""
    match = TASK_ITEM_RE.match(inline.content)
    children = list(inline.children or [])
    if not match or not children or children[0].type != "text":
        return False
    child_match = TASK_ITEM_RE.match(children[0].content)
    if not child_match:
        return False

    checked = match.group(1).lower() == "x"
    inline.content = inline.content[match.end() :]
    children[0].content = children[0].content[child_match.end() :]
    checkbox = Token("task_checkbox", "span", 0)
    checkbox.meta = {"checked": checked}
    children.insert(0, checkbox)
    inline.children = children
    item.attrJoin("class", "task-list-item")
    return True


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
        task_count = 0
        for item_index in item_indices:
            item_end = find_matching_close(tokens, item_index)
            inline = first_direct_inline(tokens, item_index, item_end)
            if inline and annotate_task_item(tokens[item_index], inline):
                task_count += 1
            first_lines.append(inline.content if inline else "")

        if task_count:
            token.attrJoin("class", "task-list")
            counts[20] += task_count
        elif first_lines and all(
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


def image_is_standalone(children: Sequence[Token], image_index: int) -> bool:
    """Return true only for a paragraph containing one optional linked image."""
    meaningful = [
        (index, child)
        for index, child in enumerate(children)
        if not (
            child.type in {"softbreak", "hardbreak"}
            or (child.type == "text" and not child.content.strip())
        )
    ]
    if len(meaningful) == 1:
        return meaningful[0][0] == image_index and meaningful[0][1].type == "image"
    return (
        len(meaningful) == 3
        and [child.type for _, child in meaningful]
        == ["link_open", "image", "link_close"]
        and meaningful[1][0] == image_index
    )


def annotate_inline_rules(tokens: Sequence[Token], counts: Counter[int]) -> None:
    for index, token in enumerate(tokens):
        if token.type == "front_matter":
            counts[19] += 1
        elif token.type == "dl_open":
            counts[26] += 1
        elif token.type == "html_block":
            _, safe_count = sanitize_html(token.content)
            counts[28] += safe_count
        elif token.type == "fence":
            counts[14] += 1
        elif token.type == "hr":
            counts[16] += 1
        elif token.type in {"math_block", "math_block_label"}:
            counts[25 if token.markup == r"\[" else 18] += 1
        if token.type != "inline":
            continue

        has_image = False
        children = list(token.children or [])
        for child_index, child in enumerate(children):
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
                if image_is_standalone(children, child_index):
                    child.meta["image_mode"] = "block"
                    counts[15] += 1
                else:
                    child.meta["image_mode"] = "inline"
                    counts[27] += 1
            elif child.type in {"math_inline", "math_inline_double"}:
                counts[25 if child.markup == r"\(" else 17] += 1
            elif child.type == "link_open":
                counts[23 if child.markup == "bare-url" else 16] += 1
            elif child.type in {"strong_open", "em_open"}:
                counts[16] += 1
            elif child.type == "s_open":
                counts[21] += 1
            elif child.type == "footnote_ref":
                counts[22] += 1
            elif child.type == "html_inline":
                _, safe_count = sanitize_html(child.content)
                counts[28] += safe_count

        if has_image and index and tokens[index - 1].type == "paragraph_open":
            paragraph_open = tokens[index - 1]
            paragraph_open.tag = "div"
            paragraph_open.attrJoin("class", "image-paragraph")
            if index + 1 < len(tokens) and tokens[index + 1].type == "paragraph_close":
                tokens[index + 1].tag = "div"


def annotate_tokens(tokens: Sequence[Token]) -> Counter[int]:
    counts: Counter[int] = Counter()
    annotate_headings(tokens, counts)
    annotate_blockquotes(tokens, counts)
    annotate_lists(tokens, counts)
    annotate_tables(tokens, counts)
    annotate_inline_rules(tokens, counts)
    return counts


def annotate_source_map(tokens: Sequence[Token]) -> list[dict[str, Any]]:
    """Attach deterministic ids to non-overlapping top-level author blocks."""
    blocks: list[dict[str, Any]] = []
    for token in tokens:
        if token.level != 0 or token.type not in SOURCE_MAP_BLOCK_TAGS:
            continue
        configured_tag = SOURCE_MAP_BLOCK_TAGS[token.type]
        tag = configured_tag if configured_tag is not None else token.tag
        if not tag:
            continue

        block_id = f"b{len(blocks) + 1:06d}"
        token.attrSet("data-al-block", block_id)
        record: dict[str, Any] = {"id": block_id, "tag": tag}
        if (
            token.map is not None
            and len(token.map) == 2
            and all(isinstance(line, int) for line in token.map)
            and 0 <= token.map[0] <= token.map[1]
        ):
            source_start = token.map[0] + 1
            source_end = token.map[1] + 1
            token.attrSet("data-source-lines", f"{source_start}:{source_end}")
            record["sourceStartLine"] = source_start
            record["sourceEndLineExclusive"] = source_end
        blocks.append(record)
    return blocks


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
        f"{HEAD_INJECTION_MARKER}"
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


def resolve_input_path(input_path: Path) -> Path:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise RenderError(f"Markdown file not found: {input_path}")
    if input_path.suffix.lower() != ".md":
        raise RenderError("input must be a .md file")
    return input_path


def resolve_write_target(
    candidate: Path,
    *,
    label: str,
    input_path: Path,
    other_target: Path | None = None,
) -> Path:
    target = candidate.expanduser().resolve()
    if target == input_path:
        raise RenderError(f"refusing to overwrite source Markdown with {label}")
    if other_target is not None and target == other_target:
        raise RenderError(f"{label} must not use the HTML output path")
    if not target.parent.is_dir():
        raise RenderError(f"{label} parent directory does not exist: {target.parent}")
    if target.exists() and not target.is_file():
        raise RenderError(f"{label} target is not a file: {target}")
    return target


def write_temporary_payload(target: Path, payload: bytes) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{target.name}.tmp-", dir=target.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def restore_target(target: Path, previous_payload: bytes | None) -> None:
    if previous_payload is None:
        target.unlink(missing_ok=True)
        return
    temporary_path = write_temporary_payload(target, previous_payload)
    try:
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def commit_payloads(
    payloads: Sequence[tuple[Path, bytes]],
    *,
    input_path: Path,
    source_sha256: str,
) -> None:
    previous = {
        target: target.read_bytes() if target.exists() else None
        for target, _ in payloads
    }
    temporary: list[tuple[Path, Path]] = []
    try:
        for target, payload in payloads:
            temporary.append((target, write_temporary_payload(target, payload)))
    except BaseException:
        for _, temporary_path in temporary:
            temporary_path.unlink(missing_ok=True)
        raise
    committed: list[Path] = []
    try:
        assert_source_unchanged(input_path, source_sha256)
        for target, temporary_path in temporary:
            os.replace(temporary_path, target)
            committed.append(target)
        assert_source_unchanged(input_path, source_sha256)
    except BaseException as error:
        try:
            for target in reversed(committed):
                restore_target(target, previous[target])
        except OSError as rollback_error:
            raise RenderError(
                f"render commit failed and output rollback failed: {rollback_error}"
            ) from error
        raise
    finally:
        for _, temporary_path in temporary:
            temporary_path.unlink(missing_ok=True)


def render_file_with_report(
    input_path: Path,
    *,
    output_path: Path | None = None,
    report_path: Path | None = None,
    source_map: bool = False,
) -> RenderResult:
    input_path = resolve_input_path(input_path)
    if not THEME_PATH.is_file():
        raise RenderError(f"theme not found: {THEME_PATH}")

    output_path = resolve_write_target(
        output_path if output_path is not None else input_path.with_suffix(".html"),
        label="HTML output",
        input_path=input_path,
    )
    if report_path is not None:
        report_path = resolve_write_target(
            report_path,
            label="JSON report",
            input_path=input_path,
            other_target=output_path,
        )

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
    blocks = annotate_source_map(tokens) if source_map else []
    body = parser.renderer.render(tokens, parser.options, environment)
    title = document_title(tokens, input_path.stem)
    html = build_document(title, css, body)

    assert_text_equivalent(tokens, html)
    assert_source_unchanged(input_path, original_digest)

    output_bytes = html.encode("utf-8")
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "sourceSha256": original_digest,
        "outputSha256": hashlib.sha256(output_bytes).hexdigest(),
        "title": title,
        "rendererVersion": RENDERER_VERSION,
        "ruleCounts": {
            f"{number}:{RULE_NAMES[number]}": counts[number]
            for number in sorted(RULE_NAMES)
            if counts[number]
        },
        "blocks": blocks,
    }
    report_json = json.dumps(
        report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    payloads: list[tuple[Path, bytes]] = []
    if report_path is not None:
        payloads.append((report_path, f"{report_json}\n".encode("utf-8")))
    payloads.append((output_path, output_bytes))
    commit_payloads(
        payloads, input_path=input_path, source_sha256=original_digest
    )
    return RenderResult(output_path, counts, report, report_json)


def render_file(
    input_path: Path,
    output_path: Path | None = None,
    *,
    source_map: bool = False,
) -> tuple[Path, Counter[int]]:
    result = render_file_with_report(
        input_path, output_path=output_path, source_map=source_map
    )
    return result.output_path, result.counts


def format_report(counts: Counter[int]) -> str:
    triggered = ", ".join(
        f"{number}:{RULE_NAMES[number]}={counts[number]}"
        for number in sorted(RULE_NAMES)
        if counts[number]
    )
    return triggered or "none"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Render immutable Markdown as a self-contained HTML reading view.")
    )
    parser.add_argument("input", type=Path, help="UTF-8 .md file to render")
    parser.add_argument(
        "--output",
        type=Path,
        help="write HTML to this existing directory instead of beside the source",
    )
    parser.add_argument(
        "--report-json",
        help="write the deterministic JSON report to a file, or '-' for stdout",
    )
    parser.add_argument(
        "--source-map",
        action="store_true",
        help="add deterministic non-visible block and source-line attributes",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report_path = (
            Path(args.report_json)
            if args.report_json is not None and args.report_json != "-"
            else None
        )
        result = render_file_with_report(
            args.input,
            output_path=args.output,
            report_path=report_path,
            source_map=args.source_map,
        )
    except (OSError, RenderError) as error:
        print(f"render failed: {error}", file=sys.stderr)
        return 1
    if args.report_json == "-":
        print(result.report_json)
    else:
        print(
            f"rendered {result.output_path} | rules: {format_report(result.counts)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
