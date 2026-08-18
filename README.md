# Render Markdown Reading View

> Content is immutable. Presentation is disposable.

Render Markdown Reading View is an Agent Skill that turns an existing Markdown document into a calm, polished reading experience. It produces a self-contained HTML file with responsive typography, automatic dark mode, print styles, common README syntax, structured callouts, readable tables, build-time MathML, and static syntax-colored code—without giving the renderer permission to rewrite a single word, formula, or code character.

This is not a Markdown editor, a writing assistant, or a semantic page builder. Markdown remains the only source of truth. The HTML can be deleted and regenerated at any time.

## Why it exists

Raw Markdown is excellent source material, but it is not always the best delivery format for reports, reviews, handbooks, or long-form technical notes. This skill gives AI applications a consistent way to attach a refined reading view whenever they present a Markdown artifact, while preserving the author's exact text.

The design is intentionally restrained:

- a 760 px centered reading column and deliberate vertical rhythm;
- light and dark color systems selected by the reader's OS preference;
- no JavaScript, animation, external fonts, or runtime network dependency;
- native, static MathML for explicitly delimited inline and display formulas;
- build-time code coloring only when the fence declares a known language;
- deterministic rendering for frontmatter, tasks, footnotes, definition lists, heading anchors, and safe documentation HTML;
- syntax-only component detection, with no semantic guessing;
- deterministic output: identical Markdown and theme inputs produce identical bytes;
- built-in prose, formula-position, exact TeX-source, and exact fenced-code checks before any HTML is written.

## Quick start

Requires Python 3.10 or newer.

```bash
python -m pip install -r requirements.txt
python scripts/render.py path/to/document.md
```

The command creates `path/to/document.html`. It never writes back to the Markdown file.

Open the generated file in any modern browser. CSS is inlined into the document; Markdown image paths remain relative by design, so referenced local images should travel with the HTML.

To inspect the complete component set:

```bash
python scripts/render.py examples/sample.md
```

Then open [`examples/sample.html`](examples/sample.html).

## Install as an Agent Skill

Clone the repository into your agent's skill directory:

```bash
git clone https://github.com/sluminositys/render-markdown-reading-view.git \
  ~/.codex/skills/render-markdown-reading-view
```

The skill is eligible for automatic use when a user asks to render, present, typeset, beautify, or generate a readable version of an existing Markdown file. It also applies when an agent has produced a report-like Markdown artifact and should attach a reading version.

Requests to rewrite, summarize, translate, reorganize, or otherwise edit the source do not belong to this skill.

## Content guarantee

The renderer has one hard invariant: author content does not change. It enforces that invariant through coordinated audit channels:

> Visible non-formula text and formula positions must match the parsed Markdown; every formula's exact TeX token source and every fenced code block's exact character stream must survive in the same order. Syntax-generated controls never authorize moving author content.

The guarantee is enforced in code, not left to an agent prompt:

1. `markdown-it-py` parses the source once.
2. Explicit `$...$`, `$$...$$`, `\(...\)`, and `\[...\]` tokens are compiled to static MathML during rendering.
3. The exact unmodified TeX token source is embedded in the MathML `annotation` element.
4. The same token stream produces expected prose, positioned formulas, ordered TeX sources, and exact fenced-code sources.
5. A standard-library HTML parser independently extracts all audit streams from the completed document.
6. Any prose, position, formula, or fenced-code mismatch prints a unified diff, exits non-zero, and prevents a new output file.

The source SHA-256 digest is checked before and after output, providing an additional guard against writes or concurrent source changes. Footnote definitions remain where the author placed them; only their reference number is generated as presentation chrome.

MathML is the visual projection of the exact TeX source, not replacement author text. The output uses the browser's native math layout engine, so fractions, radicals, scripts, sums, matrices, and scalable delimiters remain crisp at any zoom level. No client-side script, CDN, web font, or runtime conversion is involved.

Admonition names such as `CAUTION` are interface labels generated from explicit marker syntax. They are presentation chrome, not inferred prose. Image alt text is rendered once as a caption when non-empty; an empty alt produces no caption.

## Deterministic mappings

Every enhanced component has an exact syntax trigger. Anything else receives the base reading style.

| Markdown syntax | Reading component |
| --- | --- |
| `#`, `##`, `###`, deeper headings | Fixed heading scale; level 4+ keeps its semantic tag and uses the level-3 visual style |
| First ordinary paragraph after a top-level `h1` | Lede color |
| `[!CAUTION]`, `[!WARNING]` blockquote marker | Caution callout |
| `[!NOTE]`, `[!IMPORTANT]` blockquote marker | Note callout |
| `[!TIP]` blockquote marker | Tip callout |
| Unmarked blockquote | Quiet quote |
| Every list item begins with ✅, ⚠️, 🔴, or ❌ | Status list |
| Every list item begins with `**label**:` or `**label**：` | Definition-style list |
| Other or mixed list | Plain list |
| Inline code contains `/` or ends in a known extension | File chip with an extension color dot |
| Other inline code | Neutral code chip |
| Table | Rule-only table; all-numeric body columns use tabular figures |
| Fenced code with a recognized language alias | Static syntax-colored spans generated at build time |
| Fenced code without a recognized language alias | Plain low-contrast code block; language is never guessed from content |
| A paragraph containing only `![alt](src)` | Block figure with an author-supplied caption when alt is non-empty |
| An image sharing a paragraph with other content | Compact inline figure; non-empty alt remains visibly preserved |
| Rule, link, strong, emphasis | Base reading styles |
| Single-line `$...$` | Baseline-aligned native MathML with exact TeX annotation |
| Block-level `$$...$$` without internal blank lines | Background-free, centered native MathML with horizontal overflow for narrow screens |
| Initial `---` frontmatter | Low-contrast metadata block preserving every interior character |
| `[ ]`, `[x]`, or `[X]` at the start of a list item | Static task checkbox |
| `~~text~~` | Strikethrough |
| `[^label]` with `[^label]: text` | Linked footnote whose definition stays at its source position |
| Bare `http://` or `https://` URL | Automatic link with unchanged display text |
| Any heading | Stable Unicode `id`; duplicate ids receive `-1`, `-2`, and so on |
| `\(...\)` and block `\[...\]` | The same static MathML components used for dollar-delimited math |
| Pandoc-style `Term` followed by `: Definition` | Semantic definition list |
| Safe HTML subset | Static `details`, `summary`, `kbd`, `mark`, `sub`, `sup`, and `br`; comments are consumed |

