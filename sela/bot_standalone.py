#!/usr/bin/env python3
"""
Sela — Standalone Telegram Bot (single file, no dependencies on other sela files)
הרצה:
    ANTHROPIC_API_KEY=sk-ant-... python3 bot.py
"""

import asyncio
import json
import logging
import os
import queue
import threading
from datetime import datetime, time
from pathlib import Path

import anthropic
import yfinance as yf
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

# ─── Config ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = "8636112784:AAGkAdJsBIH0TSgpk4Xngq47u_WNYSsUM88"
TELEGRAM_CHAT_ID   = 753995107
DAILY_REPORT_HOUR  = 8          # 08:00 — שנה לשעה שתרצה

WATCHLIST    = ["CVX", "XOM", "LMT", "RTX", "QQQ"]
LUMP_SUM_NIS = 5_000
MONTHLY_NIS  = 1_500
CLAUDE_MODEL = "claude-opus-4-6"
REPORTS_DIR  = Path.home() / "sela" / "reports"

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Claude Tools ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "fetch_stock_data",
        "description": "Fetch current stock price and key metrics via Yahoo Finance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "period": {"type": "string", "enum": ["1d","5d","1mo","3mo"]},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "fetch_sector_etf",
        "description": "Fetch data for a sector ETF (XLE, ITA, QQQ, XLF…).",
        "input_schema": {
            "type": "object",
            "properties": {
                "etf_ticker": {"type": "string"},
            },
            "required": ["etf_ticker"],
        },
    },
]

AGENT_SYSTEMS = {
    "geopolitical": """\
You are the Geopolitical Analyst in an elite investment advisory team.
Specialty: Israel-Middle East nexus, energy corridors, defense budgets.
Current context (April 2026): Israel-Iran tensions; Hormuz disruption risk; NATO budgets elevated.
1. Pull data with fetch_stock_data for each ticker and fetch_sector_etf for XLE and ITA.
2. Give BULLISH/BEARISH/NEUTRAL per stock + one "Socio-Global trigger" sentence.
Be concise and quantitative.""",

    "macro_economist": """\
You are the Macro-Economist in an elite investment advisory team.
Current context (April 2026): US Fed holding at 5.25-5.50%; Middle East GDP ~1.8%; ILS/USD volatile.
1. Pull data with fetch_stock_data and fetch_sector_etf for QQQ and XLF.
2. Give FAVORABLE/UNFAVORABLE/NEUTRAL per stock with macro rationale.
Ground every claim in numbers.""",

    "portfolio_strategist": """\
You are the Portfolio Strategist for Hagay Levenshtein.
Client: age 25, Israeli paramedic, ~23,000 NIS/month.
Savings: ~11,500 NIS Gemel (S&P500) + ~158,000 NIS pension (S&P500).
Available: ~5,000 NIS lump sum, ~1,500 NIS/month. Risk: MEDIUM. Horizon: 5-10 years.
Concern: heavy S&P 500 concentration.
1. Synthesise geo + macro analyses.
2. Use fetch_stock_data to verify prices.
3. Produce ranked BUY/HOLD/SELL list (3-5 stocks) with allocation amounts.
4. Add "Socio-Global trigger" per recommendation and a risk-warning paragraph.
5. Always state this is NOT licensed financial advice.""",
}

# ─── Agent Logic ──────────────────────────────────────────────────────────────

def _stock_data(ticker: str, period: str = "1mo") -> dict:
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        hist  = stock.history(period=period)
        if hist.empty:
            return {"error": f"No history for {ticker}"}
        cur   = float(hist["Close"].iloc[-1])
        start = float(hist["Close"].iloc[0])
        return {
            "ticker": ticker,
            "company_name":    info.get("longName", ticker),
            "current_price":   round(cur, 2),
            "currency":        info.get("currency", "USD"),
            "period_change_pct": round((cur - start) / start * 100, 2),
            "sector":          info.get("sector"),
            "pe_ratio":        info.get("trailingPE"),
            "52w_high":        info.get("fiftyTwoWeekHigh"),
            "52w_low":         info.get("fiftyTwoWeekLow"),
            "analyst_target":  info.get("targetMeanPrice"),
            "dividend_yield":  info.get("dividendYield"),
        }
    except Exception as exc:
        return {"error": str(exc), "ticker": ticker}


