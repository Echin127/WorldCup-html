"""
Pull Australia's 2026 World Cup qualification fixtures (AFC) from ESPN's
public (unofficial) JSON API, with venue coordinates, to CSV.

Unofficial/undocumented endpoint — may change without notice. No key required.
Columns: date, round, opponent, score, venue, city, country, attendance, lat, lon
score = Australia's perspective.
"""

import csv
import time
import requests
from datetime import date, timedelta
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

# ----- settings -----
LEAGUE   = "fifa.worldq.afc"          # AFC World Cup qualifying slug
TEAM     = "Australia"                # ESPN team displayName to match
OUT_FILE = "australia_wcq_2026_espn.csv"

# FIFA windows that held Australia's qualifiers — scan these, not every day.
WINDOWS = [
    ("2023-11-13", "2023-11-22"),
    ("2024-03-18", "2024-03-27"),
    ("2024-06-03", "2024-06-12"),
    ("2024-09-02", "2024-09-11"),
    ("2024-10-07", "2024-10-16"),
    ("2024-11-11", "2024-11-20"),
    ("2025-03-17", "2025-03-26"),
    ("2025-06-02", "2025-06-11"),
]
# --------------------

SCOREBOARD = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{LEAGUE}/scoreboard"
HEADERS = {"User-Agent": "Mozilla/5.0"}   # ESPN blocks the default python UA


def daterange(start, end):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    while s <= e:
        yield s.strftime("%Y%m%d")
        s += timedelta(days=1)


def round_from_date(iso_date):
    # 2nd round ended Jun 2024; 3rd round began Sep 2024
    return "Second" if iso_date <= "2024-06-30" else "Third"


def get_scoreboard(yyyymmdd):
    r = requests.get(SCOREBOARD, headers=HEADERS,
                     params={"dates": yyyymmdd}, timeout=30)
    r.raise_for_status()
    return r.json().get("events", [])


def parse_event(ev):
    comp = ev["competitions"][0]

    if not comp.get("status", {}).get("type", {}).get("completed"):
        return None                                   # skip unplayed/abandoned

    sides = comp["competitors"]
    me = next((c for c in sides if c["team"]["displayName"] == TEAM), None)
    if me is None:
        return None                                   # not an Australia match
    opp = next(c for c in sides if c is not me)

    score = f"{me.get('score')}-{opp.get('score')}"

    venue = comp.get("venue", {})
    addr  = venue.get("address", {})

    rnd = round_from_date(ev["date"][:10])
    for note in comp.get("notes", []):                # use ESPN's label if present
        head = note.get("headline", "").lower()
        if "second" in head or "2nd" in head:
            rnd = "Second"
        elif "third" in head or "3rd" in head:
            rnd = "Third"

    return {
        "date": ev["date"][:10],
        "round": rnd,
        "opponent": opp["team"]["displayName"],
        "score": score,
        "venue": venue.get("fullName", ""),
        "city": addr.get("city", ""),
        "country": addr.get("country", ""),           # often blank → geocoder fills
        "attendance": comp.get("attendance", "") or "",
        "lat": "", "lon": "",
    }


def pull():
    rows, seen = [], set()
    for start, end in WINDOWS:
        for d in daterange(start, end):
            for ev in get_scoreboard(d):
                row = parse_event(ev)
                if row:
                    key = (row["date"], row["opponent"])
                    if key not in seen:
                        seen.add(key)
                        rows.append(row)
            time.sleep(0.3)                            # be polite to ESPN
    rows.sort(key=lambda x: x["date"])
    return rows


def add_coordinates(rows):
    geocode = RateLimiter(
        Nominatim(user_agent="socceroos_wcq_espn").geocode,
        min_delay_seconds=1.1,
    )
    cache = {}
    for row in rows:
        key = f"{row['venue']}, {row['city']}".strip(", ")
        if key not in cache:
            cache[key] = (geocode(key, addressdetails=True, language="en")
                          or geocode(row["city"], addressdetails=True, language="en"))
        loc = cache[key]
        if loc:
            row["lat"] = round(loc.latitude, 5)
            row["lon"] = round(loc.longitude, 5)
            if not row["country"]:
                row["country"] = loc.raw.get("address", {}).get("country", "")
    return rows


def main():
    rows = add_coordinates(pull())
    fields = ["date", "round", "opponent", "score", "venue",
              "city", "country", "attendance", "lat", "lon"]
    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} fixtures to {OUT_FILE}")


if __name__ == "__main__":
    main()