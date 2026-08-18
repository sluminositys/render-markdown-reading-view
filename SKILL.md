---
name: render-markdown-reading-view
description: Present an existing Markdown file through a polished, self-contained single-file HTML reading view. Use whenever an AI application is about to show Markdown for reading, including requests to render, present, typeset, beautify, or generate a readable version, and report-like Markdown artifacts produced by an agent. Do not use for requests to edit, rewrite, summarize, translate, or otherwise change Markdown content.
---

# Render Markdown Reading View

This skill is a renderer, not a writing tool. The Markdown file is the only source of truth; HTML is a disposable reading artifact that can always be regenerated.

Whenever an AI application would present a Markdown document for reading, present the generated HTML reading view instead of the raw Markdown artifact. Keep the Markdown file as the only editable source.

## 第一铁律:内容不变性

> 渲染后 HTML 的全部可见正文,与 md 去除语法记号后的正文,逐字符一致。

- 禁止:增写、删减、改写、润色、概括、翻译、重排任何内容;禁止补写"一句话结论"之类 md 里没有的东西;禁止合并或拆分段落。
- "语法记号"指 `#`、`**`、`` ` ``、`>`、`- `、表格管道符、`[!CAUTION]` 这类标记行——它们是语法,消费后不显示;除此之外全是内容,一律原样保留(包括 emoji、包括作者的错别字)。
- **实现上必须由脚本保证,不靠自觉**:转换由 skill 附带的确定性脚本完成,使用 skill 的 agent 只负责调用脚本,禁止手工书写或修改 HTML 正文。

## 唯一工作流

1. 定位作为唯一事实源的 `.md` 文件。
2. 运行 `python <skill-directory>/scripts/render.py <input.md>`。脚本在 Markdown 同目录生成同名 `.html`,强制执行文本等价校验,并打印规则触发计数。
3. 将生成的 `.html` 作为阅读版交付,同时保留 `.md` 作为唯一可编辑源。模型不得触碰 HTML 正文。

若脚本缺少 `markdown-it-py`,停止并报告依赖缺失;不得以手写 HTML 代替确定性渲染。

## 渲染不满意时

只允许以下两种动作:

1. 经用户明确同意后修改 Markdown 原文,再重新渲染。
2. 修改本 skill 的映射规则或 `assets/theme.css`,再重新渲染。

禁止单独手改任何一份 HTML 产物。禁止基于内容语义推断组件。v1 不生成指标卡。

## 确定性映射表

| # | Markdown 模式(触发条件) | 渲染结果 |
| --- | --- | --- |
| 1 | `#` 一级标题 | `h1` |
| 2 | `h1` 之后的第一个普通段落 | lede 样式,仅字色变化,文字不动 |
| 3 | `##` / `###`;`####` 及更深 | `h2` / `h3`;更深标题保留原标签并按 `h3` 样式显示 |
| 4 | 引用块首行为 `[!CAUTION]` 或 `[!WARNING]` | caution 警示块,标记行转为对应大写标签 |
| 5 | 引用块首行为 `[!NOTE]` 或 `[!IMPORTANT]` | note 警示块 |
| 6 | 引用块首行为 `[!TIP]` | tip 警示块 |
| 7 | 普通引用块,无标记 | 安静引用样式,左细线加浅底 |
| 8 | 列表且每一项都以 ✅/⚠️/🔴/❌ 开头 | 状态清单,glyph 原样保留,不替换字符 |
| 9 | 列表且每一项都匹配 `**标签**:描述` 或 `**标签**: 描述`,全角/半角冒号皆可 | 定义式条目 |
| 10 | 其余列表 | 普通列表样式 |
| 11 | 行内 code 内容含 `/`,或以已知扩展名结尾 | 文件胶囊;`py js ts md go rs java sh json yaml css html` 使用扩展名色点,其余路径使用灰点 |
| 12 | 其余行内 code | 浅底胶囊 code |
| 13 | 表格 | 无竖线表格;整列除表头均为数字、百分比或货币时,该列使用 `tabular-nums` |
| 14 | 围栏代码块 | `pre` 样式,不做语法高亮 |
| 15 | `![alt](src)` | `figure`;alt 非空时作为 `figcaption`,为空时无图注,不编造文本 |
| 16 | `---` 水平线、链接、粗体、斜体 | 对应基础样式 |

规则 8 和规则 9 的“每一项都”是硬条件。只要存在一个不匹配项,整个列表必须按规则 10 渲染。
