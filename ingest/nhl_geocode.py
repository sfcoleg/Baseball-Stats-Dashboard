"""Geocode every distinct NHL player birthplace into data/nhl.db's
`geo_places` table (city, state/province, country -> lat, lon), for the
Birthplace Map page.

Source: OpenStreetMap's Nominatim (free, no key). Its usage policy asks
for a real User-Agent, at most one request per second, and caching — so
this script identifies itself, sleeps 1s between lookups, and only ever
geocodes places not already in the table. The first full run over ~1,500
distinct birthplaces takes ~25 minutes; every run after that only picks
up new places (a handful per season), so the nightly refresh can call it
cheaply.

Lookup strategy, most to least specific, stopping at the first hit:
  "City, Region, Country" -> "City, Country" -> "City"
Country/region codes are expanded to full names first (Nominatim matches
"Canada" far more reliably than "CAN").

Usage:
    python ingest/nhl_geocode.py          # geocode anything not yet cached
"""
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
import requests

NHL_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nhl.db"
HEADERS = {"User-Agent": "DiamondMetrics/1.0 (greg@cromulentlabs.com)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"

# The NHL API's 3-letter country codes -> names Nominatim recognizes.
COUNTRY_NAMES = {
    "CAN": "Canada", "USA": "United States", "SWE": "Sweden", "FIN": "Finland", "RUS": "Russia",
    "CZE": "Czechia", "SVK": "Slovakia", "CHE": "Switzerland", "DEU": "Germany", "DNK": "Denmark",
    "NOR": "Norway", "AUT": "Austria", "LVA": "Latvia", "SVN": "Slovenia", "FRA": "France",
    "GBR": "United Kingdom", "AUS": "Australia", "BLR": "Belarus", "UKR": "Ukraine", "NLD": "Netherlands",
    "KAZ": "Kazakhstan", "BEL": "Belgium", "ITA": "Italy", "POL": "Poland", "HUN": "Hungary",
    "JPN": "Japan", "KOR": "South Korea", "CHN": "China", "BGR": "Bulgaria", "HRV": "Croatia",
    "LTU": "Lithuania", "EST": "Estonia", "IRL": "Ireland", "MEX": "Mexico", "BRA": "Brazil",
    "NGA": "Nigeria", "ZAF": "South Africa", "UZB": "Uzbekistan", "SRB": "Serbia", "JAM": "Jamaica",
    "HTI": "Haiti", "ARE": "United Arab Emirates", "ISR": "Israel", "TWN": "Taiwan", "BHS": "Bahamas",
    "PRI": "Puerto Rico", "VEN": "Venezuela", "ESP": "Spain", "PRT": "Portugal", "GRC": "Greece",
    "TUR": "Turkey", "IND": "India", "PHL": "Philippines", "NZL": "New Zealand", "THA": "Thailand",
}

# State/province codes the NHL uses for CAN/USA. Anything else is passed
# through as-is (it's usually already a readable region name or null).
REGION_NAMES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}


def _norm(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def distinct_birthplaces() -> pd.DataFrame:
    """Every distinct (city, region, country) across skaters and goalies."""
    with sqlite3.connect(NHL_DB_PATH) as conn:
        frames = []
        for table in ("skaters", "goalies"):
            try:
                frames.append(pd.read_sql(
                    f"SELECT DISTINCT birthCity, birthStateProvinceCode, birthCountryCode FROM {table}", conn
                ))
            except pd.errors.DatabaseError:
                pass
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if df.empty:
        return df
    for c in df.columns:
        df[c] = df[c].map(_norm)
    df = df[df["birthCity"] != ""].drop_duplicates().reset_index(drop=True)
    return df.rename(columns={"birthCity": "city", "birthStateProvinceCode": "region", "birthCountryCode": "country"})


def already_cached() -> set[tuple]:
    with sqlite3.connect(NHL_DB_PATH) as conn:
        try:
            rows = conn.execute("SELECT city, region, country FROM geo_places").fetchall()
        except sqlite3.OperationalError:
            return set()
    return set(rows)


def _query(q: str):
    resp = requests.get(
        NOMINATIM, params={"q": q, "format": "json", "limit": 1}, headers=HEADERS, timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", "")
    return None


def geocode(city: str, region: str, country: str):
    """Try progressively looser queries; returns (lat, lon, matched_name, query_used) or None."""
    country_name = COUNTRY_NAMES.get(country, country)
    region_name = REGION_NAMES.get(region, region)
    candidates = []
    if region_name and country_name:
        candidates.append(f"{city}, {region_name}, {country_name}")
    if country_name:
        candidates.append(f"{city}, {country_name}")
    candidates.append(city)
    for q in candidates:
        try:
            hit = _query(q)
        except Exception as e:  # noqa: BLE001
            print(f"    lookup error for {q!r}: {e!r}", flush=True)
            hit = None
        time.sleep(1.05)  # Nominatim policy: max 1 request/second
        if hit:
            return (*hit, q)
    return None


def run() -> None:
    places = distinct_birthplaces()
    cached = already_cached()
    todo = [r for r in places.itertuples(index=False) if (r.city, r.region, r.country) not in cached]
    print(f"{len(places)} distinct birthplaces, {len(cached)} cached, {len(todo)} to geocode", flush=True)
    if not todo:
        print("done")
        return

    with sqlite3.connect(NHL_DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS geo_places ("
            " city TEXT, region TEXT, country TEXT, lat REAL, lon REAL, matched TEXT, query TEXT,"
            " PRIMARY KEY (city, region, country))"
        )
        for i, r in enumerate(todo, 1):
            result = geocode(r.city, r.region, r.country)
            if result:
                lat, lon, matched, q = result
                conn.execute(
                    "INSERT OR REPLACE INTO geo_places VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (r.city, r.region, r.country, lat, lon, matched, q),
                )
            else:
                # Record the miss so we don't re-query it every night.
                conn.execute(
                    "INSERT OR REPLACE INTO geo_places VALUES (?, ?, ?, NULL, NULL, NULL, NULL)",
                    (r.city, r.region, r.country),
                )
                print(f"    no match: {r.city}, {r.region}, {r.country}", flush=True)
            if i % 25 == 0:
                conn.commit()
                print(f"  ...{i}/{len(todo)}", flush=True)
        conn.commit()
    print("done")


if __name__ == "__main__":
    run()
