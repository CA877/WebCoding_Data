---
name: codex-cli-edit-generation
description: Generate and browser-validate WebCoding Edit cases with Codex CLI, Nju-Link gpt-5.6-luna, and the project's reusable Edit Skills. Use when constructing Edit GT from 0921 source projects and instructions.
metadata:
  short-description: Minimal-path Codex CLI Edit generation
---

# Codex CLI Edit Generation

Use the project wrapper `scripts/codex_cli_with_edit_skills.sh` (or `~/.local/bin/codex`) so the CLI uses an isolated temporary `CODEX_HOME`, the Nju-Link `gpt-5.6-luna` provider, the configured proxy, and the 16 component Skills under `harness/.agents/skills`.

For each Edit case, preserve the source project's framework, routes, data, DOM structure, and existing behavior. Process the numbered instructions as a strict sequential loop: finish and browser-check instruction N before reading or implementing N+1. For each one, choose one route-local host entry point and implement the smallest observable end-to-end slice using the matching Skill's component and the host's existing state/events. Keep each instruction to 1-3 existing files and roughly 120 changed lines; if the requested behavior appears broader, narrow it to the core interaction instead of expanding the app. Copy only the needed reference fragment. Never replace or delete a whole source file, scaffold a parallel app, add dependencies, invent a data model, or reformat unrelated code.

In fast generation mode, do not start a server or browser and do not run a build, typecheck, audit, dependency install, file check, or diff check. Stop immediately after the minimal patch is written; browser validation is deferred to a later sample audit.

When running multiple cases, isolate each case directory and browser port. Use bounded concurrency, per-case timeout, and independent logs. A missing Node dependency or source startup failure is an environment/source failure; record it instead of changing the sample to satisfy the runner.

The wrapper does not modify the desktop Codex configuration. Do not print or commit the Nju-Link token. Validate the final patch by replaying it from the original source before marking the case accepted.
