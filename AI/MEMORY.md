# Working notes for AI assistants

## Start here

1. Read `AI/PLAN.md` for the current project state.
2. Read `AI/LOCAL.md` if it exists for this computer's setup and protected local files.
3. For operational requests (setup, smoke tests, finding or downloading samples), follow `AI/USAGE.md`.
4. Read `AI/PROJECT_LOG.md` when history matters, before revisiting an approach or interpreting an old decision.
5. Read `AI/STRATEGY.md` when changing how these docs are organized.

## How this repo is organized for AI

- `AI/` is the single home for everything an assistant needs: `MEMORY.md` (how to work: these notes),
  `PLAN.md` (current goal, approach, status, issues and next steps), `PROJECT_LOG.md` (dated history and reasons),
  `USAGE.md` (operational tasks and prerequisites), and `STRATEGY.md` (the organization and how to replicate it).
- `AI/LOCAL.md` (optional, git-ignored) holds what's true only on one computer: local paths, related projects next
  to the repo, local run state, machine-only rules.
- Entry files (`AGENTS.md`, `CLAUDE.md`, and any other assistant's equivalent) only point to the files in `AI/`.
  They hold no content of their own, so nothing depends on which assistant is used.
- `README.md` is for people: what the project is, how to run it, options, output, and information derived for
  them.

*Why:* the user may continue on another computer, in a fresh session, or with a different assistant. Only the
repo's own files carry over, and they should work for any assistant.

## Remember things in the repo, not in the assistant's own memory

Save lasting preferences in this file, current project facts in `AI/PLAN.md`, dated history in
`AI/PROJECT_LOG.md`, and anything about this computer in `AI/LOCAL.md`. Rewrite the plan to keep it true;
append to the historical log. Don't use an assistant's built-in or per-machine memory for this project.

*Why:* built-in memory stays on one computer or account, and other assistants can't see it.

## Keep the shared docs self-contained

The README and shared `AI/` docs describe only the repo: no local paths,
machine details, or files, folders and projects outside it. Describe outside needs generically ("the project that
uses the samples"); where they are on this computer goes in `AI/LOCAL.md`.

*Why:* the shared docs travel with the repo to other computers, other people and possibly the public. Local details
are wrong elsewhere and can expose private information.

## Keep the docs current without asking

Update affected docs as part of each change, without asking first:
- the README when what a person sees or runs changes;
- the plan for the current approach, status, open questions and known issues;
- the log for dated decisions and their reasons, findings and history;
- the usage guide when operational tasks or their prerequisites change;
- this file when the user states a lasting preference about how to work.

*Why:* the docs should always match the code, so the next session can pick up from them alone.

## Test a script as designed; don't survey around it

Test a script by running it the way it's meant to run, with its normal limits, not by raising the limits or writing
side queries to survey every input. If the output is wrong, fix the script.

While the user is still shaping what a script should do, don't run it after each edit. Wait until they say to.

*Why:* the script is supposed to do the work itself; an exhaustive survey wastes requests and time, and runs during
design aren't wanted.

## Judge a run by whether the tool works, not by one reader's results

When reviewing a run, check that the tool behaves correctly. Don't analyse or record the particular reader's
results (for example, how many candidates fell outside the length range), and don't let them drive design.

*Why:* the tool is meant for many readers in very different situations; one reader's numbers aren't useful.

## Solve observed problems only

Don't plan or build fixes for problems that are only theoretical. Mention a risk once at most, then drop it until
it actually shows up in testing.

*Why:* speculative issues steered design choices before anyone had seen them happen.

## Protect files the user creates

Before a test writes to or deletes a path the user may have created themselves (local configs, anything
git-ignored and machine-specific), check whether it exists. Prefer a scratch path; if the real path is needed, move
the existing file aside and restore it in the same step.

*Why:* a test once overwrote and then deleted a config file the user had just saved, and it had to be recreated.


## Console and sessions

Use librivox_web.py as the primary entry point; keep implementation in src/librivox_download/, including its namespaced vendored
microweb.py. Do not add a root framework wrapper. Keep librivox_web.py as the only root Python launcher and component adapter. Ordinary console startup
without a JSON argument opens a picker; it must not silently select or create a session. New session accepts
a filename and creates exclusively under launch-directory sessions/, which is ignored. Existing JSON files
in that directory and the launch directory remain selectable. Session switching is inside the downloader
panel and drains old work before replacing only its controller, preserving files and decisions.

*Why:* the user wants a clean root entry point and seamless standalone/shared hosting, with explicit session
selection, visible active filenames and no server restart when switching.

## Explain reader-entry lockout

Keep adding readers restricted to idle collection for now; show a visible explanation when scanning or
downloading disables Add reader.

*Why:* the user prefers the simpler existing behavior while the combined console is being exercised.
