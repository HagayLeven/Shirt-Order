#!/usr/bin/env python3
"""
Sela — Investment Agents core logic.

Exposes:
    run_round_table(stocks, budget_nis, monthly_nis) -> str
        Blocking call; prints progress and returns the full report.

    run_round_table_events(stocks, budget_nis, monthly_nis) -> Iterator
        Generator; yields (event_type, payload_dict) pairs for SSE streaming.

Usage (CLI):
    export ANTHROPIC_API_KEY=sk-ant-...
    python agents.py
"""

import json
from datetime import datetime

import anthropic
import yfinance as yf

import config

# ─── Client & Model ──────────────────────────────────────────────────────────

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from environment
MODEL = config.CLAUDE_MODEL

# ─── Tool Definitions ────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "fetch_stock_data",
        "description": (
            "Fetch current stock price, recent performance and key financial "
            "metrics for a given ticker symbol using Yahoo Finance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": (
                        "Stock ticker symbol "
                        "(e.g. AAPL, LMT, ESLT.TA for Tel-Aviv)"
                    ),
                },
                "period": {
                    "type": "string",
                    "description": "Time period for price history",
                    "enum": ["1d", "5d", "1mo", "3mo"],
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "fetch_sector_etf",
        "description": (
            "Fetch data for a sector ETF to understand broad sector performance. "
            "E.g. XLE=Energy, ITA=Aerospace-Defense, QQQ=Nasdaq-100, XLF=Financials."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "etf_ticker": {
                    "type": "string",
                    "description": "ETF ticker symbol",
                }
            },
            "required": ["etf_ticker"],
        },
    },
]

# ─── Tool Implementations ────────────────────────────────────────────────────


def _stock_data(ticker: str, period: str = "1mo") -> dict:
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period=period)

        if hist.empty:
            return {"error": f"No price history found for {ticker}"}

        current = float(hist["Close"].iloc[-1])
        start = float(hist["Close"].iloc[0])
        change_pct = round((current - start) / start * 100, 2)

        return {
            "ticker": ticker,
            "company_name": info.get("longName", ticker),
            "current_price": round(current, 2),
            "currency": info.get("currency", "USD"),
            "period_change_pct": change_pct,
            "sector": info.get("sector"),
            "market_cap_usd": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "analyst_target": info.get("targetMeanPrice"),
            "dividend_yield": info.get("dividendYield"),
        }
    except Exception as exc:
        return {"error": str(exc), "ticker": ticker}


def execute_tool(name: str, inputs: dict) -> str:
    if name == "fetch_stock_data":
        result = _stock_data(inputs["ticker"], inputs.get("period", "1mo"))
    elif name == "fetch_sector_etf":
        result = _stock_data(inputs["etf_ticker"], "1mo")
    else:
        result = {"error": f"Unknown tool: {name}"}
    return json.dumps(result, ensure_ascii=False, default=str)


# ─── Agent System Prompts ────────────────────────────────────────────────────

