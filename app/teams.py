"""MLB team metadata: real team colors + abbreviations, used for badges.

Baseball-Reference's scraped 'Tm' column is a city name, which is ambiguous
for cities with two teams (New York, Chicago, Los Angeles). We disambiguate
using the 'Lev' column (Maj-AL / Maj-NL) that comes with the same data.
Statcast-sourced tables (fielding) instead give the team nickname directly.
"""

# (city, league) -> (abbreviation, nickname, primary color)
# league is None when the city has only one team.
_BY_CITY_LEAGUE = {
    ("Arizona", None): ("ARI", "Diamondbacks", "#A71930"),
    ("Atlanta", None): ("ATL", "Braves", "#CE1141"),
    ("Athletics", None): ("ATH", "Athletics", "#003831"),
    ("Baltimore", None): ("BAL", "Orioles", "#DF4601"),
    ("Boston", None): ("BOS", "Red Sox", "#BD3039"),
    ("Chicago", "AL"): ("CWS", "White Sox", "#27251F"),
    ("Chicago", "NL"): ("CHC", "Cubs", "#0E3386"),
    ("Cincinnati", None): ("CIN", "Reds", "#C6011F"),
    ("Cleveland", None): ("CLE", "Guardians", "#00385D"),
    ("Colorado", None): ("COL", "Rockies", "#33006F"),
    ("Detroit", None): ("DET", "Tigers", "#0C2340"),
    ("Houston", None): ("HOU", "Astros", "#EB6E1F"),
    ("Kansas City", None): ("KC", "Royals", "#004687"),
    ("Los Angeles", "AL"): ("LAA", "Angels", "#BA0021"),
    ("Los Angeles", "NL"): ("LAD", "Dodgers", "#005A9C"),
    ("Miami", None): ("MIA", "Marlins", "#00A3E0"),
    ("Milwaukee", None): ("MIL", "Brewers", "#12284B"),
    ("Minnesota", None): ("MIN", "Twins", "#002B5C"),
    ("New York", "AL"): ("NYY", "Yankees", "#0C2340"),
    ("New York", "NL"): ("NYM", "Mets", "#002D72"),
    ("Philadelphia", None): ("PHI", "Phillies", "#E81828"),
    ("Pittsburgh", None): ("PIT", "Pirates", "#FDB827"),
    ("San Diego", None): ("SD", "Padres", "#2F241D"),
    ("San Francisco", None): ("SF", "Giants", "#FD5A1E"),
    ("Seattle", None): ("SEA", "Mariners", "#0C2C56"),
    ("St. Louis", None): ("STL", "Cardinals", "#C41E3A"),
    ("Tampa Bay", None): ("TB", "Rays", "#092C5C"),
    ("Texas", None): ("TEX", "Rangers", "#003278"),
    ("Toronto", None): ("TOR", "Blue Jays", "#134A8E"),
    ("Washington", None): ("WSH", "Nationals", "#AB0003"),
}

# nickname -> (abbreviation, primary color), for Statcast-sourced tables
# (e.g. fielding) which report the nickname directly.
_BY_NICKNAME = {info[1]: (info[0], info[2]) for info in _BY_CITY_LEAGUE.values()}
_BY_NICKNAME["D-backs"] = _BY_NICKNAME["Diamondbacks"]

# abbreviation -> primary color, used once a Tm column has been converted
# to abbreviations (see add_team_abbr) so table styling doesn't need to
# re-resolve the city/league ambiguity per cell.
_COLOR_BY_ABBR = {info[0]: info[2] for info in _BY_CITY_LEAGUE.values()}


def color_for_abbr(abbr: str) -> str:
    return _COLOR_BY_ABBR.get(abbr, "#666666")


def all_teams() -> list[tuple[str, str]]:
    """All 30 teams as (abbreviation, nickname) pairs, sorted by abbreviation."""
    return sorted(((info[0], info[1]) for info in _BY_CITY_LEAGUE.values()), key=lambda t: t[0])


def add_team_abbr(df, tm_col="Tm", lev_col="Lev", out_col="Tm"):
    """Return a copy of df with `out_col` replaced by the disambiguated
    team abbreviation (uses Lev to resolve shared cities like New York)."""
    df = df.copy()
    df[out_col] = df.apply(
        lambda row: team_meta_from_city(row[tm_col], row.get(lev_col))[0], axis=1
    )
    return df


def add_team_abbr_from_nickname(df, tm_col="Tm", out_col="Tm"):
    """Like add_team_abbr, but for Statcast-sourced tables (e.g. fielding)
    whose Tm column is already a team nickname (e.g. 'Yankees')."""
    df = df.copy()
    df[out_col] = df[tm_col].map(lambda nick: team_meta_from_nickname(nick)[0])
    return df


def _league_code(lev: str | None) -> str | None:
    if not lev:
        return None
    return "AL" if lev.endswith("AL") else "NL" if lev.endswith("NL") else None


def team_meta_from_city(tm: str, lev: str | None = None) -> tuple[str, str, str]:
    """Look up (abbreviation, nickname, color) from a Baseball-Reference
    city string (possibly multiple comma-separated cities for a traded
    player, in which case the most recent/last team is used)."""
    if not isinstance(tm, str) or not tm:
        return ("—", "Unknown", "#666666")
    city = tm.split(",")[-1].strip()
    league = _league_code(lev)
    info = _BY_CITY_LEAGUE.get((city, league)) or _BY_CITY_LEAGUE.get((city, None))
    if info is None:
        return (city[:3].upper(), city, "#666666")
    return info


def team_meta_from_nickname(nickname: str) -> tuple[str, str]:
    """Look up (abbreviation, color) from a team nickname (Statcast format)."""
    if not isinstance(nickname, str):
        return ("—", "#666666")
    return _BY_NICKNAME.get(nickname, (nickname[:3].upper(), "#666666"))


# abbreviation -> MLB Stats API team id (stable, from /api/v1/teams?sportId=1),
# used for live per-team lookups like the depth chart. The API reports
# Arizona as "AZ", not our "ARI" — keyed here under our own abbreviation.
_TEAM_IDS = {
    "ARI": 109, "ATL": 144, "ATH": 133, "BAL": 110, "BOS": 111, "CWS": 145,
    "CHC": 112, "CIN": 113, "CLE": 114, "COL": 115, "DET": 116, "HOU": 117,
    "KC": 118, "LAA": 108, "LAD": 119, "MIA": 146, "MIL": 158, "MIN": 142,
    "NYY": 147, "NYM": 121, "PHI": 143, "PIT": 134, "SD": 135, "SF": 137,
    "SEA": 136, "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "WSH": 120,
}


def team_id_for_abbr(abbr: str) -> int | None:
    return _TEAM_IDS.get(abbr)


# The MLB Stats API's own team-abbreviation field uses "AZ" for Arizona;
# every other source in this app (Baseball-Reference-derived abbreviations,
# _TEAM_IDS above) uses "ARI". Normalize before looking anything up by
# abbreviation when the value came from a live Stats API payload (e.g.
# todays_games' away_abbr/home_abbr).
_MLB_API_ABBR_FIX = {"AZ": "ARI"}


def normalize_mlb_abbr(abbr: str) -> str:
    return _MLB_API_ABBR_FIX.get(abbr, abbr)
