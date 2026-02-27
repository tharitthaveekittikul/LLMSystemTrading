# Roadmap: AI-Integrated Multi-Account Trading Framework

## Phase 1: Infrastructure & Data Ingestion

- [ ] **MT5 Portable Setup**: Install and configure multiple MT5 portable instances (`/portable` flag).
- [ ] **Data Ingestion/Gateway Service**: Create a Python service to connect to specific MT5 instances using the `MetaTrader5` library.
- [ ] **Context Engine (News/Macro)**: Integrate external APIs (e.g., FinancialModelingPrep, AlphaVantage, ForexFactory) for macroeconomic calendars and news sentiment.
- [ ] **Database Setup**: Set up PostgreSQL for the Strategy & Account Binding Table, trade logging, and historical data storage.

## Phase 2: Core Trading Engine

- [ ] **Standardized Signal Interface**: Define the core `Signal` object schema (`{action: BUY/SELL, confidence: 0.0-1.0, sl: price, tp: price, reason: text}`).
- [ ] **Hard-coded Risk Management Layer**: Implement a risk guardrail that validates all signals before execution (max drawdown limits, max open positions, margin check).
- [ ] **Executor Service**: Implement the module that receives validated signals and routes them to the correct MT5 account via `mt5.order_send()`.
- [ ] **Baseline Strategy Plugin**: Implement a simple Python strategy (e.g., custom indicator) to test the end-to-end execution pipeline.

## Phase 3: AI/LLM Integration

- [ ] **LLM Strategy Plugin**: Develop the Multi-Agent Loop (Analyst, Strategist, Executor).
- [ ] **Prompt Engineering & Context Aggregation**: Design prompts that effectively combine MT5 OHLCV data with "Market Regime" reports and macro news.
- [ ] **LLM State Management**: Implement a mechanism for the LLM to remember its current open positions and recent rationale so it doesn't trade amnesiacally.
- [ ] **Paper Trading / Forward Testing**: Deploy the LLM strategy on an isolated MT5 Demo account for safety validation.

## Phase 4: Management UI & Backtesting Suite

- [ ] **Unified Management Dashboard**: Build a web interface (Streamlit, FastAPI + React/Next.js) to monitor the system.
- [ ] **Strategy Configuration UI**: Create the UI capability to bind strategies to specific accounts, adjust Risk Multipliers, and toggle Status (Live/Forward Test/Paused).
- [ ] **Market Simulator (Backtesting Engine)**: Develop a unified historical environment that mocks the `MetaTrader5` library.
- [ ] **LLM Replay Mode**: Implement the loop to feed historical data slices to the LLM ("It is Jan 5th...") and evaluate performance.
- [ ] **Vector Database (Optional)**: Integrate a Vector DB to store and search historical news correlations for the LLM.

## Phase 5: Production Deployment & Observability

- [ ] **Containerization**: Create Docker/Docker-compose setups for the Agentic workflows, Database, and web dashboard.
- [ ] **Cloud Deployment**: Deploy the supporting microservices to a reliable VPS (MT5 instances typically require Windows VPS).
- [ ] **Logging & Alerting**: Integrate real-time notifications (e.g., Telegram, Discord) for executed trades, significant errors, or API limits.