AGENT_SYSTEMS = {
    "geopolitical": """\
You are the Geopolitical Analyst in an elite investment advisory team.

Specialty: mapping how geopolitical events (wars, sanctions, ceasefire talks,
trade routes, energy corridors) translate into equity price movements — with
special focus on the Israel-Middle East nexus.

Current context (April 2026):
- Israel-Iran tensions persist; ceasefire negotiations are ongoing.
- Strait of Hormuz remains a critical oil-supply choke-point.
- TA-125 index near 4,294 pts. Defense budgets elevated across NATO and Israel.
- Brent crude spiked on supply-disruption fears.

Your job:
1. Pull current data with fetch_stock_data for each ticker assigned to you.
2. Pull sector context using fetch_sector_etf (XLE for energy, ITA for defense).
3. For each stock give a BULLISH / BEARISH / NEUTRAL geo-political rating
   with a one-sentence "Socio-Global trigger" explaining the driver.
4. Be concise and quantitative — cite price levels where relevant.
""",
    "macro_economist": """\
You are the Macro-Economist in an elite investment advisory team.

Specialty: translating CPI prints, rate decisions, GDP readings and FX moves
into sector-level and stock-level investment implications.

Current context (April 2026):
- US Fed holding rates after the 2024-2025 hiking cycle.
- Middle East GDP growth slowing to ~1.8 %.
- ILS/USD volatility affecting Israeli exporter margins.
- Global tech sector in a post-correction recovery phase.

Your job:
1. Pull current data with fetch_stock_data for each ticker assigned to you.
2. Pull sector context via fetch_sector_etf (QQQ for tech, XLF for financials).
3. For each stock give a FAVORABLE / UNFAVORABLE / NEUTRAL macro rating
   with a brief rationale citing at least one macro indicator.
4. Ground every claim in numbers.
""",
    "portfolio_strategist": """\
You are the Portfolio Strategist for Hagay Levenshtein.

Client profile:
- Age: 25, Israeli paramedic and student.
- Monthly salary: ~23,000 NIS (net).
- Existing savings:
    * ~11,500 NIS in Gemel Lehashkaa (100 % S&P 500 track).
    * ~158,000 NIS in pension fund (100 % S&P 500 track).
- Available for deployment NOW: ~5,000-7,000 NIS lump sum.
- Monthly standing order capacity: ~1,500 NIS.
- Risk profile: MEDIUM (can absorb volatility, not speculative).
- Time horizon: 5-10 + years.
- Key concern: heavy concentration in S&P 500; wants diversification.

Your job:
1. Synthesise the Geopolitical and Macro analyses provided to you.
2. Use fetch_stock_data to verify the latest prices before finalising calls.
3. Produce a ranked BUY / HOLD / SELL list of 3-5 stocks.
4. For each BUY: suggest how much of the lump sum to allocate and whether
   to include it in the monthly standing order.
5. Add one "Socio-Global trigger" sentence per recommendation.
6. Close with a risk-warning paragraph tailored to Hagay's profile.
7. Always remind the reader that AI analysis is NOT licensed financial advice.
""",
}

# ─── Single-Agent Runner ─────────────────────────────────────────────────────


def run_agent(agent_name: str, user_prompt: str) -> str:
    """Run one agent in a tool-use loop. Returns the final assistant text."""
    messages = [{"role": "user", "content": user_prompt}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=AGENT_SYSTEMS[agent_name],
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    raw = execute_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": raw,
                        }
                    )
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            return "\n".join(
                block.text for block in response.content if block.type == "text"
            )


# ─── Report Assembly ─────────────────────────────────────────────────────────


def _assemble_report(
    geo: str,
    macro: str,
    recommendations: str,
    stocks: list,
    budget_nis: int,
    monthly_nis: int,
) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    tickers = ", ".join(stocks)
    return (
        f"{'='*60}\n"
        f"SELA — INVESTMENT AGENTS ROUND TABLE REPORT\n"
        f"Date: {today}\n"
        f"Tickers: {tickers}\n"
        f"Budget: {budget_nis:,} NIS lump-sum + {monthly_nis:,} NIS/month\n"
        f"{'='*60}\n\n"
        "DISCLAIMER: This report is generated by an AI system and does NOT\n"
        "constitute licensed financial advice. Consult a certified financial\n"
        "advisor before making any investment decisions.\n\n"
        f"{'─'*60}\n"
        "AGENT 1 — GEOPOLITICAL ANALYST\n"
        f"{'─'*60}\n"
        f"{geo}\n\n"
        f"{'─'*60}\n"
        "AGENT 2 — MACRO-ECONOMIST\n"
        f"{'─'*60}\n"
        f"{macro}\n\n"
        f"{'─'*60}\n"
        "AGENT 3 — PORTFOLIO STRATEGIST (Hagay's Recommendations)\n"
        f"{'─'*60}\n"
        f"{recommendations}\n\n"
        f"{'='*60}"
    )


# ─── SSE-Friendly Events Generator ───────────────────────────────────────────


