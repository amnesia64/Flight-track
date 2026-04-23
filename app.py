from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flight_tracker import (
    run_search, CITY_PROFILES, EUR_PER_INR, SKYSCANNER_HOST, AIRHOB_HOST
)

load_dotenv()

app = Flask(__name__)


@app.route("/")
def index():
    today         = datetime.today()
    default_depart = (today + timedelta(days=30)).strftime("%Y-%m-%d")
    default_return = (today + timedelta(days=37)).strftime("%Y-%m-%d")
    return render_template("index.html",
                           default_depart=default_depart,
                           default_return=default_return,
                           today=today.strftime("%Y-%m-%d"))


@app.route("/search", methods=["POST"])
def search():
    depart_date   = request.form.get("depart_date", "").strip()
    return_date   = request.form.get("return_date", "").strip()
    max_price_str = request.form.get("max_price", "").strip()
    max_price     = int(max_price_str) if max_price_str.isdigit() else None

    if not depart_date or not return_date:
        return redirect(url_for("index"))

    results     = run_search(depart_date, return_date, max_price)
    flight_data = results.get("flight_data", [])

    priced   = sorted([d for d in flight_data if d["price_inr"]], key=lambda x: x["price_inr"])
    unpriced = [d for d in flight_data if not d["price_inr"]]
    sorted_data = priced + unpriced

    stats = {}
    if priced:
        stats = {
            "cheapest":     priced[0],
            "avg_inr":      int(sum(d["price_inr"] for d in priced) / len(priced)),
            "priced_count": len(priced),
            "total_count":  len(flight_data),
        }

    # Top 3 picks with profiles
    top_picks = []
    for d in priced[:3]:
        ttype, vibe = CITY_PROFILES.get(d["city"], ("—", "a great European destination"))
        top_picks.append({**d, "vibe": vibe, "traveler_type": ttype})

    # Best per traveler type (cheapest in each category)
    best_for = {}
    for ttype, label in (("budget", "Budget traveler"), ("culture", "Culture & history"),
                         ("nature", "Nature & outdoors")):
        pool = [d for d in priced if CITY_PROFILES.get(d["city"], ("",))[0] == ttype]
        if pool:
            _, vibe = CITY_PROFILES.get(pool[0]["city"], ("", ""))
            best_for[label] = {**pool[0], "vibe": vibe}

    return render_template("results.html",
                           sorted_data=sorted_data,
                           stats=stats,
                           top_picks=top_picks,
                           best_for=best_for,
                           eur_per_inr=EUR_PER_INR,
                           depart_date=depart_date,
                           return_date=return_date,
                           max_price=max_price,
                           cold_count=len(results.get("filtered", [])),
                           skyscanner_host=SKYSCANNER_HOST,
                           airhob_host=AIRHOB_HOST)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
