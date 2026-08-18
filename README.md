# Render Markdown Reading View

> Content is immutable. Presentation is disposable.

Render Markdown Reading View is an Agent Skill that turns an existing Markdown document into a calm, polished reading experience. It produces a self-contained HTML file with responsive typography, automatic dark mode, print styles, structured callouts, readable tables, and syntax-driven visual components—without giving the renderer permission to rewrite a single word.

This is not a Markdown editor, a writing assistant, or a semantic page builder. Markdown remains the only source of truth. The HTML can be deleted and regenerated at any time.

## Why it exists

Raw Markdown is excellent source material, but it is not always the best delivery format for reports, reviews, handbooks, or long-form technical notes. This skill gives AI applications a consistent way to attach a refined reading view whenever they present a Markdown artifact, while preserving the author's exact text.

The design is intentionally restrained:

- a 760 px centered reading column and deliberate vertical rhythm;
- light and dark color systems selected by the reader's OS preference;
- no JavaScript, animation, external fonts, or runtime network dependency;
- syntax-only component detection, with no semantic guessing;
- deterministic output: identical Markdown and theme inputs produce identical bytes;
- built-in visible-text equivalence checks before any HTML is written.

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

The renderer has one hard invariant:

> Visible document text in the HTML must equal the author text parsed from Markdown, after Markdown syntax and normalized whitespace are removed.

The guarantee is enforced in code, not left to an agent prompt:

1. `markdown-it-py` parses the source once.
2. The same token stream produces both the HTML body and the expected author-text stream.
3. A standard-library HTML parser extracts text nodes from the completed document.
4. The normalized streams are compared.
5. A mismatch prints a unified diff, exits non-zero, and prevents a new output file.

The source SHA-256 digest is checked before and after output, providing an additional guard against writes or concurrent source changes.

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
| Fenced code | Low-contrast code block without syntax highlighting |
| `![alt](src)` | Figure with an author-supplied caption when alt is non-empty |
| Rule, link, strong, emphasis | Base reading styles |

The “every item” condition for enhanced lists is strict. One non-matching item keeps the entire list plain. The renderer deliberately prefers a missed enhancement over a false semantic claim.

## Output characteristics

- Single HTML file with the entire theme inlined
- UTF-8 document and responsive viewport metadata
- Automatic `prefers-color-scheme` dark mode
- Black-and-white-safe print stylesheet
- Horizontal table overflow on narrow screens
- Relative image sources preserved
- Raw HTML disabled and escaped by the parser
- No scripts and no syntax-highlighting dependency

## What it deliberately does not do

- edit, polish, summarize, translate, or reorder Markdown;
- infer metric cards, summaries, severity, ownership, or other semantics from prose;
- merge or split paragraphs;
- embed or download images;
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
├── requirements.txt
└── LICENSE
```

## Contributing

Changes are welcome when they preserve the project's narrow contract. A mapping change must have an explicit Markdown syntax trigger. A theme change must not change, hide, duplicate, or synthesize author text.

Before submitting a change, render the sample twice, verify byte-identical output, confirm both mixed-list counterexamples remain plain, and inspect light, dark, 375 px, and print views.

## License

[MIT](LICENSE)
