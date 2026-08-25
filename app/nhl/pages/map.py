"""NHL Birthplace Map — every player's hometown and every team's home arena
on one interactive map (pydeck / deck.gl over a Carto dark basemap).

Birthplaces are bubbled per city (radius ~ sqrt of player count) so
hockey's hotbeds read as hotbeds instead of a pile of overlapping dots,
with a hover listing who's from there. Teams plot as their logo at the
arena. Below the map: the numbers behind it — players by country, the
most productive hometowns, and each team's "local products" (players born
within 100 km of the arena they play in).

Data: bios from the NHL stats API (ingest/nhl_refresh.py) geocoded via
OpenStreetMap's Nominatim (ingest/nhl_geocode.py)."""
import math
import sys
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL Birthplace Map | Diamond Metrics", layout="wide")
st.title("Birthplace Map")

mtime = ndb.nhl_db_mtime()
seasons = ndb.skater_seasons(mtime)
if not seasons:
    st.info("No NHL data yet — run ingest/nhl_refresh.py to backfill.")
    st.stop()

COUNTRY_NAMES = {
    "CAN": "Canada", "USA": "United States", "SWE": "Sweden", "FIN": "Finland", "RUS": "Russia",
    "CZE": "Czechia", "SVK": "Slovakia", "CHE": "Switzerland", "DEU": "Germany", "DNK": "Denmark",
    "NOR": "Norway", "AUT": "Austria", "LVA": "Latvia", "SVN": "Slovenia", "FRA": "France",
    "GBR": "United Kingdom", "AUS": "Australia", "BLR": "Belarus", "UKR": "Ukraine", "NLD": "Netherlands",
    "KAZ": "Kazakhstan", "BEL": "Belgium", "ITA": "Italy", "POL": "Poland", "HUN": "Hungary",
}
# Country -> marker color (RGB). The big five get the strongest, most
# separable hues; everything else shares a neutral so the map isn't a
# rainbow of one-off countries.
COUNTRY_COLORS = {
    "CAN": (239, 68, 68), "USA": (59, 130, 246), "SWE": (250, 204, 21), "FIN": (96, 165, 250),
    "RUS": (168, 85, 247), "CZE": (34, 197, 94), "SVK": (20, 184, 166), "CHE": (251, 146, 60),
    "DEU": (236, 72, 153), "DNK": (244, 114, 182), "LVA": (163, 230, 53),
}
OTHER_COLOR = (156, 163, 175)


def _country_name(code: str) -> str:
    return COUNTRY_NAMES.get(code, code or "Unknown")


def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --- Filters -------------------------------------------------------------
f1, f2, f3, f4, f5 = st.columns([1.2, 1, 1, 1.4, 1.2])
with f1:
    season = st.selectbox("Season", seasons, format_func=ndb.season_label)
players = ndb.load_birthplaces(season, mtime)
if players.empty:
    st.info("Birthplace data isn't on file for this season yet — run ingest/nhl_refresh.py, then ingest/nhl_geocode.py.")
    st.stop()
players["Tm"] = players["teamAbbrevs"].map(nteams._primary)
players["country"] = players["birthCountryCode"].map(_country_name)

with f2:
    role = st.selectbox("Players", ["All", "Skaters", "Goalies"])
with f3:
    pos = st.selectbox("Position", ["All", "C", "L", "R", "D", "G"])
with f4:
    team_choice = st.selectbox(
        "Team", ["All teams"] + [a for a, _ in nteams.all_teams()],
        format_func=lambda a: a if a == "All teams" else f"{a} — {nteams.nickname_for_abbr(a)}",
    )
with f5:
    country_options = players["country"].value_counts().index.tolist()
    countries = st.multiselect("Country", country_options, placeholder="All countries")

filtered = players.copy()
if role == "Skaters":
    filtered = filtered[filtered["role"] == "Skater"]
elif role == "Goalies":
    filtered = filtered[filtered["role"] == "Goalie"]
if pos != "All":
    filtered = filtered[filtered["positionCode"] == pos]
if team_choice != "All teams":
    filtered = filtered[filtered["Tm"] == team_choice]
if countries:
    filtered = filtered[filtered["country"].isin(countries)]

located = filtered.dropna(subset=["lat", "lon"])
unlocated = len(filtered) - len(located)

# --- City bubbles ---------------------------------------------------------
def _city_label(row) -> str:
    region = row["birthStateProvinceCode"]
    return f"{row['birthCity']}, {region}" if region else row["birthCity"]


