#!/usr/bin/env python3
"""
flight_tracker.py — One-shot European flight price tracker from Delhi (DEL).

Fetches current temperatures for 28 European cities via Open-Meteo (free, no key),
keeps only destinations below 25°C, searches flight prices from DEL via Skyscanner
and an optional second RapidAPI source, then uses Claude AI to produce a ranked
travel report in a single run.

Usage:
    python flight_tracker.py --depart 2026-05-10
    python flight_tracker.py --depart 2026-05-10 --return 2026-05-17
    python flight_tracker.py --depart 2026-05-10 --return 2026-05-17 --max-price 80000
"""

import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import anthropic

load_dotenv()

ORIGIN = "DEL"
TEMP_THRESHOLD = 25.0

EUROPEAN_CITIES = [
    {"name": "Amsterdam",   "iata": "AMS", "lat": 52.3676,  "lon":  4.9041},
    {"name": "Paris",       "iata": "CDG", "lat": 48.8566,  "lon":  2.3522},
    {"name": "Rome",        "iata": "FCO", "lat": 41.9028,  "lon": 12.4964},
    {"name": "Barcelona",   "iata": "BCN", "lat": 41.3851,  "lon":  2.1734},
    {"name": "Prague",      "iata": "PRG", "lat": 50.0755,  "lon": 14.4378},
    {"name": "Vienna",      "iata": "VIE", "lat": 48.2082,  "lon": 16.3738},
    {"name": "Lisbon",      "iata": "LIS", "lat": 38.7169,  "lon": -9.1399},
    {"name": "Athens",      "iata": "ATH", "lat": 37.9838,  "lon": 23.7275},
    {"name": "Dublin",      "iata": "DUB", "lat": 53.3498,  "lon": -6.2603},
    {"name": "Copenhagen",  "iata": "CPH", "lat": 55.6761,  "lon": 12.5683},
    {"name": "Stockholm",   "iata": "ARN", "lat": 59.3293,  "lon": 18.0686},
    {"name": "Oslo",        "iata": "OSL", "lat": 59.9139,  "lon": 10.7522},
    {"name": "Helsinki",    "iata": "HEL", "lat": 60.1699,  "lon": 24.9384},
    {"name": "Zurich",      "iata": "ZRH", "lat": 47.3769,  "lon":  8.5417},
    {"name": "Brussels",    "iata": "BRU", "lat": 50.8503,  "lon":  4.3517},
    {"name": "Warsaw",      "iata": "WAW", "lat": 52.2297,  "lon": 21.0122},
    {"name": "Budapest",    "iata": "BUD", "lat": 47.4979,  "lon": 19.0402},
    {"name": "Reykjavik",   "iata": "KEF", "lat": 64.1355,  "lon": -21.8954},
    {"name": "Edinburgh",   "iata": "EDI", "lat": 55.9533,  "lon": -3.1883},
    {"name": "Porto",       "iata": "OPO", "lat": 41.1496,  "lon": -8.6109},
    {"name": "Krakow",      "iata": "KRK", "lat": 50.0647,  "lon": 19.9450},
    {"name": "Riga",        "iata": "RIX", "lat": 56.9460,  "lon": 24.1059},
    {"name": "Tallinn",     "iata": "TLL", "lat": 59.4370,  "lon": 24.7536},
    {"name": "Vilnius",     "iata": "VNO", "lat": 54.6872,  "lon": 25.2797},
    {"name": "Bucharest",   "iata": "OTP", "lat": 44.4268,  "lon": 26.1025},
    {"name": "Sofia",       "iata": "SOF", "lat": 42.6977,  "lon": 23.3219},
    {"name": "Zagreb",      "iata": "ZAG", "lat": 45.8150,  "lon": 15.9819},
    {"name": "Bratislava",  "iata": "BTS", "lat": 48.1486,  "lon": 17.1077},
]