def _execute_tool(name: str, inputs: dict) -> str:
    if name == "fetch_stock_data":
        result = _stock_data(inputs["ticker"], inputs.get("period", "1mo"))
    elif name == "fetch_sector_etf":
        result = _stock_data(inputs["etf_ticker"], "1mo")
    else:
        result = {"error": f"Unknown tool: {name}"}
    return json.dumps(result, ensure_ascii=False, default=str)


def _run_agent(agent_name: str, user_prompt: str) -> str:
    client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_prompt}]

    while True:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=AGENT_SYSTEMS[agent_name],
            tools=TOOLS,
            messages=messages,
        )
        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    raw = _execute_tool(block.name, block.input)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": raw,
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user",      "content": results})
        else:
            return "\n".join(b.text for b in response.content if b.type == "text")


def run_round_table_events(stocks, budget_nis=5000, monthly_nis=1500):
    today   = datetime.now().strftime("%B %d, %Y")
    tickers = ", ".join(stocks)

    yield "agent_start", {"agent": "geopolitical", "label": "Geopolitical Analyst"}
    geo = _run_agent(
        "geopolitical",
        f"Date: {today}\nStocks: {tickers}\n"
        "Analyse each ticker geopolitically. Use fetch_stock_data + fetch_sector_etf (XLE, ITA).\n"
        "Conclude with BULLISH/BEARISH/NEUTRAL + Socio-Global trigger.",
    )
    yield "agent_done", {"agent": "geopolitical", "label": "Geopolitical Analyst", "result": geo}

    yield "agent_start", {"agent": "macro", "label": "Macro-Economist"}
    macro = _run_agent(
        "macro_economist",
        f"Date: {today}\nStocks: {tickers}\n"
        "Use fetch_stock_data + fetch_sector_etf (QQQ, XLF).\n"
        f"Geo context:\n{geo[:2000]}\n\nConclude FAVORABLE/UNFAVORABLE/NEUTRAL per stock.",
    )
    yield "agent_done", {"agent": "macro", "label": "Macro-Economist", "result": macro}

    yield "agent_start", {"agent": "portfolio", "label": "Portfolio Strategist"}
    recs = _run_agent(
        "portfolio_strategist",
        f"Date: {today}\nStocks: {tickers}\n"
        f"Lump-sum: {budget_nis:,} NIS | Monthly: {monthly_nis:,} NIS\n\n"
        f"--- GEO ---\n{geo}\n\n--- MACRO ---\n{macro}\n\n"
        "Verify current prices with fetch_stock_data before finalising.",
    )
    yield "agent_done", {"agent": "portfolio", "label": "Portfolio Strategist", "result": recs}

    # assemble report
    report = (
        f"{'='*60}\nSELA — INVESTMENT AGENTS ROUND TABLE\n"
        f"Date: {today} | Tickers: {tickers}\n"
        f"Budget: {budget_nis:,} NIS + {monthly_nis:,} NIS/month\n"
        f"{'='*60}\n\n"
        "DISCLAIMER: AI-generated. NOT licensed financial advice.\n\n"
        f"{'─'*60}\nAGENT 1 — GEOPOLITICAL ANALYST\n{'─'*60}\n{geo}\n\n"
        f"{'─'*60}\nAGENT 2 — MACRO-ECONOMIST\n{'─'*60}\n{macro}\n\n"
        f"{'─'*60}\nAGENT 3 — PORTFOLIO STRATEGIST\n{'─'*60}\n{recs}\n\n"
        f"{'='*60}"
    )
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fname = REPORTS_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    fname.write_text(report, encoding="utf-8")
    logger.info(f"Report saved → {fname}")

    yield "report", {"text": report}


# ─── Telegram Helpers ─────────────────────────────────────────────────────────