The “every item” condition for enhanced lists is strict. One non-matching item keeps the entire list plain. The renderer deliberately prefers a missed enhancement over a false semantic claim.

## Output characteristics

- Single HTML file with the entire theme inlined
- UTF-8 document and responsive viewport metadata
- Automatic `prefers-color-scheme` dark mode
- Black-and-white-safe print stylesheet
- Horizontal table overflow on narrow screens
- Relative image sources preserved
- Fixed safe-HTML allowlist; every other tag or attribute is visibly escaped
- Static native MathML with exact TeX-source annotations
- Static Pygments token spans for explicitly labeled fenced code
- No client-side scripts, math CDN, or runtime syntax highlighter

## Formula syntax and behavior

Inline formulas use a balanced single-dollar pair on one line:

```markdown
Energy and mass are related by $E = mc^2$.
```

Display formulas start a Markdown block with `$$`; the closing `$$` may be on the same line or a later line, but blank lines inside the formula are intentionally rejected:

```markdown
$$
\operatorname{softmax}(z_i) = \frac{e^{z_i}}{\sum_{j=1}^{K} e^{z_j}}
$$
```

Literal dollar signs can be escaped as `\$`. Formula recognition is deliberately conservative: labels, automatic equation numbering, semantic inference, inline `$$...$$`, and TeX commands that emit links, styles, or non-MathML elements are not supported. Converter output is parsed and checked against a presentation-only MathML allowlist; a conversion or safety error exits non-zero before the destination is written.

The equivalent bracket delimiters are also accepted:

```markdown
Euler's identity is \(e^{i\pi} + 1 = 0\).

\[
\int_0^1 x^2\,dx = \frac{1}{3}
\]
```

Display formulas intentionally share the document background. Spacing and centering establish hierarchy without presenting equations as code cards or callouts.

## Code highlighting

Fenced code is colored only when its info string starts with a language alias known to Pygments:

````markdown
```python
def render(source: str) -> str:
    return source
```
````

Highlighting runs during HTML generation and emits only escaped text wrapped in token `<span>` elements. Newline stripping and insertion are disabled, and the completed code block remains part of the mandatory visible-text equivalence audit. No language label, line number, copy button, or runtime script is added.

An empty or unknown fence language receives the plain code style. The renderer never guesses a language from code content.

Mermaid and other executable diagram fences intentionally remain exact plain source blocks. Rendering them as diagrams would require an additional JavaScript/Chromium toolchain and would violate the core's zero-runtime-script boundary.

## Safe documentation HTML

Common documentation-only tags are accepted through a fixed allowlist: attribute-free `kbd`, `mark`, `sub`, `sup`, `summary`, and `br`, plus `details` with only an optional `open` attribute. HTML comments are treated as non-visible syntax. No event handlers, styles, scripts, arbitrary attributes, or other tags are passed through; unsupported markup is escaped so it remains inspectable instead of executing.

## What it deliberately does not do

- edit, polish, summarize, translate, or reorder Markdown;
- infer metric cards, summaries, severity, ownership, or other semantics from prose;
- merge or split paragraphs;
- embed or download images;
- infer formulas from unmarked prose, or invent equation labels and numbers;
- infer a programming language from an unlabeled code block;
- execute Mermaid or another diagram language;
- pass through arbitrary raw HTML, styles, event handlers, or scripts;
- add generated conclusions, labels, or captions that lack explicit syntax;
- provide a WYSIWYG workflow for modifying generated HTML.

If a reading view needs to change, change the source Markdown with the author's approval or change the shared mapping/theme, then regenerate the HTML. Generated HTML is never patched by hand.

## Project layout

```text
render-markdown-reading-view/
├── SKILL.md
├── scripts/
│   └── render.py
├── assets/
│   └── theme.css
├── examples/
│   ├── sample.md
│   ├── sample.html
│   └── sample-figure.svg
├── tests/
│   └── test_render.py
├── requirements.txt
└── LICENSE
```

## Contributing

Changes are welcome when they preserve the project's narrow contract. A mapping change must have an explicit Markdown syntax trigger. A theme change must not change, hide, duplicate, or synthesize author text.

Before submitting a change, render the sample twice, verify byte-identical output, confirm both mixed-list counterexamples remain plain, and inspect light, dark, 375 px, and print views.

## License

[MIT](LICENSE)
