# vague-to-product (v2p) — Turn a Vague Idea into a Real Deliverable

> **English quick guide (condensed).** The canonical, full documentation is the Chinese [`README.md`](README.md) / [`SKILL.md`](SKILL.md); this file only covers what international users need to get started. Version: v2.7.0 · Companion skill: fuzzy-reverse-flow v1.5.0 · License: MIT © 2026 Zhang Yongxin (张勇鑫)

## What it does

`vague-to-product` is a methodology skill for AI hosts (WorkBuddy, Codex CLI, or any chat AI via system prompt). When a user says something vague like *"I want to build an alarm clock app"*, the host AI running this skill will:

1. **Classify** the idea into one of 8 deliverable types (app / web / mini-program / doc / sheet / graphic / 3D / av / physical) and score ambiguity on 5 signals to decide how deep to dig (D0–D4);
2. **Ask** a few rounds of sharp, option-based questions (max 4 per round, never repeated dimensions) instead of interrogating or guessing;
3. **Lock down** requirements into a one-page PRD / spec card with explicit "what we will NOT build";
4. **Deliver the actual product** — a buildable project, a finished document, a working spreadsheet — never stopping at a requirements document (Iron Rule 19, since v2.4.0);
5. **Attach a compliance roadmap** (Iron Rule 20): permits, filing requirements, and a week-by-week countdown plan, produced via the companion skill [fuzzy-reverse-flow](https://github.com/zhangyongxin-1124/fuzzy-reverse-flow). Verdicts are advisory only — every report carries a 7-clause disclaimer and mandatory human-verification notes.

## Install (3 steps)

1. Install Python 3, then download the latest Release ZIP from GitHub and unzip it.
2. Copy the folder into your host's skills directory (e.g. `~/.workbuddy/skills/` or `~/.codex/skills/`), or paste the system prompt (see `使用说明.txt`) into a web chat for the degraded Mode C experience.
3. Verify: say *"I want to build an app for seniors to find gigs"* — the AI should reply with a form verdict, a depth score, and option-based questions (not start coding immediately).

Full illustrated guide: `docs/quick-start.md` · Troubleshooting: `docs/FAQ.md`.

## CLI quick reference

```bash
python scripts/v2p.py route -t "your vague idea"     # form + depth + first-round questions
python scripts/v2p.py gate list -f app -d D2          # delivery gates for a form/depth
python scripts/v2p.py plan -t "..."                   # mining plan + compliance red lines in one shot
python scripts/selftest.py                            # end-to-end self test
```

MCP (local stdio, zero dependency, read-only tools): configure `python scripts/mcp_server.py` as a stdio MCP server exposing `v2p_route`, `v2p_gate_list`, `v2p_issue_codes`, `v2p_disclaimer`, `v2p_selfcheck`.

## Boundaries (hard constraints)

- Local files + CLI + on-disk knowledge base only. **No hosted SaaS, no public APIs, no paid service for the public.** Internal/loopback (127.0.0.1) use is allowed; the local stdio MCP server performs no network listening.
- All rules are experience-based summaries, **not legal advice**; verify against official sources before acting.
- Feedback: use the GitHub issue templates (bug / experience). See the Chinese README for the full capability-tier model (A/B/C) and the 12-item pre-flight checklist.

## Examples

See [`examples/README.md`](examples/README.md): one vague sentence → PRD + compliance red lines + countdown milestones, across real and clearly-labeled demonstration cases (alarm app, mini-program, milk-tea shop, business plan, inventory sheet).