def run_round_table_events(
    stocks: list,
    budget_nis: int = 5000,
    monthly_nis: int = 1500,
):
    """
    Generator that drives the full round table and yields SSE-ready events.

    Each yield is a tuple:  (event_type: str, payload: dict)

    Event types:
        agent_start  {"agent": "geopolitical"|"macro"|"portfolio", "label": str}
        agent_done   {"agent": ..., "label": ..., "result": str}
        report       {"text": str}
    """
    today = datetime.now().strftime("%B %d, %Y")
    tickers = ", ".join(stocks)

    # ── Agent 1: Geopolitical ────────────────────────────────────────────────
    yield "agent_start", {"agent": "geopolitical", "label": "Geopolitical Analyst"}

    geo = run_agent(
        "geopolitical",
        f"Date: {today}\nStocks to analyse: {tickers}\n\n"
        "Analyse each ticker from a geopolitical perspective.\n"
        "Use fetch_stock_data on each ticker and fetch_sector_etf for XLE and ITA.\n"
        'Conclude with a BULLISH/BEARISH/NEUTRAL rating per stock plus its "Socio-Global trigger" sentence.',
    )
    yield "agent_done", {"agent": "geopolitical", "label": "Geopolitical Analyst", "result": geo}

    # ── Agent 2: Macro-Economist ─────────────────────────────────────────────
    yield "agent_start", {"agent": "macro", "label": "Macro-Economist"}

    macro = run_agent(
        "macro_economist",
        f"Date: {today}\nStocks to analyse: {tickers}\n\n"
        "Use fetch_stock_data on each ticker and fetch_sector_etf for QQQ and XLF.\n"
        "Your geopolitical colleague's analysis (for background context):\n\n"
        f"--- GEO ---\n{geo[:2000]}\n---\n\n"
        "Conclude with a FAVORABLE/UNFAVORABLE/NEUTRAL macro rating per stock.",
    )
    yield "agent_done", {"agent": "macro", "label": "Macro-Economist", "result": macro}

    # ── Agent 3: Portfolio Strategist ────────────────────────────────────────
    yield "agent_start", {"agent": "portfolio", "label": "Portfolio Strategist"}

    recommendations = run_agent(
        "portfolio_strategist",
        f"Date: {today}\nStocks: {tickers}\n"
        f"Lump-sum: {budget_nis:,} NIS  |  Monthly: {monthly_nis:,} NIS\n\n"
        "--- GEOPOLITICAL ANALYSIS ---\n" + geo + "\n\n"
        "--- MACRO ANALYSIS ---\n" + macro + "\n\n"
        "Use fetch_stock_data to verify current prices before finalising recommendations.",
    )
    yield "agent_done", {"agent": "portfolio", "label": "Portfolio Strategist", "result": recommendations}

    # ── Final Report ─────────────────────────────────────────────────────────
    report = _assemble_report(geo, macro, recommendations, stocks, budget_nis, monthly_nis)
    yield "report", {"text": report}


# ─── Blocking CLI Entry Point ─────────────────────────────────────────────────


def run_round_table(stocks: list, budget_nis: int = 5000, monthly_nis: int = 1500) -> str:
    """Blocking wrapper around run_round_table_events for CLI use."""
    labels = {
        "geopolitical": "Agent 1 (Geopolitical Analyst)",
        "macro": "Agent 2 (Macro-Economist)",
        "portfolio": "Agent 3 (Portfolio Strategist)",
    }
    report = ""
    print(f"\n{'='*60}\n  SELA — INVESTMENT AGENTS ROUND TABLE\n{'='*60}\n")

    for event_type, payload in run_round_table_events(stocks, budget_nis, monthly_nis):
        if event_type == "agent_start":
            print(f"{labels[payload['agent']]} is analysing …")
        elif event_type == "agent_done":
            print(f"  → {labels[payload['agent']]} complete.\n")
        elif event_type == "report":
            report = payload["text"]

    return report


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os

    report = run_round_table(
        stocks=config.WATCHLIST,
        budget_nis=config.LUMP_SUM_NIS,
        monthly_nis=config.MONTHLY_NIS,
    )

    print(report)

    if config.SAVE_REPORT:
        os.makedirs(config.REPORTS_DIR, exist_ok=True)
        filename = os.path.join(
            config.REPORTS_DIR,
            f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
        )
        with open(filename, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"\nReport saved → {filename}")