located = located.assign(city_label=located.apply(_city_label, axis=1))
cities = (
    located.groupby(["city_label", "birthCountryCode", "lat", "lon"], as_index=False)
    .agg(n=("playerId", "size"), names=("name", lambda s: sorted(s)))
)
cities["country"] = cities["birthCountryCode"].map(_country_name)
cities["color"] = cities["birthCountryCode"].map(lambda c: list(COUNTRY_COLORS.get(c, OTHER_COLOR)))
# Radius in meters: sqrt scaling so a 20-player city isn't 20x a 1-player
# dot, floored so lone players are still visible zoomed out.
cities["radius"] = cities["n"].map(lambda n: 9000 + 11000 * math.sqrt(n))
# Plain text only — deck.gl escapes substituted tooltip values, so any
# HTML here would show up literally as "<br/>".
cities["who"] = cities["names"].map(
    lambda ns: ", ".join(ns[:8]) + (f" … +{len(ns) - 8} more" if len(ns) > 8 else "")
)
cities["headline"] = cities.apply(
    lambda r: f"{r['n']} player{'s' if r['n'] != 1 else ''}", axis=1
)

# --- Team arenas ---------------------------------------------------------
arena_rows = []
for abbr, (arena, city, lat, lon) in nteams.ARENAS.items():
    if team_choice != "All teams" and abbr != team_choice:
        continue
    n_players = int((filtered["Tm"] == abbr).sum())
    arena_rows.append({
        "abbr": abbr, "team": f"{city.split(',')[0]} {nteams.nickname_for_abbr(abbr)}",
        "arena": arena, "city": city, "lat": lat, "lon": lon,
        "icon": {"url": nteams.logo_data_uri(abbr), "width": 96, "height": 96, "anchorY": 48},
        "color": list(_hex_to_rgb(nteams.color_for_abbr(abbr))),
        "headline": f"{n_players} player{'s' if n_players != 1 else ''} on the roster",
        "who": arena,
    })
arenas = pd.DataFrame(arena_rows)

# --- Map ---------------------------------------------------------------
# Countries that produced a player in the current filter are filled with that
# country's own colour; everywhere else stays a flat grey, so the map itself
# shows where the league comes from instead of being a neutral backdrop. The
# basemap is dropped entirely (no Carto tiles) and the ocean is just the
# container's own blue showing through deck.gl's transparent canvas.
_GEOJSON_PATH = Path(__file__).resolve().parent.parent / "assets" / "world_countries.geojson"
_source_countries = set(filtered["birthCountryCode"].dropna().unique()) if not filtered.empty else set()


@st.cache_data(show_spinner=False)
def _world(source: tuple, colors: dict):
    """World polygons tagged with a fill colour. Cached on the set of source
    countries so panning and filtering don't re-read 250 KB of geometry."""
    import json
    data = json.loads(_GEOJSON_PATH.read_text())
    for feat in data["features"]:
        iso = feat["properties"].get("iso")
        if iso in source:
            feat["properties"]["fill"] = list(colors.get(iso, OTHER_COLOR)) + [205]
        else:
            feat["properties"]["fill"] = [88, 96, 110, 165]
    return data


country_layer = pdk.Layer(
    "GeoJsonLayer",
    data=_world(tuple(sorted(_source_countries)), COUNTRY_COLORS),
    stroked=True,
    filled=True,
    get_fill_color="properties.fill",
    get_line_color=[255, 255, 255, 45],
    line_width_min_pixels=0.5,
    pickable=False,
)

bubble_layer = pdk.Layer(
    "ScatterplotLayer",
    data=cities[["city_label", "country", "lat", "lon", "n", "color", "radius", "who", "headline"]].rename(
        columns={"city_label": "title"}),
    get_position="[lon, lat]",
    get_radius="radius",
    get_fill_color="color",
    get_line_color=[255, 255, 255, 110],
    line_width_min_pixels=1,
    stroked=True,
    opacity=0.55,
    pickable=True,
    radius_min_pixels=3,
    radius_max_pixels=60,
)
arena_glow = pdk.Layer(
    "ScatterplotLayer",
    data=arenas.rename(columns={"team": "title", "city": "country"}) if not arenas.empty else arenas,
    get_position="[lon, lat]",
    get_radius=26000,
    get_fill_color="color",
    opacity=0.35,
    stroked=True,
    get_line_color=[255, 255, 255, 200],
    line_width_min_pixels=2,
    radius_min_pixels=14,
    radius_max_pixels=30,
    pickable=True,
)
arena_icons = pdk.Layer(
    "IconLayer",
    data=arenas if not arenas.empty else arenas,
    get_position="[lon, lat]",
    get_icon="icon",
    # No size_units="pixels" here: pydeck serializes bare strings as
    # "@@=" expressions (so "pixels" became an invalid accessor and the
    # whole layer silently failed). IconLayer already defaults to pixels.
    get_size=34,
    size_min_pixels=22,
    size_max_pixels=48,
    pickable=False,
)

