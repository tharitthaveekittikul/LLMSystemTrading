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
