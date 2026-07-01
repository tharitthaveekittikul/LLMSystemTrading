# Plan 02: News Enable-by-Default + Calendar Page

**Branch:** `feature/news-enable`
**Depends on:** nothing.
**Risk:** low.

## Goal

Make news analysis actually run by default, make the toggle visible/
changeable from the settings UI, and give the user a page to see what
events were fetched — currently there's no way to see fetched events at
all, which is presumably why "it always shows no events" went unnoticed
as "the gate is off" for this long.

## Part A — Backend default flip

1. Change `core/config.py` `news_enabled` default from `False` to `True`.
2. Confirm the `GlobalSettings` DB row (id=1) — if it already exists with
   `news_enabled=false`, the config.py default change alone won't take
   effect (DB row wins per `api/routes/settings/_global.py:47-52`). Write
   a one-time migration or startup check that sets the DB row to match the
   new default *only if the row doesn't exist yet* — do not silently
   overwrite a value the user may have deliberately set.
3. Verify `services/scheduler/_lifecycle.py:83` picks up the change
   without a restart (it reads `settings.news_enabled` — confirm this is
   the same in-memory object the PATCH endpoint mutates, not a stale copy
   read once at scheduler-start).

## Part B — Settings UI toggle

1. Find (or add, if genuinely absent) the frontend settings page that
   calls `GET/PATCH /settings/global`. Add a `news_enabled` toggle there
   if one doesn't already exist — check `frontend/app/settings/` (or
   equivalent) first before assuming it's missing; only the dedicated
   news/calendar page was confirmed absent this session, not necessarily
   every settings control.
2. Toggle should show current DB-resolved value (not the `.env` default),
   since that's the source of truth per `_global.py`.

## Part C — `/news` calendar page (new feature)

1. New route `frontend/app/news/page.tsx`. Backend already has the
   ForexFactory fetch/analyze pipeline (`services/news_analyzer.py`,
   `services/scheduler/_lifecycle.py:105,112` — fetch at 23:00 UTC,
   analyze at 00:00 UTC) — find or add a read endpoint that returns stored
   news events (check for an existing `news_events`-type table/route
   before adding a new one).
2. Minimal viable page: table of upcoming events (time, currency, impact
   level, actual/forecast/previous if available), filterable by symbol/
   currency the user actually trades. Add a manual "fetch now" button that
   calls the existing fetch job function directly (useful for verifying
   the pipeline works without waiting for 23:00 UTC).
3. Surface, per event, whether it triggered a HOLD override on any recent
   signal (`analyze_news_impact` sets `signal.action = "HOLD"` when news
   direction contradicts — link back to the relevant `AIJournal`/pipeline
   run if feasible) — this is what makes news analysis *auditable*, which
   the user explicitly asked for.

## Acceptance criteria

- Fresh deploy (no existing `GlobalSettings` row) has news enabled by
  default.
- Existing deploy (row already exists) is not silently overwritten if the
  user had explicitly disabled it.
- `/news` page loads and shows real fetched events within one scheduled
  fetch cycle, or immediately via the manual fetch button.
- `npm run build` and `npm run lint` pass.

## Post-implementation note (what already existed vs. what was built)

Before writing code, re-verifying this doc's own assumptions (per the
sibling `01` plan's lesson that these docs can go stale) turned up that
**Part C was already substantially built** — not reflected anywhere in this
doc:

1. **The `/news` calendar page already existed.**
   `frontend/src/app/news/page.tsx` (note: the app router root is
   `frontend/src/app/`, not `frontend/app/` as this doc assumed) plus
   `frontend/src/components/news/event-row.tsx` already implemented list/day
   views, impact + currency filters, a "Fetch Now" button, an "Analyze
   Today" button, per-event LLM signal badges, expandable summaries, an
   "actual value" editor, and an LLM debug/raw-prompt viewer.
2. **`EconomicEvent` was already a persisted table** (`economic_events`,
   `db/models.py`), populated by `services/news_fetcher.py` (23:00 UTC
   fetch) and enriched by `services/news_analyzer.py` (00:00 UTC LLM
   analysis) — this doc's premise that "fetched news events aren't
   currently persisted anywhere" was stale.
3. **The read/write API already existed**: `api/routes/news.py`
   (`GET /news`, `GET/PATCH /news/{id}`, `POST /news/fetch`,
   `POST /news/{id}/analyze`, `POST /news/analyze-today`,
   `POST /news/{id}/analyze-debug`), mounted at `/api/v1/news`. Part C's
   "find or add a read endpoint" and "add a manual fetch-now button wired
   to the fetch logic" were both already done.

Given that, the actual implementation on this branch was narrower than
Part C originally described, and instead focused on two real gaps this
doc's own Part A asked to *verify* — both turned out to be broken:

