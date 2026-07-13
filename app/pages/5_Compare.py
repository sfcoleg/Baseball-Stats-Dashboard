import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import style
import teams

st.set_page_config(page_title="Compare | Diamond Metrics", layout="wide")
st.title("Compare Players")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
seasons = db.get_seasons("batting")
season = st.selectbox("Season", seasons, index=0)


def pick_player(label, key_prefix):
    query = st.text_input(label, key=f"{key_prefix}_query", placeholder="e.g. Ohtani, Judge")
    if not query.strip():
        return None
    matches = db.search_players(query, season, mtime)
    if matches.empty:
        st.warning(f"No players found matching '{query}'.")
        return None
    if len(matches) == 1:
        return matches.iloc[0]
    options = [f"{row.Name} ({row.Tm}) — {row.roles}" for row in matches.itertuples()]
    choice = st.selectbox(f"{len(matches)} matches", options, key=f"{key_prefix}_choice")
    return matches.iloc[options.index(choice)]


col_a, col_b = st.columns(2)
with col_a:
    selected_a = pick_player("Player A", "a")
with col_b:
    selected_b = pick_player("Player B", "b")

if selected_a is None or selected_b is None:
    st.info("Pick two players to compare.")
    st.stop()

if selected_a["mlbID"] == selected_b["mlbID"]:
    st.warning("Pick two different players.")
    st.stop()

st.divider()


def team_badge(row):
    if row is None:
        return "—"
    abbr, _, color = teams.team_meta_from_city(row["Tm"], row.get("Lev"))
    return (
        f"<span style='background-color:{color}66;color:#FAFAFA;padding:3px 10px;"
        f"border-radius:10px;font-weight:600'>{abbr}</span>"
    )


def build_compare_table(row_a, row_b, fields, round_map=None):
    """fields: list of (label, column). Returns a DataFrame indexed by label
    with two columns, one per player. round_map: {label: ndigits}."""
    round_map = round_map or {}
    data = {}
    for label, col in fields:
        val_a = row_a[col] if row_a is not None else None
        val_b = row_b[col] if row_b is not None else None
        ndigits = round_map.get(label)
        if ndigits is not None:
            val_a = round(val_a, ndigits) if val_a is not None and not pd.isna(val_a) else val_a
            val_b = round(val_b, ndigits) if val_b is not None and not pd.isna(val_b) else val_b
        data[label] = [val_a, val_b]
    return pd.DataFrame(data, index=[selected_a["Name"], selected_b["Name"]]).T


batting_a = db.get_player_batting(selected_a["mlbID"], season, mtime)
batting_b = db.get_player_batting(selected_b["mlbID"], season, mtime)
pitching_a = db.get_player_pitching(selected_a["mlbID"], season, mtime)
pitching_b = db.get_player_pitching(selected_b["mlbID"], season, mtime)
fielding_a = db.get_player_fielding(selected_a["mlbID"], season, mtime)
fielding_b = db.get_player_fielding(selected_b["mlbID"], season, mtime)

qualified_batting = db.load_batting(season, mtime)
qualified_batting = qualified_batting[qualified_batting["PA"] >= 50]
qualified_pitching = db.load_pitching(season, mtime)
qualified_pitching = qualified_pitching[qualified_pitching["IP"] >= 20]

h1, h2 = st.columns(2)
h1.image(style.headshot_url(selected_a["mlbID"], width=150), width=110)
h1.markdown(f"### {selected_a['Name']} {team_badge(batting_a if batting_a is not None else pitching_a)}", unsafe_allow_html=True)
h2.image(style.headshot_url(selected_b["mlbID"], width=150), width=110)
h2.markdown(f"### {selected_b['Name']} {team_badge(batting_b if batting_b is not None else pitching_b)}", unsafe_allow_html=True)

if batting_a is not None and batting_b is not None:
    style.colored_header("Batting Profile", "batting")
    radar_fields = [
        ("BA", "BA", False), ("OBP", "OBP", False), ("SLG", "SLG", False),
        ("HR", "HR", False), ("SB", "SB", False), ("BB%", "BB_PCT", False), ("K%", "K_PCT", True),
    ]
    values_a = [db.percentile_rank(qualified_batting[col], batting_a[col], lower) or 0 for _, col, lower in radar_fields]
    values_b = [db.percentile_rank(qualified_batting[col], batting_b[col], lower) or 0 for _, col, lower in radar_fields]
    st.caption("Percentile rank (0-100) against qualified batters (min 50 PA) league-wide.")
    st.plotly_chart(
        style.radar_chart(
            [label for label, _, _ in radar_fields], values_a, values_b,
            selected_a["Name"], selected_b["Name"],
        ),
        use_container_width=True,
    )

