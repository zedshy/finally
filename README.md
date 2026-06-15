# FinAlly — AI Trading Workstation

A visually stunning AI-powered trading workstation with live market data, simulated portfolio trading, and an LLM chat assistant that can analyze positions and execute trades on your behalf. Think Bloomberg terminal with an AI copilot.

Built as the capstone project for an agentic AI coding course — constructed entirely by orchestrated AI coding agents.

## What It Does

- **Live price streaming** — prices flash green/red on every tick via SSE
- **Simulated portfolio** — start with $10,000 virtual cash, buy and sell at market price instantly
- **Portfolio visualizations** — treemap heatmap by P&L weight, P&L chart over time, positions table
- **AI chat assistant** — ask questions, get analysis, have the AI execute trades and manage your watchlist via natural language
- **Watchlist management** — add/remove tickers manually or through the AI

## Architecture

Single Docker container, single port (8000):

- **Frontend**: Next.js (TypeScript), static export served by FastAPI
- **Backend**: FastAPI (Python/uv)
- **Database**: SQLite — zero config, auto-initialized on first run
- **Real-time**: Server-Sent Events (`/api/stream/prices`)
- **AI**: LiteLLM → OpenRouter (Cerebras inference) with structured outputs
- **Market data**: GBM simulator by default; Polygon.io REST API if `MASSIVE_API_KEY` is set

## Quick Start (Current State)

The full app (Docker container, backend API, frontend, AI chat) is still under construction — see Development Status below. The market data module is complete and can be explored directly:

```bash
cd backend
uv sync
uv run market_data_demo.py   # live terminal demo with sparklines and event log
uv run pytest                 # run the test suite
```

## Environment Variables

Planned configuration for the full app (not yet wired up):

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | For LLM chat (OpenRouter) |
| `MASSIVE_API_KEY` | No | Polygon.io key for real market data; omit to use the simulator |
| `LLM_MOCK` | No | Set `true` for deterministic mock responses (E2E tests) |

## Development Status

| Component | Status |
|---|---|
| Market data (simulator + Polygon.io) | Complete — 73 tests, 84% coverage |
| Backend API & database | In progress |
| Frontend UI | In progress |
| Docker & deployment | In progress |
| E2E tests | In progress |
