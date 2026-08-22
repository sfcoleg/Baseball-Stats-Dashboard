"""NHL team metadata — abbreviation -> (nickname, primary color). Logos come
from the NHL's public asset CDN by abbreviation."""

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
