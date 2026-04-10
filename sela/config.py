"""
User-editable configuration for the Investment Agents round table.
Edit the values here — no need to touch agents.py.
"""

# ─── Investor Profile ────────────────────────────────────────────────────────

INVESTOR = {
    "name": "Hagay Levenshtein",
    "age": 25,
    "monthly_salary_nis": 23_000,
    "risk_profile": "medium",   # low | medium | high
    "time_horizon_years": 10,
}

# ─── Budget ───────────────────────────────────────────────────────────────────

LUMP_SUM_NIS = 5_000       # one-time investment available now
MONTHLY_NIS  = 1_500       # standing-order amount per month

# ─── Watchlist ───────────────────────────────────────────────────────────────
# Add or remove tickers freely.
# Israeli stocks (TASE) require the ".TA" suffix, e.g. "ESLT.TA", "NWMD.TA".

WATCHLIST = [
    "CVX",      # Chevron         — US energy; Hormuz / oil-supply play
    "XOM",      # ExxonMobil      — oil geopolitics
    "LMT",      # Lockheed Martin — defense / aerospace
    "RTX",      # Raytheon        — defense / missiles
    "QQQ",      # Nasdaq-100 ETF  — tech-recovery proxy
    # "ESLT.TA",  # Elbit Systems   — Israeli defense prime
    # "NWMD.TA",  # NewMed Energy   — Israeli natural gas
]

# ─── Model ───────────────────────────────────────────────────────────────────

CLAUDE_MODEL = "claude-opus-4-6"   # change to "claude-sonnet-4-6" to reduce cost

# ─── Output ──────────────────────────────────────────────────────────────────

SAVE_REPORT = True          # write report to a timestamped .txt file
REPORTS_DIR = "reports"     # subdirectory for saved reports (created if absent)

# ─── Telegram Bot ─────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = "8636112784:AAGkAdJsBIH0TSgpk4Xngq47u_WNYSsUM88"
TELEGRAM_CHAT_ID   = 753995107
DAILY_REPORT_HOUR  = 8    # 08:00 — שנה אם תרצה שעה אחרת
