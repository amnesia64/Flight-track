#!/usr/bin/env python3
"""
flight_tracker.py — One-shot European flight price tracker from Delhi (DEL).

Fetches current temperatures for 28 European cities via Open-Meteo (free, no key),
keeps only destinations below 25°C, searches flight prices from DEL via:
  - sky-scrapper.p.rapidapi.com  (Skyscanner data)
  - airhob-api.p.rapidapi.com    (additional flight booking source)
Then prints a ranked travel report — no AI API key required.

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
from tabulate import tabulate

load_dotenv()

ORIGIN = "DEL"
TEMP_THRESHOLD = 25.0
EUR_PER_INR = 90

SKYSCANNER_HOST = "sky-scrapper.p.rapidapi.com"
AIRHOB_HOST     = "airhob-api.p.rapidapi.com"

# Persistent cache so entity-ID lookups only happen once per IATA code
_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".sky_entity_cache.json")
_entity_cache: dict = {}

EUROPEAN_CITIES = [
    {"name": "Amsterdam",  "iata": "AMS", "lat": 52.3676,  "lon":  4.9041},
    {"name": "Paris",      "iata": "CDG", "lat": 48.8566,  "lon":  2.3522},
    {"name": "Rome",       "iata": "FCO", "lat": 41.9028,  "lon": 12.4964},
    {"name": "Barcelona",  "iata": "BCN", "lat": 41.3851,  "lon":  2.1734},
    {"name": "Prague",     "iata": "PRG", "lat": 50.0755,  "lon": 14.4378},
    {"name": "Vienna",     "iata": "VIE", "lat": 48.2082,  "lon": 16.3738},
    {"name": "Lisbon",     "iata": "LIS", "lat": 38.7169,  "lon": -9.1399},
    {"name": "Athens",     "iata": "ATH", "lat": 37.9838,  "lon": 23.7275},
    {"name": "Dublin",     "iata": "DUB", "lat": 53.3498,  "lon": -6.2603},
    {"name": "Copenhagen", "iata": "CPH", "lat": 55.6761,  "lon": 12.5683},
    {"name": "Stockholm",  "iata": "ARN", "lat": 59.3293,  "lon": 18.0686},
    {"name": "Oslo",       "iata": "OSL", "lat": 59.9139,  "lon": 10.7522},
    {"name": "Helsinki",   "iata": "HEL", "lat": 60.1699,  "lon": 24.9384},
    {"name": "Zurich",     "iata": "ZRH", "lat": 47.3769,  "lon":  8.5417},
    {"name": "Brussels",   "iata": "BRU", "lat": 50.8503,  "lon":  4.3517},
    {"name": "Warsaw",     "iata": "WAW", "lat": 52.2297,  "lon": 21.0122},
    {"name": "Budapest",   "iata": "BUD", "lat": 47.4979,  "lon": 19.0402},
    {"name": "Reykjavik",  "iata": "KEF", "lat": 64.1355,  "lon": -21.8954},
    {"name": "Edinburgh",  "iata": "EDI", "lat": 55.9533,  "lon": -3.1883},
    {"name": "Porto",      "iata": "OPO", "lat": 41.1496,  "lon": -8.6109},
    {"name": "Krakow",     "iata": "KRK", "lat": 50.0647,  "lon": 19.9450},
    {"name": "Riga",       "iata": "RIX", "lat": 56.9460,  "lon": 24.1059},
    {"name": "Tallinn",    "iata": "TLL", "lat": 59.4370,  "lon": 24.7536},
    {"name": "Vilnius",    "iata": "VNO", "lat": 54.6872,  "lon": 25.2797},
    {"name": "Bucharest",  "iata": "OTP", "lat": 44.4268,  "lon": 26.1025},
    {"name": "Sofia",      "iata": "SOF", "lat": 42.6977,  "lon": 23.3219},
    {"name": "Zagreb",     "iata": "ZAG", "lat": 45.8150,  "lon": 15.9819},
    {"name": "Bratislava", "iata": "BTS", "lat": 48.1486,  "lon": 17.1077},
]

CITY_PROFILES = {
    "Amsterdam":  ("culture",  "canals, world-class museums, vibrant cycling culture"),
    "Paris":      ("culture",  "Eiffel Tower, art galleries, unbeatable food scene"),
    "Rome":       ("culture",  "ancient history, Vatican, outdoor museums everywhere"),
    "Barcelona":  ("culture",  "Gaudí architecture, beaches, buzzing nightlife"),
    "Prague":     ("budget",   "fairy-tale old town, craft beer, very affordable"),
    "Vienna":     ("culture",  "classical music, grand cafes, imperial palaces"),
    "Lisbon":     ("budget",   "trams, fado music, affordable seafood and wine"),
    "Athens":     ("culture",  "Acropolis, street food, island ferry base"),
    "Dublin":     ("culture",  "pubs, literary history, rugged coastal walks"),
    "Copenhagen": ("culture",  "design capital, cycling, New Nordic cuisine"),
    "Stockholm":  ("nature",   "archipelago islands, ABBA museum, clean Nordic air"),
    "Oslo":       ("nature",   "fjords, hiking trails, Viking ship museum"),
    "Helsinki":   ("nature",   "sauna culture, island ferries, design district"),
    "Zurich":     ("nature",   "Alps day-trips, pristine lakes, Swiss chocolate"),
    "Brussels":   ("culture",  "waffles, Art Nouveau, EU heart of Europe"),
    "Warsaw":     ("budget",   "WWII history, booming food scene, very affordable"),
    "Budapest":   ("budget",   "thermal baths, ruin bars, gorgeous Danube views"),
    "Reykjavik":  ("nature",   "Northern Lights, volcanoes, geysers, midnight sun"),
    "Edinburgh":  ("nature",   "castle, whisky distilleries, Highlands gateway"),
    "Porto":      ("budget",   "port wine cellars, azulejos tilework, river charm"),
    "Krakow":     ("budget",   "medieval main square, Wieliczka salt mine, very cheap"),
    "Riga":       ("budget",   "stunning Art Nouveau district, medieval old town"),
    "Tallinn":    ("culture",  "best-preserved medieval old town in Europe"),
    "Vilnius":    ("budget",   "baroque old town, hipster cafes, budget-friendly"),
    "Bucharest":  ("budget",   "communist-era palace, nightlife, emerging food scene"),
    "Sofia":      ("budget",   "Vitosha mountain backdrop, Orthodox churches, ultra-cheap"),
    "Zagreb":     ("culture",  "museum of broken relationships, compact walkable centre"),
    "Bratislava": ("budget",   "hilltop castle, tiny old town, easy day-trip from Vienna"),
}


# ── Entity-ID cache (sky-scrapper needs skyId + entityId, not just IATA) ──────

def _load_entity_cache():
    global _entity_cache
    if os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE) as f:
                _entity_cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            _entity_cache = {}


def _save_entity_cache():
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(_entity_cache, f, indent=2)
    except OSError:
        pass


def get_sky_entity(iata_code, rapidapi_key):
    """Return (skyId, entityId) for an IATA code, fetching from sky-scrapper if not cached."""
    if iata_code in _entity_cache:
        entry = _entity_cache[iata_code]
        return entry["skyId"], entry["entityId"]

    try:
        resp = requests.get(
            f"https://{SKYSCANNER_HOST}/api/v1/flights/searchAirport",
            headers={"X-RapidAPI-Key": rapidapi_key, "X-RapidAPI-Host": SKYSCANNER_HOST},
            params={"query": iata_code, "locale": "en-US"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("data", [])
        if results:
            r = results[0]
            sky_id   = str(r.get("skyId")    or iata_code)
            entity_id = str(r.get("entityId") or r.get("id") or "")
            _entity_cache[iata_code] = {"skyId": sky_id, "entityId": entity_id}
            _save_entity_cache()
            return sky_id, entity_id
    except requests.RequestException:
        pass

    # Fallback: use IATA as skyId and leave entityId blank
    _entity_cache[iata_code] = {"skyId": iata_code, "entityId": ""}
    return iata_code, ""


# ── Weather ────────────────────────────────────────────────────────────────────

def get_temperatures(cities):
    """Batch-fetch current temperatures from Open-Meteo (free, no API key needed)."""
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


# ── Skyscanner via sky-scrapper.p.rapidapi.com ────────────────────────────────

def _parse_skyscanner_response(data):
    itineraries = (
        data.get("data", {}).get("itineraries")
        or data.get("itineraries")
        or []
    )
    if not itineraries:
        return None

    best = itineraries[0]
    price_raw = best.get("price", {}).get("raw") or best.get("price", {}).get("amount")
    if not price_raw:
        return None

    price_fmt    = best.get("price", {}).get("formatted") or f"₹{float(price_raw):,.0f}"
    airline      = "Unknown"
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


def search_skyscanner(dest_iata, depart_date, return_date, rapidapi_key):
    """Search sky-scrapper.p.rapidapi.com for cheapest roundtrip from DEL."""
    if not rapidapi_key:
        return None

    origin_sky, origin_entity = get_sky_entity(ORIGIN, rapidapi_key)
    dest_sky,   dest_entity   = get_sky_entity(dest_iata, rapidapi_key)

    headers = {"X-RapidAPI-Key": rapidapi_key, "X-RapidAPI-Host": SKYSCANNER_HOST}
    params  = {
        "originSkyId":        origin_sky,
        "destinationSkyId":   dest_sky,
        "originEntityId":     origin_entity,
        "destinationEntityId": dest_entity,
        "date":               depart_date,
        "returnDate":         return_date,
        "adults":             "1",
        "currency":           "INR",
        "market":             "IN",
        "locale":             "en-IN",
        "cabinClass":         "economy",
    }

    try:
        resp = requests.get(
            f"https://{SKYSCANNER_HOST}/api/v1/flights/searchFlights",
            headers=headers,
            params=params,
            timeout=20,
        )
        if resp.status_code == 429:
            time.sleep(2)
            return None
        resp.raise_for_status()
        return _parse_skyscanner_response(resp.json())
    except requests.RequestException:
        return None


# ── Airhob via airhob-api.p.rapidapi.com ──────────────────────────────────────

def _parse_airhob_response(data):
    """Extract cheapest flight from an airhob API response."""
    # airhob wraps results under data.results or data.flights
    flights = (
        data.get("data", {}).get("results")
        or data.get("data", {}).get("flights")
        or data.get("results")
        or data.get("flights")
        or []
    )
    if not flights:
        return None

    best = flights[0]

    # Try common price field names used by airhob
    price_raw = (
        best.get("price")
        or best.get("totalPrice")
        or best.get("total_price")
        or best.get("fare", {}).get("total")
        or best.get("amount")
    )
    if not price_raw:
        return None

    # Airline name
    airline = (
        best.get("airline")
        or best.get("airlineName")
        or best.get("carrier")
        or (best.get("segments", [{}])[0].get("airline") if best.get("segments") else None)
        or "Unknown"
    )

    # Duration
    duration_str = None
    mins = best.get("duration") or best.get("durationMinutes") or best.get("total_duration")
    if mins:
        try:
            h, m = divmod(int(mins), 60)
            duration_str = f"{h}h {m}m"
        except (ValueError, TypeError):
            pass

    return {
        "price_inr":      float(price_raw),
        "price_formatted": f"₹{float(price_raw):,.0f}",
        "airline":        airline,
        "duration":       duration_str,
        "source":         "Airhob",
    }


def search_airhob(dest_iata, depart_date, return_date, rapidapi_key):
    """Search airhob-api.p.rapidapi.com for roundtrip flights from DEL."""
    if not rapidapi_key:
        return None

    headers = {"X-RapidAPI-Key": rapidapi_key, "X-RapidAPI-Host": AIRHOB_HOST}
    params  = {
        "origin":          ORIGIN,
        "destination":     dest_iata,
        "departureDate":   depart_date,
        "returnDate":      return_date,
        "adults":          "1",
        "currency":        "INR",
        "cabinClass":      "ECONOMY",
        "tripType":        "ROUND",
    }

    # Try the two most common airhob endpoint paths
    for path in ("/search", "/flights/search"):
        try:
            resp = requests.get(
                f"https://{AIRHOB_HOST}{path}",
                headers=headers,
                params=params,
                timeout=15,
            )
            if resp.status_code == 404:
                continue
            if resp.status_code == 429:
                time.sleep(1)
                return None
            resp.raise_for_status()
            result = _parse_airhob_response(resp.json())
            if result:
                return result
        except requests.RequestException:
            continue
    return None


# ── Flight collection loop ─────────────────────────────────────────────────────

def collect_flight_data(filtered_cities, depart_date, return_date, max_price, rapidapi_key):
    results = []
    total   = len(filtered_cities)

    for i, city in enumerate(filtered_cities, 1):
        name, iata = city["name"], city["iata"]
        print(f"  [{i}/{total}] {name} ({iata}) ... ", end="", flush=True)

        ss = search_skyscanner(iata, depart_date, return_date, rapidapi_key)
        time.sleep(0.5)
        ah = search_airhob(iata, depart_date, return_date, rapidapi_key)

        candidates = [r for r in (ss, ah) if r and r["price_inr"]]
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
            "city":           name,
            "iata":           iata,
            "temperature_c":  city["temp"],
            "price_inr":      best["price_inr"],
            "price_formatted": best["price_formatted"],
            "airline":        best["airline"],
            "flight_duration": best["duration"],
            "data_source":    best["source"],
        })

    return results


# ── Report (pure Python, no AI key needed) ────────────────────────────────────

def generate_report(flight_data, depart_date, return_date):
    priced   = sorted([d for d in flight_data if d["price_inr"]], key=lambda x: x["price_inr"])
    unpriced = [d for d in flight_data if not d["price_inr"]]
    ordered  = priced + unpriced

    lines = []

    # Executive summary
    lines.append("EXECUTIVE SUMMARY")
    lines.append("-" * 40)
    if priced:
        cheapest = priced[0]
        avg_inr  = sum(d["price_inr"] for d in priced) / len(priced)
        lines.append(
            f"Found {len(priced)} priced route(s) from Delhi to Europe with temp < 25°C "
            f"({depart_date} → {return_date}).\n"
            f"Cheapest: {cheapest['city']} at {cheapest['price_formatted']} "
            f"(~€{int(cheapest['price_inr'] / EUR_PER_INR):,}).\n"
            f"Average across all destinations: ₹{avg_inr:,.0f} (~€{int(avg_inr / EUR_PER_INR):,})."
        )
    else:
        lines.append(
            f"{len(flight_data)} destination(s) qualify on temperature but prices could not be "
            "fetched — verify your RAPIDAPI_KEY in .env."
        )
    lines.append("")

    # Ranked deals table
    lines.append("RANKED FLIGHT DEALS  (cheapest first)")
    lines.append("-" * 40)
    rows = []
    for rank, d in enumerate(ordered, 1):
        eur = f"~€{int(d['price_inr'] / EUR_PER_INR):,}" if d["price_inr"] else "—"
        rows.append([
            rank,
            f"{d['city']} ({d['iata']})",
            f"{d['temperature_c']}°C",
            d["price_formatted"],
            eur,
            d["airline"],
            d["flight_duration"] or "N/A",
            d["data_source"],
        ])
    lines.append(tabulate(
        rows,
        headers=["#", "Destination", "Temp", "Price (INR)", "EUR ~",
                 "Airline", "Duration", "Source"],
        tablefmt="rounded_grid",
    ))
    lines.append("")

    # Top 3 best-value picks
    lines.append("TOP 3 BEST-VALUE PICKS")
    lines.append("-" * 40)
    top3 = priced[:3] if priced else sorted(flight_data, key=lambda x: x["temperature_c"])[:3]
    for d in top3:
        _, vibe = CITY_PROFILES.get(d["city"], ("—", "a great European destination"))
        eur_str = f" (~€{int(d['price_inr'] / EUR_PER_INR):,})" if d["price_inr"] else ""
        lines.append(f"  {d['city']} ({d['iata']})  |  {d['price_formatted']}{eur_str}  |  {d['temperature_c']}°C")
        lines.append(f"  {vibe}.")
        lines.append(f"  Tip: search '{ORIGIN}→{d['iata']}' on Skyscanner with 'Whole month' view for the cheapest date.")
        lines.append("")

    # Best for each traveler type
    lines.append("BEST FOR DIFFERENT TRAVELERS")
    lines.append("-" * 40)

    def best_of(ttype):
        pool = [d for d in priced if CITY_PROFILES.get(d["city"], ("",))[0] == ttype]
        if not pool:
            pool = [d for d in flight_data if CITY_PROFILES.get(d["city"], ("",))[0] == ttype]
        return pool[0] if pool else None

    for ttype, label in (("budget", "Budget traveler  "), ("culture", "Culture & history"),
                         ("nature", "Nature & outdoors")):
        d = best_of(ttype)
        if d:
            _, vibe  = CITY_PROFILES.get(d["city"], ("", ""))
            price_str = d["price_formatted"] if d["price_inr"] else "price N/A"
            lines.append(f"  {label}:  {d['city']} ({price_str}) — {vibe}")
    lines.append("")

    # Booking tip
    lines.append("BOOKING TIP")
    lines.append("-" * 40)
    lines.append(
        "  Use Skyscanner's 'Cheapest month' grid to find the best date combination.\n"
        "  From Delhi, IndiGo, Air India, and Emirates/Qatar often have the best fares.\n"
        "  Flying into Amsterdam, Lisbon, or Prague is usually cheapest — then hop\n"
        "  onward with Ryanair or Wizz Air for €10-30 to your final destination."
    )

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="One-shot European flight tracker from Delhi — filters by temp < 25°C"
    )
    parser.add_argument("--depart",     required=True, help="Departure date (YYYY-MM-DD)")
    parser.add_argument("--return",     dest="return_date",
                        help="Return date (YYYY-MM-DD, default: depart + 7 days)")
    parser.add_argument("--max-price",  type=int,
                        help="Skip destinations priced above this INR value")
    args = parser.parse_args()

    depart_date = args.depart
    return_date = args.return_date or (
        datetime.strptime(depart_date, "%Y-%m-%d") + timedelta(days=7)
    ).strftime("%Y-%m-%d")

    try:
        datetime.strptime(depart_date, "%Y-%m-%d")
        datetime.strptime(return_date, "%Y-%m-%d")
    except ValueError:
        print("ERROR: Dates must be YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)

    rapidapi_key = os.getenv("RAPIDAPI_KEY", "").strip()

    _load_entity_cache()

    sep = "=" * 62
    print(f"\n{sep}")
    print(f"  EUROPEAN FLIGHT TRACKER  |  Delhi (DEL) -> Europe")
    print(f"  Dates  : {depart_date}  ->  {return_date}")
    print(f"  Filter : temperature < {TEMP_THRESHOLD}°C")
    if args.max_price:
        print(f"  Budget : max ₹{args.max_price:,}")
    print(f"  Sources: {SKYSCANNER_HOST}  |  {AIRHOB_HOST}")
    print(f"{sep}\n")

    # Step 1 — Weather
    print("Step 1/3  Fetching temperatures for 28 European cities ...")
    temps = get_temperatures(EUROPEAN_CITIES)

    filtered, cold_log, warm_log = [], [], []
    for city in EUROPEAN_CITIES:
        temp = temps.get(city["name"])
        if temp is None:
            continue
        if temp < TEMP_THRESHOLD:
            filtered.append({**city, "temp": temp})
            cold_log.append(f"{city['name']} {temp}°C")
        else:
            warm_log.append(f"{city['name']} {temp}°C")

    print(f"\n  Qualifying — {len(filtered)} cities below {TEMP_THRESHOLD}°C:")
    for entry in sorted(cold_log):
        print(f"    {entry}")
    if warm_log:
        print(f"\n  Excluded (too warm): {', '.join(sorted(warm_log))}")

    if not filtered:
        print(f"\nNo cities below {TEMP_THRESHOLD}°C right now.")
        sys.exit(0)

    # Step 2 — Prices
    print(f"\nStep 2/3  Searching flights from DEL to {len(filtered)} destinations ...")
    if not rapidapi_key:
        print("  WARNING: RAPIDAPI_KEY not set in .env — all prices will show as unavailable.")

    flight_data = collect_flight_data(
        filtered, depart_date, return_date, args.max_price, rapidapi_key
    )

    if not flight_data:
        print("\nNo destinations left after price filtering. Exiting.")
        sys.exit(0)

    priced_count = sum(1 for d in flight_data if d["price_inr"])
    print(f"\n  Prices found for {priced_count}/{len(flight_data)} destinations.")

    # Step 3 — Report
    print("\nStep 3/3  Building travel report ...\n")

    print(f"\n{sep}")
    print("  TRAVEL REPORT")
    print(f"{sep}\n")
    print(generate_report(flight_data, depart_date, return_date))
    print(f"\n{sep}")
    print(f"  Sources: Open-Meteo (weather) | {SKYSCANNER_HOST} | {AIRHOB_HOST}")
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