AGENT_LABELS = {
    "geopolitical": "🌍 אנליסט גיאופוליטי",
    "macro":        "📊 מאקרו-כלכלן",
    "portfolio":    "💼 אסטרטג תיק ההשקעות",
}


async def _send_chunks(bot, chat_id: int, text: str):
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        try:
            await bot.send_message(chat_id=chat_id, text=f"```\n{chunk}\n```",
                                   parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await bot.send_message(chat_id=chat_id, text=chunk)


async def _run_and_send(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=chat_id, text="⏳ מריץ ניתוח... כ-3 דקות")

    q: queue.Queue = queue.Queue()

    def producer():
        try:
            for item in run_round_table_events(WATCHLIST, LUMP_SUM_NIS, MONTHLY_NIS):
                q.put(item)
        except Exception as exc:
            q.put(("error", {"message": str(exc)}))
        finally:
            q.put(None)

    threading.Thread(target=producer, daemon=True).start()
    loop = asyncio.get_running_loop()
    report_text = ""

    while True:
        item = await loop.run_in_executor(None, q.get)
        if item is None:
            break
        event_type, payload = item

        if event_type == "agent_start":
            label = AGENT_LABELS.get(payload["agent"], payload["label"])
            await context.bot.send_message(chat_id=chat_id, text=f"🔄 {label} מנתח...")
        elif event_type == "agent_done":
            label = AGENT_LABELS.get(payload["agent"], payload["label"])
            await context.bot.send_message(chat_id=chat_id, text=f"✅ {label} סיים")
        elif event_type == "report":
            report_text = payload["text"]
        elif event_type == "error":
            await context.bot.send_message(chat_id=chat_id,
                                           text=f"❌ שגיאה: {payload['message']}")
            return

    if report_text:
        await context.bot.send_message(chat_id=chat_id, text="📄 *דוח Sela:*",
                                       parse_mode=ParseMode.MARKDOWN)
        await _send_chunks(context.bot, chat_id, report_text)
    await context.bot.send_message(chat_id=chat_id, text="🏁 ניתוח הושלם!")


# ─── Commands ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🪨 *Sela — AI Investment Agents*\n\n"
        "שלום הגאי! אני מנתח מניות עבורך כל בוקר.\n\n"
        "/analyze — הרץ ניתוח עכשיו\n"
        "/report — הדוח האחרון\n"
        "/watchlist — רשימת המניות\n"
        "/help — עזרה",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)

async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = ", ".join(f"`{t}`" for t in WATCHLIST)
    await update.message.reply_text(
        f"📋 *מניות:* {tickers}\n"
        f"💰 חד-פעמי: *{LUMP_SUM_NIS:,} ₪*\n"
        f"📅 חודשי: *{MONTHLY_NIS:,} ₪*",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_and_send(update.effective_chat.id, context)

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reports = sorted(REPORTS_DIR.glob("report_*.txt"), reverse=True)
    if not reports:
        await update.message.reply_text("❌ אין דוחות. הרץ /analyze קודם.")
        return
    text = reports[0].read_text(encoding="utf-8")
    await update.message.reply_text(f"📂 *{reports[0].name}*", parse_mode=ParseMode.MARKDOWN)
    await _send_chunks(context.bot, update.effective_chat.id, text)

async def daily_report(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Daily report triggered.")
    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID,
                                   text="🌅 *דוח יומי — Sela*", parse_mode=ParseMode.MARKDOWN)
    await _run_and_send(TELEGRAM_CHAT_ID, context)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not ANTHROPIC_API_KEY:
        raise SystemExit("ERROR: ANTHROPIC_API_KEY is not set")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("analyze",   cmd_analyze))
    app.add_handler(CommandHandler("report",    cmd_report))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))

    app.job_queue.run_daily(
        daily_report,
        time=time(hour=DAILY_REPORT_HOUR, minute=0),
        chat_id=TELEGRAM_CHAT_ID,
    )

    logger.info(f"🪨 Sela bot running — daily report at {DAILY_REPORT_HOUR:02d}:00")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