SYSTEM_PROMPT = """You are an expert travel analyst specializing in budget flights from India to Europe.
Your job is to analyze flight price and weather data and produce a clear, actionable travel report for someone flying from Delhi (DEL).

Format your response using these sections:

## Executive Summary
2-3 sentences covering the overall deal landscape for these dates.

## Ranked Flight Deals
A markdown table sorted by price (cheapest first):
| Rank | Destination | Temp (°C) | Price (INR) | Price (EUR ~) | Airline | Flight Time | Source |

Use 1 EUR ≈ 90 INR for the EUR column. Mark missing prices as "Check manually".

## Top 3 Best-Value Picks
For each pick: city name as a heading, one sentence on why it's great (price + weather combo), and one practical travel tip.

## Best For Different Travelers
- Budget traveler: [city] — reason
- Culture & history: [city] — reason
- Nature & outdoors: [city] — reason

## Booking Tip
One specific, actionable piece of advice for booking these routes from Delhi.

Rules:
- Be concise and specific — no filler text
- All cities shown are already filtered to temp < 25°C
- Skyscanner is generally the most accurate source; note when only one source is available
- If all prices are N/A, still rank by temperature and give recommendations based on typical pricing"""


def get_temperatures(cities):
    """Batch-fetch current temperatures for all cities from Open-Meteo (free, no key)."""
    lats = ",".join(str(c["lat"]) for c in cities)
    lons = ",".join(str(c["lon"]) for c in cities)

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": lats, "longitude": lons, "current": "temperature_2m"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        print(f"ERROR: Weather API failed — {exc}", file=sys.stderr)
        sys.exit(1)

    results = {}
    items = data if isinstance(data, list) else [data]
    for i, item in enumerate(items):
        if i < len(cities):
            temp = item.get("current", {}).get("temperature_2m")
            if temp is not None:
                results[cities[i]["name"]] = round(float(temp), 1)
    return results


def _parse_skyscanner_response(data):
    """Extract cheapest itinerary from a Sky-Scanner3 RapidAPI response."""
    itineraries = (
        data.get("data", {}).get("itineraries")
        or data.get("itineraries")
        or []
    )
    if not itineraries:
        return None

    best = itineraries[0]
    price_raw = (
        best.get("price", {}).get("raw")
        or best.get("price", {}).get("amount")
    )
    if not price_raw:
        return None

    price_fmt = best.get("price", {}).get("formatted") or f"₹{float(price_raw):,.0f}"

    airline = "Unknown"
    duration_str = None
    legs = best.get("legs", [])
    if legs:
        carriers = legs[0].get("carriers", {}).get("marketing", [])
        if carriers:
            airline = carriers[0].get("name", "Unknown")
        mins = legs[0].get("durationInMinutes")
        if mins:
            h, m = divmod(int(mins), 60)
            duration_str = f"{h}h {m}m"

    return {
        "price_inr": float(price_raw),
        "price_formatted": price_fmt,
        "airline": airline,
        "duration": duration_str,
        "source": "Skyscanner",
    }


def search_skyscanner(dest_iata, depart_date, return_date):
    """Search Skyscanner via RapidAPI for cheapest roundtrip from DEL."""
    key = os.getenv("RAPIDAPI_KEY", "").strip()
    host = os.getenv("SKYSCANNER_API_HOST", "sky-scanner3.p.rapidapi.com").strip()
    if not key:
        return None

    headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": host}
    params = {
        "fromEntityId": ORIGIN,
        "toEntityId": dest_iata,
        "departDate": depart_date,
        "returnDate": return_date,
        "adults": "1",
        "currency": "INR",
        "market": "IN",
        "locale": "en-IN",
    }

    for endpoint in (
        f"https://{host}/v1/flights/search-roundtrip",
        f"https://{host}/flights/search-roundtrip",
    ):
        try:
            resp = requests.get(endpoint, headers=headers, params=params, timeout=15)
            if resp.status_code == 429:
                time.sleep(1)
                return None
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            result = _parse_skyscanner_response(resp.json())
            if result:
                return result
        except requests.RequestException:
            continue
    return None