VIEWS = {
    "World": pdk.ViewState(latitude=46.0, longitude=-45.0, zoom=1.95, pitch=0),
    "North America": pdk.ViewState(latitude=46.5, longitude=-96.0, zoom=3.0, pitch=0),
    "Europe": pdk.ViewState(latitude=56.0, longitude=20.0, zoom=3.2, pitch=0),
}
preset = st.radio("View", list(VIEWS), horizontal=True, label_visibility="collapsed")
if team_choice != "All teams" and not located.empty and preset == "World":
    # A single team: frame its arena and its players' hometowns together.
    lat0, lon0 = nteams.ARENAS[team_choice][2], nteams.ARENAS[team_choice][3]
    view = pdk.ViewState(latitude=(lat0 + located["lat"].mean()) / 2,
                         longitude=(lon0 + located["lon"].mean()) / 2, zoom=2.6, pitch=0)
else:
    view = VIEWS[preset]

tooltip = {
    "html": "<div style='font-family:sans-serif'><b style='font-size:14px'>{title}</b>"
            "<div style='color:var(--dm-dim);font-size:12px;margin-bottom:4px'>{country}</div>"
            "<div style='font-weight:600;margin-bottom:4px'>{headline}</div>"
            "<div style='font-size:12px;line-height:1.35'>{who}</div></div>",
    "style": {"backgroundColor": "#1B2438", "color": "#FAFAFA", "borderRadius": "8px", "padding": "10px 12px",
              "border": "1px solid #4A5266"},
}

st.markdown(
    "<style>[data-testid='stDeckGlJsonChart'],[data-testid='stDeckGlJsonChart'] canvas{"
    "background:#123A63 !important;border-radius:12px;}</style>",
    unsafe_allow_html=True,
)
st.pydeck_chart(
    pdk.Deck(
        layers=[country_layer, bubble_layer, arena_glow, arena_icons],
        initial_view_state=view,
        map_provider=None,
        map_style=None,
        tooltip=tooltip,
    ),
    use_container_width=True, height=620,
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Players", len(filtered))
m2.metric("Hometowns", len(cities))
m3.metric("Countries", filtered["country"].nunique())
m4.metric("Teams", len(arenas))
if unlocated:
    st.caption(f"{unlocated} player{'s' if unlocated != 1 else ''} not plotted — birthplace missing or not geocoded yet.")

st.divider()

# --- The numbers behind the map ------------------------------------------
c1, c2 = st.columns(2)
with c1:
    style.colored_header("Players by Country", "batting")
    by_country = filtered["country"].value_counts().reset_index()
    by_country.columns = ["Country", "Players"]
    by_country["Share"] = (by_country["Players"] / len(filtered) * 100).round(1)
    st.dataframe(by_country, use_container_width=True, hide_index=True, height=360)

with c2:
    style.colored_header("Top Hometowns", "pitching")
    top_cities = cities.sort_values("n", ascending=False).head(15)[["city_label", "country", "n"]].rename(
        columns={"city_label": "Hometown", "country": "Country", "n": "Players"})
    st.dataframe(top_cities, use_container_width=True, hide_index=True, height=360)

# --- Local products ---------------------------------------------------------
style.colored_header("Local Products", "fielding")
st.caption("Players born within 100 km of the arena they play in.")
LOCAL_KM = 100
local_rows = []
for _, p in located.iterrows():
    arena = nteams.ARENAS.get(p["Tm"])
    if not arena:
        continue
    d = _haversine_km(p["lat"], p["lon"], arena[2], arena[3])
    if d <= LOCAL_KM:
        local_rows.append({
            "name": p["name"], "playerId": p["playerId"], "Tm": p["Tm"], "Pos": p["positionCode"],
            "Hometown": p["city_label"], "km": round(d),
        })
if not local_rows:
    st.caption("No local products match the current filters.")
else:
    local = pd.DataFrame(local_rows).sort_values(["Tm", "km"])
    for team_abbr, grp in local.groupby("Tm"):
        color = nteams.color_for_abbr(team_abbr)
        names_html = " · ".join(
            f"<a href='{nstyle.player_link(r.playerId, season)}' target='_self' "
            f"style='color:inherit;text-decoration:none;font-weight:600'>{r.name}</a>"
            f"<span style='color:var(--dm-dim)'> ({r.Hometown}, {r.km} km)</span>"
            for r in grp.itertuples()
        )
        st.markdown(
            f"<div style='margin-bottom:8px'><span style='background-color:{color}66;color:var(--dm-text);"
            f"padding:2px 9px;border-radius:6px;font-weight:700;margin-right:8px'>{team_abbr}</span>{names_html}</div>",
            unsafe_allow_html=True,
        )
