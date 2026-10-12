# Strategy: a repo that any AI assistant can pick up

This describes how this repo is organized so that an AI assistant can continue the work from the repo alone: on
another computer, in a fresh session, or with a different assistant. It's written so an assistant can set up the
same structure in another repo by following it.

## The problem it solves

An assistant's understanding of a project usually lives in places that don't travel:
- **the conversation**, which ends;
- **the assistant's own memory**, which is tied to one tool, one account or one computer;
- **the user's head**, which means re-explaining preferences and decisions every time.

The fix is to keep that understanding in the repo, in plain Markdown, in a place every assistant is pointed to, and
to keep it current as part of the work itself.

## Principles

1. **The repo is the memory.** Everything an assistant needs to continue is a file in the repo. Nothing important
   lives only in a chat or in an assistant's private memory.
2. **One home for AI context.** It all lives in `AI/`. Tool-specific entry files only point there, so switching
   assistants means adding a pointer, not rewriting anything.
3. **People and assistants get separate docs.** `README.md` is for people. `AI/` is for assistants, and can be
   detailed, explicit and full of reasons.
4. **Record the why.** Decisions are written down with their reasons, so a later session can tell a deliberate
   choice from an accident, and knows what to reconsider if the reason no longer holds.
5. **Docs are updated with the code, unasked.** Every change includes updating the docs it affects. A stale log is
   worse than none.
6. **Plain Markdown, no tooling.** Any assistant can read and write it; nothing needs installing.

## Layout

```
README.md            for people: what it is, how to run it, options, output
AGENTS.md            entry file: "read AI/MEMORY.md and AI/PROJECT_LOG.md first"
CLAUDE.md            entry file for Claude Code: imports the same two files
(other entry files)  one per assistant in use, same content
AI/
  MEMORY.md          how to work here: the user's preferences and rules, each with its reason
  PROJECT_LOG.md     the project: goal, decisions, how things work, history, status, open questions, known issues
  STRATEGY.md        this file: how the structure works and how to replicate it
```

### `AI/MEMORY.md`: how to work

The user's lasting preferences about how the assistant should work: process, testing, communication, what to ask
about and what to just do. Not facts about the project.

- One short section per rule: the rule, then a `*Why:*` line with the reason or the incident behind it.
- Written for any assistant ("an assistant should…"), with no tool-specific names or paths.
- Added to whenever the user states a lasting preference, including corrections ("don't do X") and confirmations
  ("yes, keep doing that").
- Starts with the rules that make this structure work (below), so they travel with every copy.

### `AI/PROJECT_LOG.md`: the project

Everything about the project that isn't obvious from the code. Suggested sections:

- **Goal:** what it's for, and what good looks like.
- **Design decisions:** each choice with its reason, and whether the user decided it or the assistant proposed it
  and it's not yet confirmed.
- **How things work:** external systems, data formats, APIs, quirks discovered along the way.
- **Code map:** where things are, briefly, for orientation.
- **Log:** dated entries for what changed and why, including approaches tried and dropped.
- **Status:** what works, what hasn't been run or tested.
- **Open questions:** decisions waiting on the user.
- **Known issues:** bugs and weak spots not yet fixed, with workarounds.
- **Next steps.**

Facts that are already plain from the code or version control don't need repeating; record what isn't.

### `README.md`: for people

What it is, how to install and run it, options, output, and any information derived for a person's benefit.
Reasons, history and working rules go in `AI/` instead.

### Entry files: pointers only

Each assistant looks for its own instructions file. Each should contain only a pointer to `AI/`, never content of
its own, so there's one place to update. Examples (check each tool's docs for the current name and format):

| File | Read by |
|---|---|
| `AGENTS.md` | a shared convention used by several assistants |
| `CLAUDE.md` | Claude Code; `@path` lines import files, so it can be just `@AI/MEMORY.md` and `@AI/PROJECT_LOG.md` |
| others (e.g. `GEMINI.md`, `.github/copilot-instructions.md`) | add one when that assistant is used, with the same pointer |

Where a tool can't import files, the entry file says in plain words to read `AI/MEMORY.md` and `AI/PROJECT_LOG.md`
before starting.

## Rules that keep it working

These go at the top of every `AI/MEMORY.md`:

1. **Read `AI/MEMORY.md` and `AI/PROJECT_LOG.md` before starting.**
2. **Remember in the repo.** Save preferences in `AI/MEMORY.md` and project facts in `AI/PROJECT_LOG.md`, not in the
   assistant's own memory.
3. **Keep the docs current without asking.** Each change includes updating the README, the log and the memory file
   as they're affected.
4. **README for people, `AI/` for assistants.**

## Setting it up in a repo

For an assistant doing this in a new or existing repo:

1. **Create `AI/`** with `MEMORY.md`, `PROJECT_LOG.md` and a copy of this `STRATEGY.md`.
2. **Write `AI/MEMORY.md`:** start with the four rules above (worded for that repo), then add the user's known
   preferences. If the user has preferences saved in an assistant's own memory, carry over the ones that still
   apply, generalized so any assistant can follow them.
3. **Write `AI/PROJECT_LOG.md`:**
   - new repo: the goal and the first decisions;
   - existing repo: read the code, docs and history, then write the goal, how things work, a code map, the current
     status, and the open questions. Ask the user about anything that can't be learned from the repo, especially
     the reasons behind decisions.
4. **Sort the README.** Keep what people need; move reasons, history and working notes into `AI/`.
5. **Add entry files:** `AGENTS.md`, plus one per assistant the user works with, each only pointing to `AI/`.
6. **Tell the user** what was created and what's still an open question.

## Day to day

- **Starting a session:** read `AI/MEMORY.md` and `AI/PROJECT_LOG.md`.
- **During work:** when a decision is made, a finding turns up, or a plan changes, record it in the log as part of
  that step. When the user states a preference, add it to `AI/MEMORY.md`.
- **Finishing a piece of work:** make sure the status, open questions and known issues in the log are true, and the
  README matches what a person would see.