def _parse_booking_response(data):
    """Extract cheapest flight from a Booking.com (or similar) RapidAPI response."""
    flights = (
        data.get("data", {}).get("flightOffers")
        or data.get("data", {}).get("flights")
        or data.get("results")
        or []
    )
    if not flights:
        return None

    best = flights[0]
    price_raw = None

    breakdown = best.get("priceBreakdown", {})
    if breakdown:
        total = breakdown.get("total", {})
        price_raw = total.get("units") or total.get("amount")

    if not price_raw:
        price_raw = best.get("price", {}).get("raw") or best.get("price", {}).get("amount")

    if not price_raw:
        return None

    airline = "Unknown"
    try:
        seg = best.get("segments", [{}])[0]
        carrier = seg.get("legs", [{}])[0].get("carriersData", [{}])[0]
        airline = carrier.get("name", "Unknown")
    except (IndexError, KeyError, TypeError):
        pass

    return {
        "price_inr": float(price_raw),
        "price_formatted": f"₹{float(price_raw):,.0f}",
        "airline": airline,
        "duration": None,
        "source": "FlightBooking",
    }


def search_flight_booking(dest_iata, depart_date, return_date):
    """Search optional secondary flight booking API via RapidAPI."""
    key = os.getenv("RAPIDAPI_KEY", "").strip()
    host = os.getenv("FLIGHT_BOOKING_API_HOST", "").strip()
    if not key or not host:
        return None

    headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": host}
    params = {
        "fromId": f"{ORIGIN}.AIRPORT",
        "toId": f"{dest_iata}.AIRPORT",
        "departDate": depart_date,
        "returnDate": return_date,
        "adults": "1",
        "currency_code": "INR",
        "cabinClass": "ECONOMY",
    }

    try:
        resp = requests.get(
            f"https://{host}/api/v1/flights/searchFlights",
            headers=headers,
            params=params,
            timeout=15,
        )
        if resp.status_code in (403, 404, 429):
            return None
        resp.raise_for_status()
        return _parse_booking_response(resp.json())
    except requests.RequestException:
        return None


def collect_flight_data(filtered_cities, depart_date, return_date, max_price):
    """Fetch flight prices for all temperature-filtered cities and return results list."""
    results = []
    total = len(filtered_cities)

    for i, city in enumerate(filtered_cities, 1):
        name, iata = city["name"], city["iata"]
        print(f"  [{i}/{total}] {name} ({iata}) ... ", end="", flush=True)

        ss = search_skyscanner(iata, depart_date, return_date)
        time.sleep(0.4)
        fb = search_flight_booking(iata, depart_date, return_date)

        candidates = [r for r in (ss, fb) if r and r["price_inr"]]
        if candidates:
            best = min(candidates, key=lambda x: x["price_inr"])
            if max_price and best["price_inr"] > max_price:
                print(f"skipped ({best['price_formatted']} > max ₹{max_price:,})")
                continue
            print(f"{best['price_formatted']} via {best['source']}")
        else:
            best = {"price_inr": None, "price_formatted": "N/A",
                    "airline": "N/A", "duration": "N/A", "source": "N/A"}
            print("price unavailable")

        results.append({
            "city": name,
            "iata": iata,
            "temperature_c": city["temp"],
            "price_inr": best["price_inr"],
            "price_formatted": best["price_formatted"],
            "airline": best["airline"],
            "flight_duration": best["duration"],
            "data_source": best["source"],
        })

    return results