- **`_lifecycle.py:83` did NOT pick up a live `news_enabled` toggle** — the
  scheduler only registered `news_fetch_daily`/`news_analyze_daily` once,
  at `start_scheduler()` time, based on `settings.news_enabled` at that
  instant. `PATCH /settings/global` flipped the DB row and the in-memory
  flag but never added/removed the actual APScheduler jobs, so toggling the
  setting silently required a backend restart to take effect (in either
  direction). Fixed by extracting `_register_news_jobs()` and adding
  `services/scheduler/_lifecycle.py::reschedule_news_jobs(enabled)`, wired
  into the `PATCH` route in `api/routes/settings/_global.py` — mirrors the
  existing `reschedule_maintenance_job` hot-reload pattern.
- **The `GlobalSettings.news_enabled` DB column default was still `False`**
  (`db/models.py`). Because the row is lazily created on the *first* PATCH
  to *any* global setting (not just `news_enabled` — see
  `patch_global_settings`), an operator who only ever touched, say, the
  maintenance interval would have silently pinned `news_enabled=False`
  forever via the ORM column default, regardless of the `core/config.py`
  default. Fixed by flipping the column default to `True` to match, and by
  adding `services/settings_bootstrap.py::ensure_global_settings_row()` —
  called once from `main.py`'s lifespan — which creates the row
  deterministically at boot (seeded from current in-memory settings) only
  if it has never existed, and never touches an existing row. This is the
  "startup-time check/migration" Part A asked for.

### Actual changes on this branch

- `backend/core/config.py` — `news_enabled` default flipped to `True`.
- `backend/db/models.py` — `GlobalSettings.news_enabled` column default
  flipped to `True` to match.
- `backend/services/settings_bootstrap.py` (new) —
  `ensure_global_settings_row()`, unit-tested in isolation
  (`tests/test_settings_bootstrap.py`) without touching the real DB
  singleton row.
- `backend/main.py` — lifespan now calls `ensure_global_settings_row()`
  instead of inline create-or-skip logic.
- `backend/services/scheduler/_lifecycle.py` /
  `backend/services/scheduler/__init__.py` — added
  `reschedule_news_jobs()`; tested in
  `tests/test_news_scheduler_toggle.py`.
- `backend/api/routes/settings/_global.py` — PATCH route calls
  `reschedule_news_jobs()` when `news_enabled` changes.
- `frontend/src/components/settings/news-section.tsx` (new) + wired into
  `frontend/src/app/settings/page.tsx` — the toggle this doc's Part B
  asked for; confirmed genuinely absent (unlike Part C's page).
- `frontend/src/app/news/page.tsx` — added a `symbol` filter input next to
  the existing currency filter (the backend's `GET /news?symbol=` param
  already existed but had no UI control).

### Skipped — Part C, item 3 (HOLD-override → AIJournal linkage)

Not implemented. `services/ai_trading/_signal.py`'s news gate
(`analyze_news_impact`, fed by `services/market_context.fetch_high_impact_events`)
fetches live from ForexFactory **independently** of the persisted
`economic_events` table that the calendar page reads
(`services/news_fetcher.py` / `services/news_analyzer.py`) — the two code
paths share no row IDs or other join key. Linking a calendar event to "this
triggered a HOLD override on pipeline run N" would require either rewriting
the trading pipeline's news gate to query `economic_events` instead of
live-fetching, or adding a fuzzy match (title + currency + time window) plus
a new FK from `PipelineStep`/`AIJournal` to `EconomicEvent.id`. Both are
more than the "if feasible" scope this plan allows — flagging as a
candidate for its own follow-up plan rather than scope-creeping this PR.

### Not verified (needs a live/real environment)

- `npm run build` could not be executed in the sandbox that implemented
  this — it has Node 18.19.1 installed, with no version manager and no
  Docker registry access to fetch a Node ≥20.9.0 image (Next.js 16's
  minimum, per the "Node.js version >=20.9.0 is required" build-time
  check). Confirmed via `git stash` that `npm run build` fails identically
  on the unmodified tree — this is a pre-existing sandbox limitation, not a
  regression. Verified equivalently instead: `npm run lint` (passes, only
  pre-existing warnings/errors in untouched files) and `npx tsc --noEmit`
  (passes, one pre-existing unrelated error in `backtest/page.tsx`, present
  before and after this change). Re-run `npm run build` for real in the
  dev/CI environment (Node 20+, per `frontend/Dockerfile`) before merging.
- The live 23:00/00:00 UTC scheduled fetch/analyze jobs and the "Fetch Now"
  button against the real ForexFactory endpoint were not re-exercised
  end-to-end in this session (pre-existing, untouched code paths).
- `reschedule_news_jobs()` is unit-tested against a locally-started
  APScheduler instance, not against a live running backend process toggling
  the setting through the real `PATCH /settings/global` HTTP endpoint.
