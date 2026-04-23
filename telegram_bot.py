#!/usr/bin/env python3
"""
telegram_bot.py — Run the flight search and deliver results to a Telegram chat.

Designed to be triggered by a cron job (see run_daily.sh).
Departure date defaults to DEFAULT_DEPART_DAYS from today (set in .env).

Usage:
    python telegram_bot.py
    python telegram_bot.py --depart 2026-05-10 --return 2026-05-17
    python telegram_bot.py --max-price 70000
"""

import os
import sys
import argparse
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flight_tracker import run_search, CITY_PROFILES, EUR_PER_INR

load_dotenv()

BOT_TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID            = os.getenv("TELEGRAM_CHAT_ID", "").strip()
DEFAULT_DEPART_DAYS = int(os.getenv("DEFAULT_DEPART_DAYS", "30"))
DEFAULT_TRIP_DAYS   = int(os.getenv("DEFAULT_TRIP_DAYS",   "7"))


# ── Telegram helpers ───────────────────────────────────────────────────────────

def send(text):
    """Send one HTML-formatted message to Telegram (max 4096 chars)."""
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env", file=sys.stderr)
        sys.exit(1)
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    resp.raise_for_status()


def send_long(text, max_len=4000):
    """Split text into chunks and send each as a separate message."""
    lines  = text.split("\n")
    chunk  = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > max_len:
            send(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        send(chunk)


# ── Message formatters ─────────────────────────────────────────────────────────

def fmt_summary(flight_data, depart_date, return_date):
    priced = [d for d in flight_data if d["price_inr"]]
    if not priced:
        return (
            "✈ <b>Daily Flight Deals — DEL → Europe</b>\n"
            f"📅 {depart_date}  →  {return_date}\n\n"
            "⚠️ No prices fetched. Check your <code>RAPIDAPI_KEY</code> in .env."
        )
    cheapest = min(priced, key=lambda x: x["price_inr"])
    avg_inr  = int(sum(d["price_inr"] for d in priced) / len(priced))
    return (
        "✈ <b>Daily Flight Deals — DEL → Europe</b>\n"
        f"📅 {depart_date}  →  {return_date}\n"
        f"🌡 Only cities below 25°C shown\n\n"
        f"🏆 <b>Cheapest:</b> {cheapest['city']} — <b>{cheapest['price_formatted']}</b>"
        f"  (~€{int(cheapest['price_inr'] / EUR_PER_INR):,})\n"
        f"📊 <b>Average price:</b> ₹{avg_inr:,}  (~€{int(avg_inr / EUR_PER_INR):,})\n"
        f"📍 <b>{len(priced)}</b> destinations with live prices"
    )


def fmt_deals(flight_data):
    priced = sorted([d for d in flight_data if d["price_inr"]], key=lambda x: x["price_inr"])
    if not priced:
        return ""

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines  = ["<b>🗺 Ranked Flight Deals (cheapest first):</b>\n"]
    for i, d in enumerate(priced, 1):
        eur    = int(d["price_inr"] / EUR_PER_INR)
        prefix = medals.get(i, f"{i}.")
        dur    = d["flight_duration"] or "N/A"
        lines.append(
            f"{prefix} <b>{d['city']}</b> ({d['iata']})  —  <b>{d['price_formatted']}</b> (~€{eur})\n"
            f"    🌡 {d['temperature_c']}°C  |  ✈ {d['airline']}  |  ⏱ {dur}\n"
        )
    return "\n".join(lines)


def fmt_top_picks(flight_data):
    priced = sorted([d for d in flight_data if d["price_inr"]], key=lambda x: x["price_inr"])
    top3   = priced[:3]
    if not top3:
        return ""

    medals = ["🥇", "🥈", "🥉"]
    lines  = ["<b>⭐ Top 3 Best-Value Picks:</b>\n"]
    for medal, d in zip(medals, top3):
        _, vibe = CITY_PROFILES.get(d["city"], ("", "great European destination"))
        eur     = int(d["price_inr"] / EUR_PER_INR)
        lines.append(
            f"{medal} <b>{d['city']}</b>  —  {d['price_formatted']} (~€{eur})\n"
            f"    🌡 {d['temperature_c']}°C  |  ✈ {d['airline']}\n"
            f"    <i>{vibe}</i>\n"
        )

    # Best per traveler type
    lines.append("\n<b>Best for each traveler:</b>")
    for ttype, label, icon in (
        ("budget",  "Budget",  "💰"),
        ("culture", "Culture", "🏛"),
        ("nature",  "Nature",  "🌲"),
    ):
        pool = [d for d in priced if CITY_PROFILES.get(d["city"], ("",))[0] == ttype]
        if pool:
            lines.append(f"{icon} <b>{label}:</b> {pool[0]['city']}  —  {pool[0]['price_formatted']}")

    lines.append(
        "\n💡 <i>Use Skyscanner's \"Cheapest month\" view to find even better dates.</i>"
    )
    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Flight tracker → Telegram bot")
    parser.add_argument("--depart",    help="Departure date YYYY-MM-DD (default: today + DEFAULT_DEPART_DAYS)")
    parser.add_argument("--return",    dest="return_date", help="Return date YYYY-MM-DD")
    parser.add_argument("--max-price", type=int, help="Max price in INR")
    args = parser.parse_args()

    today       = datetime.today()
    depart_date = args.depart or (today + timedelta(days=DEFAULT_DEPART_DAYS)).strftime("%Y-%m-%d")
    return_date = args.return_date or (
        datetime.strptime(depart_date, "%Y-%m-%d") + timedelta(days=DEFAULT_TRIP_DAYS)
    ).strftime("%Y-%m-%d")

    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Running search: {depart_date} → {return_date}")

    results     = run_search(depart_date, return_date, args.max_price)
    flight_data = results.get("flight_data", [])

    priced_count = sum(1 for d in flight_data if d["price_inr"])
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Prices found for {priced_count}/{len(flight_data)} destinations. Sending to Telegram...")

    # Send in 3 separate messages so nothing gets cut off
    send(fmt_summary(flight_data, depart_date, return_date))
    if flight_data:
        deals_text = fmt_deals(flight_data)
        if deals_text:
            send_long(deals_text)
        picks_text = fmt_top_picks(flight_data)
        if picks_text:
            send(picks_text)

    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Done. Messages sent to Telegram.")


if __name__ == "__main__":
    main()
