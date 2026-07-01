# Plan 1: Dead Code / Unused Variables

**Branch:** `refactor/dead-code`
**Depends on:** nothing — do this first.
**Risk:** low for 1a, medium for 1b (false positives possible).

## Goal

Remove unused imports, unused local variables, and genuinely dead
(zero-caller) functions/exports across backend and frontend, without
touching anything that's actually load-bearing (framework entry points,
dynamically-dispatched code).

## Part 1a — Automated linter cleanup

Mechanical, tool-driven. No manual judgment calls expected here.

1. Backend: enable stricter unused-code detection temporarily for this pass
   — add `"ARG"` (unused function args) to `select` in `backend/pyproject.toml`
   only if you intend to act on it now; otherwise leave `select` as-is and
   just rely on the existing `F` rules (unused imports `F401`, unused local
   vars `F841`).
2. Run `uv run ruff check --fix .` from `backend/`. Review the diff —
   `--fix` on `F401`/`F841` is safe, but confirm nothing in `__init__.py`
   re-export barrels gets stripped (those imports look "unused" but are
   public API).
3. Frontend: run `npm run lint -- --fix` from `frontend/`. Review the diff.
4. Commit 1a as its own commit within the branch (separate from 1b) so it's
   easy to bisect if something breaks later.

## Part 1b — Repo-wide dead code (graph-assisted)

Higher risk — static "zero callers" does **not** mean unused. Before
deleting anything, check it against the allowlist below.

1. Use the code-review-graph MCP tools (`query_graph_tool` with
   `callers_of`, `get_impact_radius_tool`, `refactor_tool` /
   `find_large_functions_tool` for dead-function detection) to find
   exported functions/classes/components with zero call sites.
2. **Allowlist — never flag these as dead even with zero static callers:**
   - `frontend/src/app/**/page.tsx`, `layout.tsx`, `loading.tsx`,
     `error.tsx`, `not-found.tsx` — Next.js App Router invokes these by
     file convention, not by import.
   - `backend/api/routes/*.py` route handler functions — wired via
     `@router.get/post/...` decorators, not called directly in Python.
   - `backend/db/models.py` SQLAlchemy model classes/columns — referenced
     by the ORM and Alembic, not necessarily imported elsewhere.
   - Anything under an `alembic/versions/` migration directory.
   - Pydantic schema classes used only for FastAPI's OpenAPI generation.
3. For every candidate that survives the allowlist filter, do a manual
   `grep` across the **whole repo** (not just backend or frontend alone —
   frontend calls backend routes by URL string, not import) before
   deleting.
4. Delete in small batches, running the done-gate (see `00-overview.md`)
   after each batch — not once at the end. If anything breaks, the batch
   that caused it is small and obvious.

## Acceptance criteria

- `uv run ruff check .` clean (backend).
- `npm run lint` clean (frontend).
- `uv run pytest -v` passes.
- `npm run build` passes.
- No route, page, or migration was deleted (spot-check the diff against
  the allowlist above before opening the PR).
