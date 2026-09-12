"""NBA-specific presentation. Shared chrome (headers, stat tables) still
comes from app/style.py; add to this as real NBA-only components come up,
following app/nfl/style.py's shape."""


def player_link(player_id, season: str | None = None) -> str:
    """Relative URL to a player's profile page — same pattern as
    app/nhl/style.py's player_link(), one query param per sport since each
    player.py reads its own name (nba/pages/player.py reads "player")."""
    url = f"nba-player?player={int(player_id)}"
    if season is not None:
        url += f"&season={season}"
    return url


def headshot_url(player_id) -> str:
    """NBA's own CDN, confirmed directly (200 for a real player id) —
    same idea as app/style.py's headshot_url() for MLB."""
    return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{int(player_id)}.png"