if batting_a is not None or batting_b is not None:
    style.colored_header("Batting", "batting")
    std_tab, adv_tab, sc_tab = st.tabs(["Standard", "Advanced", "Statcast"])

    with std_tab:
        fields = [
            ("G", "G"), ("PA", "PA"), ("AB", "AB"), ("R", "R"), ("H", "H"),
            ("HR", "HR"), ("RBI", "RBI"), ("SB", "SB"),
            ("BA", "BA"), ("OBP", "OBP"), ("SLG", "SLG"), ("OPS", "OPS"),
        ]
        table = build_compare_table(
            batting_a, batting_b, fields,
            round_map={"BA": 3, "OBP": 3, "SLG": 3, "OPS": 3},
        )
        st.dataframe(
            style.style_comparison(
                table,
                higher_better=["HR", "RBI", "SB", "R", "H", "BA", "OBP", "SLG", "OPS"],
            ),
            use_container_width=True,
        )

    with adv_tab:
        fields = [
            ("ISO", "ISO"), ("BABIP", "BABIP"), ("K%", "K_PCT"), ("BB%", "BB_PCT"),
            ("wOBA", "wOBA"), ("xwOBA", "xwOBA"), ("WAR", "WAR"), ("OPS+", "OPS_plus"), ("wRC+", "wRC_plus"),
        ]
        table = build_compare_table(
            batting_a, batting_b, fields,
            round_map={"ISO": 3, "BABIP": 3, "K%": 1, "BB%": 1, "wOBA": 3, "xwOBA": 3, "WAR": 1, "OPS+": 0, "wRC+": 0},
        )
        st.dataframe(
            style.style_comparison(
                table,
                higher_better=["ISO", "BB%", "wOBA", "xwOBA", "WAR", "OPS+", "wRC+"],
                lower_better=["K%"],
            ),
            use_container_width=True,
        )

    with sc_tab:
        fields = [
            ("Avg EV", "avg_exit_velo"), ("Max EV", "max_exit_velo"),
            ("Hard-Hit%", "hard_hit_pct"), ("Barrel%", "barrel_pct"),
            ("xBA", "xBA"), ("xSLG", "xSLG"),
        ]
        table = build_compare_table(
            batting_a, batting_b, fields,
            round_map={"Avg EV": 1, "Max EV": 1, "Hard-Hit%": 1, "Barrel%": 1, "xBA": 3, "xSLG": 3},
        )
        st.dataframe(
            style.style_comparison(
                table,
                higher_better=["Avg EV", "Max EV", "Hard-Hit%", "Barrel%", "xBA", "xSLG"],
            ),
            use_container_width=True,
        )

if pitching_a is not None and pitching_b is not None:
    style.colored_header("Pitching Profile", "pitching")
    radar_fields = [
        ("ERA", "ERA", True), ("WHIP", "WHIP", True), ("K/9", "K_9", False),
        ("BB/9", "BB_9", True), ("SV", "SV", False), ("SO", "SO", False),
    ]
    values_a = [db.percentile_rank(qualified_pitching[col], pitching_a[col], lower) or 0 for _, col, lower in radar_fields]
    values_b = [db.percentile_rank(qualified_pitching[col], pitching_b[col], lower) or 0 for _, col, lower in radar_fields]
    st.caption("Percentile rank (0-100) against qualified pitchers (min 20 IP) league-wide.")
    st.plotly_chart(
        style.radar_chart(
            [label for label, _, _ in radar_fields], values_a, values_b,
            selected_a["Name"], selected_b["Name"],
        ),
        use_container_width=True,
    )

if pitching_a is not None or pitching_b is not None:
    style.colored_header("Pitching", "pitching")
    std_tab, adv_tab, sc_tab = st.tabs(["Standard", "Advanced", "Statcast"])

    with std_tab:
        fields = [
            ("G", "G"), ("GS", "GS"), ("W", "W"), ("L", "L"), ("SV", "SV"),
            ("IP", "IP"), ("ERA", "ERA"), ("WHIP", "WHIP"), ("SO", "SO"), ("BB", "BB"),
        ]
        table = build_compare_table(
            pitching_a, pitching_b, fields, round_map={"ERA": 2, "WHIP": 3},
        )
        st.dataframe(
            style.style_comparison(
                table,
                higher_better=["W", "SV", "SO"],
                lower_better=["ERA", "WHIP", "L", "BB"],
            ),
            use_container_width=True,
        )

    with adv_tab:
        fields = [
            ("FIP", "FIP"), ("K/9", "K_9"), ("BB/9", "BB_9"), ("K/BB", "K_BB"),
            ("WAR", "WAR"), ("ERA+", "ERA_plus"),
        ]
        table = build_compare_table(
            pitching_a, pitching_b, fields,
            round_map={"FIP": 2, "K/9": 2, "BB/9": 2, "K/BB": 2, "WAR": 1, "ERA+": 0},
        )
        st.dataframe(
            style.style_comparison(
                table,
                higher_better=["K/9", "K/BB", "WAR", "ERA+"],
                lower_better=["FIP", "BB/9"],
            ),
            use_container_width=True,
        )

    with sc_tab:
        fields = [
            ("Avg EV Against", "avg_exit_velo_against"),
            ("Hard-Hit% Against", "hard_hit_pct_against"),
            ("Barrel% Against", "barrel_pct_against"),
        ]
        table = build_compare_table(
            pitching_a, pitching_b, fields,
            round_map={"Avg EV Against": 1, "Hard-Hit% Against": 1, "Barrel% Against": 1},
        )
        st.dataframe(
            style.style_comparison(
                table,
                lower_better=["Avg EV Against", "Hard-Hit% Against", "Barrel% Against"],
            ),
            use_container_width=True,
        )

if not fielding_a.empty or not fielding_b.empty:
    style.colored_header("Fielding", "fielding")
    positions = sorted(set(fielding_a["Pos"]) | set(fielding_b["Pos"]))
    for pos in positions:
        row_a = fielding_a[fielding_a["Pos"] == pos].iloc[0] if pos in fielding_a["Pos"].values else None
        row_b = fielding_b[fielding_b["Pos"] == pos].iloc[0] if pos in fielding_b["Pos"].values else None
        st.caption(pos)
        fields = [("OAA", "OAA"), ("FRP", "FRP")]
        table = build_compare_table(row_a, row_b, fields)
        st.dataframe(
            style.style_comparison(table, higher_better=["OAA", "FRP"]),
            use_container_width=True,
        )

if batting_a is None and batting_b is None and pitching_a is None and pitching_b is None and fielding_a.empty and fielding_b.empty:
    st.info("No stats found for these players in the selected season.")
