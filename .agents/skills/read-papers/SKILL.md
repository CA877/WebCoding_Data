---
name: read-papers
description: Read research papers in full and produce plain Chinese notes for WebCoding research using a mandatory eight-part structure. Use when the user asks to read, explain, compare, audit, or organize LLM, MLLM, Agent, GUI, accessibility, browser, or WebCoding papers; also use whenever the user asks to record an inspiration, identifies where an idea came from, points out a paper's weakness, or says an idea is their own.
---

# Read WebCoding Papers

## Read the original paper first

1. Read the applicable project `AGENTS.md`, project README, docs navigation, and existing paper-note index.
2. Locate the complete paper body. Prefer a complete local PDF/text extraction; otherwise use the official publisher, proceedings, DOI, or arXiv HTML/PDF.
3. Read the motivation, method, experimental setup, main results, ablations, limitations, and relevant appendices. Do not write a full note from the abstract alone.
4. Record the exact paper title, link, local source when available, version boundary, and sections actually inspected.
5. If a local file is partial or corrupt, state that boundary and use a complete official source.

## Write every paper with the mandatory structure

Use plain Chinese and keep this order. Do not merge or omit sections:

1. **论文解决什么问题**
2. **为什么采用这个顺序**
3. **方法具体怎样运行**
4. **用前端例子解释**
5. **论文怎样做实验**
6. **实验能证明什么**
7. **有哪些局限**
8. **对 WebCoding 有什么启发**

Before the eight sections, include the full paper title, official link, and a short plain-language conclusion. After them, include an original-source reading record when the note covers multiple papers.

### Requirements for each section

- Explain the authors' actual motivation before giving WebCoding interpretation.
- Describe the production order with concrete inputs, intermediate objects, selection steps, outputs, costs, and rejection conditions.
- Use one consistent frontend example. State the source page, what changes, the resulting query and ground truth, and which browser evidence would verify it.
- Report dataset size, model, baseline, metric, main result, and relevant ablation when the paper provides them.
- Separate “the experiment supports” from “the experiment does not establish.”
- Separate paper claims from Codex's inference. Label adjacent work that is not truly instruction synthesis.
- Treat browser, DOM, AX tree, application state, screenshots, interaction history, and tests as different evidence surfaces.
- Preserve uncertainty. Do not turn a proposal, preliminary result, model judge score, or small pilot into a proven conclusion.

## Keep paper notes, inspirations, and proposals separate

- Put pure paper explanations in the project's `paper_notes/` folder.
- Put research proposals in `proposals/`, one Markdown file per distinct production procedure. Keep variants of the same procedure in the same file.
- Put paper-derived ideas and user-supplied ideas in the single canonical inspiration Markdown under `inspirations/`.
- Keep raw PDFs, extracted text, manifests, logs, and experiment outputs separate from all three.
- When splitting a mixed legacy document, preserve every substantive paragraph. Move or reproduce content in the correct destination, record its source, and update navigation before retiring the mixed file.

## Append to the inspiration document

Whenever the user says “记录到灵感里”, “写进灵感”, or equivalent:

1. Locate the canonical inspiration Markdown from the project README/docs index. In `web_coding_sft`, default to `paper_review/inspirations/webcoding_instruction_augmentation_inspirations.md` after verifying it exists.
2. Append a new numbered entry; never overwrite previous entries.
3. Preserve the user's points and original order. Record the related paper when one was mentioned.
4. Focus on organizing rather than rewriting the user's content. Preserve their wording, examples, order, and judgments whenever possible; use headings, bullets, or a compact table to make them easier to retrieve. Unless the user explicitly asks for expansion, do not turn a short inspiration into long newly written passages.
5. Add only the minimum explanation needed to make the idea understandable or accurate: input material, processing order, possible output, cost source, and how WebCoding/browser evidence would inspect it.
6. State whether the entry is an atomic inspiration, a shared validation rule, or a developed proposal.
7. Treat inspirations as hypotheses. Use this sentence-level policy: ideas may identify a valuable production order, data source, verification method, or cost change; they are not complete methods or innovations until implemented and compared.
8. Use direct descriptive headings. Do not invent an acronym or decorate the idea with prestige terminology.

## Record the source of every inspiration

When the user explains where an idea came from, classify it into exactly one of these three types and record the type near the beginning of the inspiration entry:

1. **借鉴其他论文的思路。** Record the paper's complete title and official link. Separate what the paper actually proposes from the user's WebCoding adaptation or extension.
2. **针对其他论文做得不好的地方。** Record the paper's complete title and official link. State whether the weakness is acknowledged by the paper, demonstrated by its experiments, or identified by the user; do not turn the user's critique into an author claim.
3. **用户自己想出来的思路。** Mark it as `用户原创思路`. Do not attach a paper merely because related work exists.

If the user provides only an abbreviation, nickname, or incomplete title for either paper-based type, verify the complete title from the local full text or an official primary source before recording it. Never leave the first two types without the paper name, and never guess the source from superficial similarity.

## Promote an inspiration only with evidence

Move an inspiration into a proposal file only when the user asks to develop it or when the document already contains a complete procedure. A proposal must state:

- starting data and prerequisites;
- ordered processing steps;
- how query and ground truth are jointly produced;
- Generate/Edit/Repair applicability;
- main cost sources;
- browser acceptance evidence;
- failure and stopping conditions;
- implementation and empirical status.

Shared infrastructure such as a harness, Playwright, logging, checkpointing, and data layering is not a research contribution by itself.

## Validate documentation changes

Before finishing:

1. Confirm every requested paper or user point appears exactly once in the canonical destination.
2. Check that headings follow the mandatory order.
3. Check local links and source paths.
4. Search for stale links after moving files.
5. Update the project docs navigation and replacement relationships.
6. Report what was read from full text, what was reorganized, and what remains a hypothesis or historical record.
