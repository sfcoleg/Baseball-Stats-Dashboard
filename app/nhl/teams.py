"""NHL team metadata — abbreviation -> (nickname, primary color). Logos come
from the NHL's public asset CDN by abbreviation."""
import base64
from pathlib import Path


_TEAMS = {
    "ANA": ("Ducks", "#F47A38"), "BOS": ("Bruins", "#FFB81C"), "BUF": ("Sabres", "#003087"),
    "CGY": ("Flames", "#D2001C"), "CAR": ("Hurricanes", "#CC0000"), "CHI": ("Blackhawks", "#CF0A2C"),
    "COL": ("Avalanche", "#6F263D"), "CBJ": ("Blue Jackets", "#002654"), "DAL": ("Stars", "#006847"),
    "DET": ("Red Wings", "#CE1126"), "EDM": ("Oilers", "#FF4C00"), "FLA": ("Panthers", "#C8102E"),
    "LAK": ("Kings", "#A2AAAD"), "MIN": ("Wild", "#154734"), "MTL": ("Canadiens", "#AF1E2D"),
    "NSH": ("Predators", "#FFB81C"), "NJD": ("Devils", "#CE0E2D"), "NYI": ("Islanders", "#00539B"),
    "NYR": ("Rangers", "#0038A8"), "OTT": ("Senators", "#DA1A32"), "PHI": ("Flyers", "#F74902"),
    "PIT": ("Penguins", "#FCB514"), "SJS": ("Sharks", "#006D75"), "SEA": ("Kraken", "#99D9D9"),
    "STL": ("Blues", "#002F87"), "TBL": ("Lightning", "#002868"), "TOR": ("Maple Leafs", "#00205B"),
    "UTA": ("Mammoth", "#6CACE4"), "VAN": ("Canucks", "#00843D"), "VGK": ("Golden Knights", "#B4975A"),
    "WSH": ("Capitals", "#C8102E"), "WPG": ("Jets", "#041E42"),
    # Relocated/legacy codes that still appear in older seasons' data.
    "ARI": ("Coyotes", "#8C2633"),
}


def color_for_abbr(abbr: str) -> str:
    return _TEAMS.get(_primary(abbr), ("", "#666666"))[1]


def nickname_for_abbr(abbr: str) -> str:
    return _TEAMS.get(_primary(abbr), (abbr, ""))[0] or abbr


def all_teams() -> list[tuple[str, str]]:
    return sorted((abbr, info[0]) for abbr, info in _TEAMS.items() if abbr != "ARI")


def logo_url(abbr: str) -> str:
    return f"https://assets.nhle.com/logos/nhl/svg/{_primary(abbr)}_light.svg"


def _primary(abbr) -> str:
    """The NHL API lists a traded player's teams as 'TOR,FLA' — the last one
    is his current club."""
    if not isinstance(abbr, str) or not abbr:
        return ""
    return abbr.split(",")[-1].strip()


# Numeric team id (as used by play-by-play's eventOwnerTeamId, schedule's
# team.id, etc.) -> abbreviation. From api.nhle.com/stats/rest/en/team,
# filtered to the 32 current franchises (+ARI, still used for pre-Utah-move
# game data).
_ID_TO_ABBR = {
    24: "ANA", 6: "BOS", 7: "BUF", 20: "CGY", 12: "CAR", 16: "CHI", 21: "COL", 29: "CBJ",
    25: "DAL", 17: "DET", 22: "EDM", 13: "FLA", 26: "LAK", 30: "MIN", 8: "MTL", 18: "NSH",
    1: "NJD", 2: "NYI", 3: "NYR", 9: "OTT", 4: "PHI", 5: "PIT", 28: "SJS", 55: "SEA",
    19: "STL", 14: "TBL", 10: "TOR", 68: "UTA", 23: "VAN", 54: "VGK", 15: "WSH", 52: "WPG",
    53: "ARI",
}


def abbr_for_id(team_id) -> str:
    try:
        return _ID_TO_ABBR.get(int(team_id), "")
    except (TypeError, ValueError):
        return ""


