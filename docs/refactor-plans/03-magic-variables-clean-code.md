# Plan 3: Magic-Variable / Clean-Code Pass

**Branch:** `refactor/magic-values`
**Depends on:** Plans 1 and 2 merged first (don't extract constants from
code that's about to be deleted or restructured).
**Risk:** low — naming/extraction only, no logic changes.

## Goal

Replace repeated literal numbers/strings with named constants, and enable
lint rules going forward so new magic values get flagged (as warnings, not
hard failures — see `00-overview.md` for the reasoning).

## Step 1: enable the lint rules

- Backend: add `"PLR2004"` to `select` in `backend/pyproject.toml`'s
  `[tool.ruff.lint]`. Do **not** add it to a hard-fail CI gate yet — treat
  ruff warnings as informational for this pass (ruff doesn't have a
  separate warn/error split per-rule the way eslint does; if the repo's CI
  treats any ruff finding as a failure, either add targeted `# noqa:
  PLR2004` for the cases you're intentionally leaving as literals — e.g.
  HTTP status codes, `0`/`1`/`-1` — or scope the rule to specific modules
  first via `per-file-ignores` and widen later).
- Frontend: add `"no-magic-numbers"` to `eslint.config.mjs` as `"warn"`,
  with an `ignore` list for common legitimate literals (`0, 1, -1, 2`) and
  `ignoreArrayIndexes: true`.

## Step 2: run and triage

1. Run `uv run ruff check .` (backend) and `npm run lint` (frontend) and
   collect every new `PLR2004`/`no-magic-numbers` finding.
2. Triage each finding into one of:
   - **Extract to a named constant** — genuinely magic (a drawdown
     threshold, a retry count, a timeout, a provider name string repeated
     across files).
   - **Leave as-is with a suppression comment** — genuinely fine (array
     index, status code, mathematical constant like `2` for doubling).
3. For repeated **string** literals specifically (not caught by
   `no-magic-numbers`/`PLR2004`, which target numbers) — e.g. provider
   names `"openai"`/`"gemini"`/"anthropic"` appearing as raw strings across
   `orchestrator.py`, `settings.py`, `_helpers.py`, `position_maintenance.py`
   — introduce a shared `Literal["openai", "gemini", "anthropic",
   "openrouter", "ollama"]` type alias or enum in one place
   (e.g. `backend/ai/providers.py`) and use it everywhere instead of
   scattering the raw string list.

## Step 3: where constants should live

- Backend: module-level `_CONSTANT_NAME` (private, leading underscore) if
  used only within one file; a shared `core/constants.py` if used across
  modules (e.g. risk/drawdown defaults, kill-switch thresholds).
- Frontend: co-locate with the component if used once; `src/lib/constants.ts`
  if shared across components (check whether this file already exists
  before creating a new one).

## Acceptance criteria

- `uv run ruff check .` passes (with any intentional `noqa` comments
  reviewed in the PR).
- `npm run lint` passes (warnings visible, not blocking).
- `npm run build` passes.
- `uv run pytest -v` passes — this should be a pure rename/extraction, so
  no test behavior should change. If a test needs updating, that's a signal
  the "extraction" accidentally changed behavior — stop and re-check.