def generate_claude_report(flight_data, depart_date, return_date):
    """Send all collected data to Claude and return a formatted travel report."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None

    client = anthropic.Anthropic(api_key=api_key)
    user_message = (
        f"Travel dates: {depart_date} to {return_date}\n"
        f"Origin: Delhi (DEL), India\n\n"
        f"Flight & temperature data for qualifying European destinations:\n"
        f"{json.dumps(flight_data, indent=2)}\n\n"
        f"Generate the full travel report."
    )

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
        return msg.content[0].text
    except anthropic.APIError as exc:
        print(f"\nWARNING: Claude API error — {exc}. Printing raw table instead.\n",
              file=sys.stderr)
        return None


def print_fallback_table(flight_data):
    """Plain table fallback when Claude is unavailable."""
    try:
        from tabulate import tabulate
        rows = [
            [
                d["city"], d["iata"], f"{d['temperature_c']}°C",
                d["price_formatted"], d["airline"],
                d["flight_duration"] or "N/A", d["data_source"],
            ]
            for d in sorted(flight_data, key=lambda x: x["price_inr"] or float("inf"))
        ]
        print(tabulate(
            rows,
            headers=["City", "IATA", "Temp", "Price (INR)", "Airline", "Duration", "Source"],
            tablefmt="rounded_grid",
        ))
    except ImportError:
        for d in sorted(flight_data, key=lambda x: x["price_inr"] or float("inf")):
            print(f"  {d['city']:15} {d['iata']}  {d['temperature_c']}°C  "
                  f"{d['price_formatted']:>15}  {d['airline']}")


def main():
    parser = argparse.ArgumentParser(
        description="One-shot European flight tracker from Delhi — filters by temp < 25°C"
    )
    parser.add_argument("--depart", required=True,
                        help="Departure date (YYYY-MM-DD)")
    parser.add_argument("--return", dest="return_date",
                        help="Return date (YYYY-MM-DD, default: depart + 7 days)")
    parser.add_argument("--max-price", type=int,
                        help="Skip destinations with price above this INR value")
    args = parser.parse_args()

    depart_date = args.depart
    return_date = args.return_date or (
        datetime.strptime(depart_date, "%Y-%m-%d") + timedelta(days=7)
    ).strftime("%Y-%m-%d")

    try:
        datetime.strptime(depart_date, "%Y-%m-%d")
        datetime.strptime(return_date, "%Y-%m-%d")
    except ValueError:
        print("ERROR: Dates must be in YYYY-MM-DD format.", file=sys.stderr)
        sys.exit(1)

    sep = "=" * 62
    print(f"\n{sep}")
    print(f"  EUROPEAN FLIGHT TRACKER  |  Delhi (DEL) -> Europe")
    print(f"  Dates  : {depart_date}  ->  {return_date}")
    print(f"  Filter : temperature < {TEMP_THRESHOLD}°C")
    if args.max_price:
        print(f"  Budget : max ₹{args.max_price:,}")
    print(f"{sep}\n")

    # ── Step 1: Weather ────────────────────────────────────────────
    print("Step 1/3  Fetching temperatures for 28 European cities ...")
    temps = get_temperatures(EUROPEAN_CITIES)

    filtered = []
    cold_cities, warm_cities = [], []
    for city in EUROPEAN_CITIES:
        temp = temps.get(city["name"])
        if temp is None:
            continue
        if temp < TEMP_THRESHOLD:
            filtered.append({**city, "temp": temp})
            cold_cities.append(f"{city['name']} {temp}°C")
        else:
            warm_cities.append(f"{city['name']} {temp}°C")

    print(f"\n  Qualifying ({len(filtered)} cities, temp < {TEMP_THRESHOLD}°C):")
    for entry in sorted(cold_cities):
        print(f"    {entry}")

    if warm_cities:
        print(f"\n  Excluded — too warm ({len(warm_cities)} cities):")
        print(f"    {', '.join(sorted(warm_cities))}")

    if not filtered:
        print(f"\nNo cities below {TEMP_THRESHOLD}°C right now. Try different dates or a higher threshold.")
        sys.exit(0)

    # ── Step 2: Flight prices ─────────────────────────────────────
    print(f"\nStep 2/3  Searching flights from DEL to {len(filtered)} destinations ...")
    if not os.getenv("RAPIDAPI_KEY", "").strip():
        print("  WARNING: RAPIDAPI_KEY not set — all prices will show as unavailable.")

    flight_data = collect_flight_data(filtered, depart_date, return_date, args.max_price)

    if not flight_data:
        print("\nNo destinations remaining after filtering. Exiting.")
        sys.exit(0)

    priced = sum(1 for d in flight_data if d["price_inr"])
    print(f"\n  Prices found for {priced}/{len(flight_data)} destinations.")

    # ── Step 3: Claude report ─────────────────────────────────────
    print("\nStep 3/3  Generating AI travel report with Claude ...")
    report = generate_claude_report(flight_data, depart_date, return_date)

    print(f"\n{sep}")
    print("  TRAVEL REPORT")
    print(f"{sep}\n")

    if report:
        print(report)
    else:
        print_fallback_table(flight_data)

    print(f"\n{sep}")
    print("  Sources: Open-Meteo (weather) | Skyscanner via RapidAPI | Claude AI")
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