# Home arena for every current franchise: (arena name, city, lat, lon).
# Used by the Birthplace Map to plot where each team plays alongside where
# its players were born.
ARENAS = {
    "ANA": ("Honda Center", "Anaheim, CA", 33.8078, -117.8765),
    "BOS": ("TD Garden", "Boston, MA", 42.3662, -71.0621),
    "BUF": ("KeyBank Center", "Buffalo, NY", 42.8750, -78.8764),
    "CGY": ("Scotiabank Saddledome", "Calgary, AB", 51.0375, -114.0519),
    "CAR": ("Lenovo Center", "Raleigh, NC", 35.8034, -78.7219),
    "CHI": ("United Center", "Chicago, IL", 41.8807, -87.6742),
    "COL": ("Ball Arena", "Denver, CO", 39.7487, -105.0077),
    "CBJ": ("Nationwide Arena", "Columbus, OH", 39.9692, -83.0061),
    "DAL": ("American Airlines Center", "Dallas, TX", 32.7905, -96.8103),
    "DET": ("Little Caesars Arena", "Detroit, MI", 42.3411, -83.0553),
    "EDM": ("Rogers Place", "Edmonton, AB", 53.5469, -113.4979),
    "FLA": ("Amerant Bank Arena", "Sunrise, FL", 26.1584, -80.3255),
    "LAK": ("Crypto.com Arena", "Los Angeles, CA", 34.0430, -118.2673),
    "MIN": ("Xcel Energy Center", "St. Paul, MN", 44.9448, -93.1011),
    "MTL": ("Bell Centre", "Montreal, QC", 45.4961, -73.5693),
    "NSH": ("Bridgestone Arena", "Nashville, TN", 36.1592, -86.7785),
    "NJD": ("Prudential Center", "Newark, NJ", 40.7336, -74.1711),
    "NYI": ("UBS Arena", "Elmont, NY", 40.7227, -73.7259),
    "NYR": ("Madison Square Garden", "New York, NY", 40.7505, -73.9934),
    "OTT": ("Canadian Tire Centre", "Ottawa, ON", 45.2969, -75.9271),
    "PHI": ("Xfinity Mobile Arena", "Philadelphia, PA", 39.9012, -75.1720),
    "PIT": ("PPG Paints Arena", "Pittsburgh, PA", 40.4395, -79.9893),
    "SJS": ("SAP Center", "San Jose, CA", 37.3327, -121.9012),
    "SEA": ("Climate Pledge Arena", "Seattle, WA", 47.6221, -122.3540),
    "STL": ("Enterprise Center", "St. Louis, MO", 38.6268, -90.2026),
    "TBL": ("Amalie Arena", "Tampa, FL", 27.9427, -82.4518),
    "TOR": ("Scotiabank Arena", "Toronto, ON", 43.6435, -79.3791),
    "UTA": ("Delta Center", "Salt Lake City, UT", 40.7683, -111.9011),
    "VAN": ("Rogers Arena", "Vancouver, BC", 49.2778, -123.1089),
    "VGK": ("T-Mobile Arena", "Las Vegas, NV", 36.1028, -115.1784),
    "WSH": ("Capital One Arena", "Washington, DC", 38.8982, -77.0209),
    "WPG": ("Canada Life Centre", "Winnipeg, MB", 49.8927, -97.1436),
}


# ESPN's logo CDN serves transparent PNGs, which deck.gl's IconLayer can
# rasterize — the NHL's own CDN is SVG-only, which that layer can't size
# reliably. Only the abbreviations that differ from ours are listed.
_ESPN_ABBR = {"NJD": "nj", "SJS": "sj", "TBL": "tb", "LAK": "la", "UTA": "utah"}


def logo_png_url(abbr: str) -> str:
    code = _ESPN_ABBR.get(_primary(abbr), _primary(abbr).lower())
    return f"https://a.espncdn.com/i/teamlogos/nhl/500/{code}.png"


_LOGO_DIR = Path(__file__).resolve().parent / "assets" / "logos"


def logo_data_uri(abbr: str) -> str:
    """Local 96px PNG (assets/logos/, shrunk from ESPN's CDN) as a base64
    data URI — for deck.gl IconLayer, which needs a raster it can load
    without any cross-origin fetch. Falls back to the CDN URL if the file
    is missing."""
    path = _LOGO_DIR / f"{_primary(abbr)}.png"
    if not path.exists():
        return logo_png_url(abbr)
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
