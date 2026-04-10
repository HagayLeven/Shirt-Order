#!/usr/bin/env python3
"""
Investment Agents - Multi-agent socio-economic stock analysis system.
Three specialized Claude agents hold a "round table" to produce
Buy/Hold/Sell recommendations for Hagay Levenshtein.

Requirements:
    pip install -r requirements.txt

Usage:
    export ANTHROPIC_API_KEY=your_api_key
    python agents.py
"""

import json
import os
from datetime import datetime

import anthropic
import yfinance as yf

# ─── Client & Model ──────────────────────────────────────────────────────────

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from environment
MODEL = "claude-opus-4-6"

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
    """Pull data from Yahoo Finance and return a compact summary dict."""
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
            "avg_volume": info.get("averageVolume"),
        }
    except Exception as exc:
        return {"error": str(exc), "ticker": ticker}


def execute_tool(name: str, inputs: dict) -> str:
    """Route Claude's tool-use request to the appropriate implementation."""
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
4. For each BUY: suggest how much of the 5,000 NIS lump sum to allocate
   and whether to include it in the 1,500 NIS/month standing order.
5. Add one "Socio-Global trigger" sentence per recommendation.
6. Close with a risk-warning paragraph tailored to Hagay's profile.
7. Always remind the reader that AI analysis is NOT licensed financial advice.
""",
}


# ─── Single-Agent Runner ─────────────────────────────────────────────────────


def run_agent(agent_name: str, user_prompt: str) -> str:
    """
    Run one agent in a tool-use loop until it reaches end_turn.
    Returns the final assistant text.
    """
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


# ─── Round-Table Orchestrator ────────────────────────────────────────────────


def run_round_table(
    stocks: list,
    budget_nis: int = 5000,
    monthly_nis: int = 1500,
) -> str:
    """
    Orchestrate the three-agent round table.

    Args:
        stocks:      Ticker symbols to analyse (e.g. ["CVX", "LMT", "QQQ"]).
        budget_nis:  One-time lump-sum budget in NIS.
        monthly_nis: Monthly standing-order amount in NIS.

    Returns:
        Full formatted report string.
    """
    today = datetime.now().strftime("%B %d, %Y")
    tickers = ", ".join(stocks)

    print(f"\n{'='*60}")
    print(f"  INVESTMENT AGENTS ROUND TABLE — {today}")
    print(f"{'='*60}\n")

    # ── Agent 1: Geopolitical Analyst ─────────────────────────────────────
    print("Agent 1 (Geopolitical Analyst) is analysing …")
    geo_prompt = f"""\
Date: {today}
Stocks to analyse: {tickers}

Please analyse each ticker from a geopolitical perspective.
Use fetch_stock_data on each ticker and fetch_sector_etf for XLE and ITA.
Conclude with a BULLISH/BEARISH/NEUTRAL rating per stock plus its
"Socio-Global trigger" sentence."""

    geo = run_agent("geopolitical", geo_prompt)
    print("  → Geopolitical analysis complete.\n")

    # ── Agent 2: Macro-Economist ───────────────────────────────────────────
    print("Agent 2 (Macro-Economist) is analysing …")
    macro_prompt = f"""\
Date: {today}
Stocks to analyse: {tickers}

Use fetch_stock_data on each ticker and fetch_sector_etf for QQQ and XLF.
Your geopolitical colleague has already produced this analysis — use it
as background context but form your own macro-driven view:

--- GEOPOLITICAL ANALYSIS (for reference) ---
{geo[:2000]}
--- END ---

Conclude with a FAVORABLE/UNFAVORABLE/NEUTRAL macro rating per stock."""

    macro = run_agent("macro_economist", macro_prompt)
    print("  → Macro-economic analysis complete.\n")

    # ── Agent 3: Portfolio Strategist ─────────────────────────────────────
    print("Agent 3 (Portfolio Strategist) is preparing Hagay's recommendations …")
    portfolio_prompt = f"""\
Date: {today}
Stocks analysed: {tickers}
Lump-sum budget: {budget_nis:,} NIS   |   Monthly: {monthly_nis:,} NIS

Below are the two specialist analyses. Synthesise them into an
actionable recommendation table for Hagay:

--- GEOPOLITICAL ANALYSIS ---
{geo}

--- MACRO ANALYSIS ---
{macro}

Use fetch_stock_data to verify current prices before finalising
your Buy/Hold/Sell calls and NIS allocations."""

    recommendations = run_agent("portfolio_strategist", portfolio_prompt)
    print("  → Portfolio recommendations ready.\n")

    # ── Assemble Report ────────────────────────────────────────────────────
    report = f"""
{'='*60}
INVESTMENT AGENTS ROUND TABLE REPORT
Date: {today}
Tickers: {tickers}
Budget: {budget_nis:,} NIS lump-sum + {monthly_nis:,} NIS/month
{'='*60}

DISCLAIMER: This report is generated by an AI system and does NOT
constitute licensed financial advice. Consult a certified financial
advisor before making any investment decisions.

{'─'*60}
AGENT 1 — GEOPOLITICAL ANALYST
{'─'*60}
{geo}

{'─'*60}
AGENT 2 — MACRO-ECONOMIST
{'─'*60}
{macro}

{'─'*60}
AGENT 3 — PORTFOLIO STRATEGIST (Hagay's Recommendations)
{'─'*60}
{recommendations}

{'='*60}
"""
    return report


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Default watchlist — edit to taste
    watchlist = [
        "CVX",   # Chevron — US energy major; Hormuz / oil-supply play
        "XOM",   # ExxonMobil — oil geopolitics
        "LMT",   # Lockheed Martin — defense/aerospace
        "RTX",   # Raytheon Technologies — defense/missiles
        "QQQ",   # Nasdaq-100 ETF — tech-recovery proxy
    ]

    # Israeli listings require the ".TA" suffix, e.g.:
    #   "ESLT.TA"  — Elbit Systems (Israeli defense prime)
    #   "NWMD.TA"  — NewMed Energy (Israeli natural gas)

    report = run_round_table(
        stocks=watchlist,
        budget_nis=5000,
        monthly_nis=1500,
    )

    print(report)

    # Save to a timestamped file
    filename = f"investment_report_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    with open(filename, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(f"Report saved → {filename}")
