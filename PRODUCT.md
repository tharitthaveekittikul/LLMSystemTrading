# Product

## Register

product

## Users

A solo quantitative trader (the developer themselves) monitoring AI-driven trade execution across multiple MT5 accounts. Technically sophisticated — comfortable with Docker, Python, LangChain — but uses the dashboard for operational oversight, not for coding. The interface is opened intentionally: to review overnight AI signal activity, check position status, and verify the system is running correctly. Decisions are deliberate, not reactive.

## Product Purpose

AI-driven multi-account trading command center. The system autonomously generates trade signals via LLM and executes them through MetaTrader 5. The dashboard gives the operator visibility into signal quality, active positions, backtest results, and system health — without requiring them to intervene unless something is wrong. Success looks like: open the dashboard, understand the system's current state in under 30 seconds, close it again.

## Brand Personality

Calm, precise, authoritative. A system that is in control — not one that demands attention. Three words: **composed, vigilant, clear**.

## Anti-references

- **Robinhood / crypto dashboards** — gamified green/red flashes, ticker tape urgency, designed to provoke action. This system acts autonomously; the dashboard should reflect that composure.
- **Generic SaaS cream** — purple gradient cards, "modern startup" templates with rounded hero blobs. Chrome (sidebar, nav) should feel purposeful and refined, not fashionable.
- **Bloomberg Terminal density** — wall-to-wall data, no hierarchy, no breathing room. Signal-to-noise discipline is required.
- **Neon/cyberpunk fintech** — electric blue glows, matrix aesthetics. Antithetical to calm and trust.

## Design Principles

1. **Oversight over action.** The operator is a supervisor, not a trader. UI should confirm the system is working, not urge them to intervene.
2. **Signal discipline.** What requires attention should be obvious. Everything else should be quiet.
3. **Confidence through clarity.** Hierarchy, grouping, and spacing do the work — not decoration or animation.
4. **Dark-first.** The dashboard is likely viewed on a large monitor in a focused environment. Dark mode is the primary experience.
5. **Chrome serves content.** Sidebar and topnav are infrastructure — they should recede. The data pane is the product.

## Accessibility & Inclusion

WCAG AA minimum: 4.5:1 contrast ratio on all interactive text, keyboard-navigable throughout, visible focus indicators. Respect `prefers-reduced-motion`. Status indicators (kill switch, connection) must use label + color, never color alone.
