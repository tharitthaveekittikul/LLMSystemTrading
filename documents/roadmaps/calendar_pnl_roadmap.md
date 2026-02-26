# Calendar PnL Roadmap (TopstepX Style)

This document outlines the roadmap and features for implementing a Trading PnL (Profit and Loss) Calendar similar to the TopstepX platform.

## 🎯 Key Features

### 1. Calendar Interface & Navigation

- **Monthly View:** A standard 7-day week grid (Sunday to Saturday) representing a full month.
- **Navigation Controls:** Previous/Next month arrows and a "Today" button to quickly jump back to the current date.
- **Current Month/Year Label:** Clear display of the currently viewed month and year (e.g., "Dec 2025").
- **Empty State Handling:** Days outside the current month or without trading data are displayed with a neutral dark background.

### 2. Daily Performance Metrics (The Cells)

- **Dynamic Visual Feedback (Heatmap):**
  - 🟩 **Green Background & Text:** Profitable days (PnL > 0).
  - 🟥 **Red Background & Text:** Unprofitable days (PnL < 0).
  - ⬛ **Neutral Background:** No trading activity.
- **Metric Display:**
  - **Net PnL:** The total profit or loss for the day displayed prominently.
  - **Trade Count:** The number of trades executed that day (e.g., "2 trades").
- **State Highlighting:** Active or selected day has a distinct border (e.g., blue outline) to indicate focus.

### 3. Weekly & Monthly Aggregation

- **Weekly Summary Column:** A dedicated column at the end of the grid (typically the right side) showing:
  - Week label (e.g., "Week 1", "Week 2").
  - Total Net PnL for the week (Green/Red color-coded).
  - Total number of trades for the week.
- **Monthly Summary Header:** An overarching display at the top of the calendar showing the aggregate Monthly PnL.

---

## 🗺️ Implementation Roadmap

### Phase 1: Data Model & State Management (Backend/Logic)

- [ ] **Define Data Structures:** Establish the schema for daily trade aggregates (Date, Total PnL, Number of Trades).
- [ ] **API Endpoint / Data Fetcher:** Create a service or utility to fetch and aggregate monthly PnL data based on the selected month/year.
- [ ] **State Management:** Implement state handling for the currently viewed month, selected date, and the fetched PnL data.

### Phase 2: Core Calendar UI Engine

- [ ] **Grid Generation Logic:** Algorithm to generate the exact grid of days for any given month, including padding days from the previous and next months to maintain a consistent 7-column grid layout.
- [ ] **Base Skeleton:** Build the structural components (HTML/CSS or React/Vue) for the calendar layout (Header, Day Headers, Grid).
- [ ] **Navigation Implementation:** Hook up the Previous, Next, and Today buttons to update the internal state and regenerate the calendar grid.

### Phase 3: Daily & Weekly Cell Rendering

- [ ] **Daily Cell Component:** Create a reusable component for a single day that accepts date, PnL, and trade count as props.
- [ ] **Conditional Styling Logic:** Implement the logic to apply Green/Red/Neutral CSS variables or classes based on the PnL value.
- [ ] **Weekly Summary Calculation:** Add logic to aggregate the daily data per row (week) and render a Weekly Summary cell at the end of each row.

### Phase 4: Polish, Interactions, and Responsiveness

- [ ] **Hover & Selection States:** Add CSS transitions for hovering over days and a highlight border for the currently "selected" day.
- [ ] **Color Palette Integration:** Ensure the specific colors match the system's dark theme (matching the exact dark grey background, muted green, and muted red hues as seen in TopstepX).
- [ ] **Tooltip/Drill-down (Optional Enhancement):** Clicking a day could open a modal or slide-over panel showing the exact individual trades that make up that day's PnL.
- [ ] **Mobile Responsiveness:** Adapt the large grid to remain legible on smaller screens (e.g., potentially allowing horizontal scroll or stacking day cards).
