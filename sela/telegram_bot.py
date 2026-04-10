#!/usr/bin/env python3
"""
Sela — Telegram Bot
שולח דוח ניתוח יומי ומגיב לפקודות.

פקודות:
    /start      — ברוך הבא
    /analyze    — הרץ ניתוח עכשיו
    /report     — הדוח האחרון שנשמר
    /watchlist  — רשימת המניות הנוכחית
    /help       — עזרה

הפעלה:
    export ANTHROPIC_API_KEY=sk-ant-...
    python telegram_bot.py
"""

import asyncio
import logging
import os
import queue
import sys
import threading
from datetime import time
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

sys.path.insert(0, os.path.dirname(__file__))
import config
from agents import run_round_table_events

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN)
CHAT_ID    = int(os.environ.get("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT_ID))

AGENT_LABELS = {
    "geopolitical": "🌍 אנליסט גיאופוליטי",
    "macro":        "📊 מאקרו-כלכלן",
    "portfolio":    "💼 אסטרטג תיק ההשקעות",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _send_chunks(bot, chat_id: int, text: str):
    """שולח טקסט ארוך בנתחים של 4000 תווים."""
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"```\n{chunk}\n```",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            await bot.send_message(chat_id=chat_id, text=chunk)


async def _run_analysis_and_send(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """מריץ ניתוח מלא ושולח עדכונים בזמן אמת."""
    await context.bot.send_message(
        chat_id=chat_id,
        text="⏳ מריץ ניתוח מלא... כ-3 דקות",
    )

    # מריץ את הגנרטור הסינכרוני בthread נפרד ומתקשר דרך queue
    event_queue: queue.Queue = queue.Queue()

    def producer():
        try:
            for item in run_round_table_events(
                config.WATCHLIST, config.LUMP_SUM_NIS, config.MONTHLY_NIS
            ):
                event_queue.put(item)
        except Exception as exc:
            event_queue.put(("error", {"message": str(exc)}))
        finally:
            event_queue.put(None)  # sentinel

    thread = threading.Thread(target=producer, daemon=True)
    thread.start()

    loop = asyncio.get_running_loop()
    report_text = ""

    while True:
        item = await loop.run_in_executor(None, event_queue.get)
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
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ שגיאה: {payload['message']}",
            )
            return

    if report_text:
        await context.bot.send_message(chat_id=chat_id, text="📄 *דוח Sela:*", parse_mode=ParseMode.MARKDOWN)
        await _send_chunks(context.bot, chat_id, report_text)
        await context.bot.send_message(chat_id=chat_id, text="🏁 ניתוח הושלם!")
    else:
        await context.bot.send_message(chat_id=chat_id, text="❌ לא התקבל דוח.")


# ─── Command Handlers ────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🪨 *Sela — AI Investment Agents*\n\n"
        "שלום הגאי! אני מנתח מניות עבורך כל יום.\n\n"
        "*פקודות זמינות:*\n"
        "/analyze — הרץ ניתוח מיידי\n"
        "/report — הדוח האחרון שנשמר\n"
        "/watchlist — רשימת המניות\n"
        "/help — עזרה"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = ", ".join(f"`{t}`" for t in config.WATCHLIST)
    text = (
        f"📋 *רשימת מניות:*\n{tickers}\n\n"
        f"💰 תקציב חד-פעמי: *{config.LUMP_SUM_NIS:,} ₪*\n"
        f"📅 חודשי: *{config.MONTHLY_NIS:,} ₪/חודש*"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_analysis_and_send(update.effective_chat.id, context)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reports_dir = Path(__file__).parent / config.REPORTS_DIR
    reports = sorted(reports_dir.glob("report_*.txt"), reverse=True)

    if not reports:
        await update.message.reply_text(
            "❌ אין דוחות שמורים. הרץ /analyze קודם."
        )
        return

    latest = reports[0]
    text = latest.read_text(encoding="utf-8")
    await update.message.reply_text(
        f"📂 *דוח אחרון:* `{latest.name}`", parse_mode=ParseMode.MARKDOWN
    )
    await _send_chunks(context.bot, update.effective_chat.id, text)


# ─── Daily Job ───────────────────────────────────────────────────────────────


async def daily_report(context: ContextTypes.DEFAULT_TYPE):
    """מופעל אוטומטית כל יום בשעה DAILY_REPORT_HOUR:00."""
    logger.info("Running scheduled daily report...")
    await context.bot.send_message(
        chat_id=CHAT_ID,
        text="🌅 *דוח יומי — Sela*\nמריץ ניתוח...",
        parse_mode=ParseMode.MARKDOWN,
    )
    await _run_analysis_and_send(CHAT_ID, context)


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN לא מוגדר")
    if not CHAT_ID:
        raise ValueError("TELEGRAM_CHAT_ID לא מוגדר")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("analyze",   cmd_analyze))
    app.add_handler(CommandHandler("report",    cmd_report))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))

    # דוח יומי אוטומטי
    app.job_queue.run_daily(
        daily_report,
        time=time(hour=config.DAILY_REPORT_HOUR, minute=0),
        chat_id=CHAT_ID,
    )

    logger.info(f"Sela bot is running. Daily report at {config.DAILY_REPORT_HOUR:02d}:00.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
