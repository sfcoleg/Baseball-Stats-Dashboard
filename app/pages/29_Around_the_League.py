"""Around the League — Injury Report, Transactions, and Awards Race merged
into one page as tabs (formerly three separate nav pages). Minor Leagues
and Box Score Search deliberately stay as their own pages."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import db
import prefs
import style
import teams

st.set_page_config(page_title="Around the League | Diamond Metrics", layout="wide")
st.title("Around the League")

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
injury_tab, tx_tab, awards_tab = st.tabs(["Injury Report", "Transactions", "Awards Race"])

# --- Injury Report ----------------------------------------------------------
with injury_tab:
    st.caption("Every player currently on a major-league injured list.")
    with st.spinner("Loading injury report..."):
        injuries = db.load_injury_report()

    if injuries.empty:
        st.info("No injured-list data available right now.")
    else:
        team_options = ["All teams"] + sorted(injuries["Tm"].unique().tolist())
        team_filter = st.selectbox("Team", team_options, key="injury_team")
        if team_filter != "All teams":
            injuries = injuries[injuries["Tm"] == team_filter]

        st.caption(
            f"{len(injuries)} players on the injured list"
            + ("" if team_filter == "All teams" else f" for {team_filter}")
        )

        STATUS_ORDER = ["60-Day IL", "15-Day IL", "10-Day IL", "7-Day IL"]
        injuries = injuries.sort_values(
            by="Status", key=lambda s: s.map({v: i for i, v in enumerate(STATUS_ORDER)})
        )

        for _, row in injuries.iterrows():
            color = teams.color_for_abbr(row["Tm"])
            detail = row["Detail"] if isinstance(row["Detail"], str) and row["Detail"] else "No further detail available"
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:14px;background-color:#1B243866;"
                f"border-left:4px solid {color};padding:10px 14px;border-radius:6px;margin:6px 0'>"
                f"<img src='{style.headshot_url(row['mlbID'], width=100)}' style='width:56px;height:56px;"
                f"border-radius:50%;object-fit:cover;object-position:center 25%;flex-shrink:0'>"
                f"<div style='flex-grow:1'>"
                f"<span style='background-color:{color}66;color:#FAFAFA;padding:2px 8px;border-radius:6px;"
                f"font-weight:700;font-size:0.85rem'>{row['Tm']}</span> "
                f"<span style='font-weight:700;font-size:1.05rem'>{row['Name']}</span> "
                f"<span style='color:#9AA3B5'>({row['Position']})</span>"
                f"<div style='color:#DCE1EA;font-size:0.9rem;margin-top:2px'>{detail}</div>"
                f"</div>"
                f"<span style='background-color:#D32F2F33;color:#FF8A80;padding:4px 10px;border-radius:8px;"
                f"font-weight:700;font-size:0.8rem;white-space:nowrap'>{row['Status']}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

# --- Transactions -----------------------------------------------------------
with tx_tab:
    st.caption("Recent MLB roster moves — trades, signings, DFAs, and more.")

    def render_transaction_card(row):
        badges = ""
        for abbr in [row["to_abbr"], row["from_abbr"]]:
            if isinstance(abbr, str):
                color = teams.color_for_abbr(abbr)
                badges += (
                    f"<span style='background-color:{color}66;color:#FAFAFA;padding:2px 8px;"
                    f"border-radius:6px;font-weight:700;font-size:0.8rem;margin-right:6px'>{abbr}</span>"
                )
        st.markdown(
            f"<div style='background-color:#1B243866;border-left:4px solid #3B82F6;padding:10px 14px;"
            f"border-radius:6px;margin:6px 0'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"
            f"<div>{badges}<span style='color:#9AA3B5;font-size:0.85rem'>{row['type']}</span></div>"
            f"<span style='color:#9AA3B5;font-size:0.85rem'>{row['date']}</span>"
            f"</div>"
            f"<div style='color:#DCE1EA'>{row['description']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    window_options = {"Last 3 days": 3, "Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30}
    window_label = st.selectbox("Lookback window", list(window_options.keys()), index=1)
    days = window_options[window_label]

    with st.spinner("Loading transactions..."):
        txs = db.load_transactions(days)

    if txs.empty:
        st.info("No transactions found in this window.")
    else:
        all_types = sorted(txs["type"].dropna().unique().tolist())
        default_types = [t for t in ["Trade", "Signed as Free Agent", "Designated for Assignment", "Released", "Claimed Off Waivers", "Status Change"] if t in all_types]
        type_filter = st.multiselect("Transaction type", all_types, default=default_types or all_types)

        team_abbrs = sorted({a for a in txs["to_abbr"].tolist() + txs["from_abbr"].tolist() if isinstance(a, str)})
        tx_team_filter = st.selectbox("Team", ["All teams"] + team_abbrs, key="tx_team")

        filtered = txs[txs["type"].isin(type_filter)] if type_filter else txs
        if tx_team_filter != "All teams":
            filtered = filtered[(filtered["to_abbr"] == tx_team_filter) | (filtered["from_abbr"] == tx_team_filter)]

        st.caption(f"{len(filtered)} transactions")

        for _, row in filtered.iterrows():
            render_transaction_card(row)

# --- Awards Race ------------------------------------------------------------
with awards_tab:
    seasons = db.get_seasons("batting")
    season = st.selectbox("Season", seasons, index=prefs.default_season_index(seasons))

    def _mvp_table(league: str):
        race = db.mvp_race(season, league, mtime)
        if race.empty:
            st.caption(f"Not enough qualifying batters or pitchers for {league} MVP this season.")
            return
        display = teams.add_team_abbr(race.head(5))
        # Batters and pitchers are scored differently (see mvp_race), so a
        # shared wRC+/BsR/OAA column would be blank for every pitcher row —
        # Streamlit's dataframe grid renders those blanks as the literal text
        # "None" rather than the Styler's na_rep, so those columns are left out
        # of this combined view entirely. Role + WAR + MVP Score is enough to
        # see why each candidate ranks where they do; the batting-only detail
        # is still on that player's own page.
        cols = ["Name", "Tm", "Role", "WAR", "MVP Score"]
        display = display[cols]
        st.dataframe(
            style.style_stats_table(
                display, team_col="Tm", team_color_fn=teams.color_for_abbr,
                precision={"WAR": "{:.1f}", "MVP Score": "{:.2f}"},
            ),
            use_container_width=True, hide_index=True,
        )

    def _cy_young_table(league: str):
        race = db.cy_young_race(season, league, mtime)
        if race.empty:
            st.caption(f"Not enough qualifying pitchers for {league} Cy Young this season.")
            return
        display = teams.add_team_abbr(race.head(5))
        cols = ["Name", "Tm", "WAR", "FIP", "ERA_plus", "IP", "Cy Young Score"]
        display = display[cols].rename(columns={"ERA_plus": "ERA+"})
        st.dataframe(
            style.style_stats_table(
                display, team_col="Tm", team_color_fn=teams.color_for_abbr,
                precision={"WAR": "{:.1f}", "FIP": "{:.2f}", "ERA+": "{:.0f}", "IP": "{:.1f}", "Cy Young Score": "{:.2f}"},
            ),
            use_container_width=True, hide_index=True,
        )

    def _roy_table(league: str):
        race = db.rookie_of_the_year_race(season, league, mtime)
        if race.empty:
            st.caption(f"Not enough rookie-eligible candidates for {league} Rookie of the Year this season.")
            return
        display = teams.add_team_abbr(race.head(5))
        cols = ["Name", "Tm", "Role", "WAR", "ROY Score"]
        st.dataframe(
            style.style_stats_table(
                display[cols], team_col="Tm", team_color_fn=teams.color_for_abbr,
                precision={"WAR": "{:.1f}", "ROY Score": "{:.2f}"},
            ),
            use_container_width=True, hide_index=True,
        )

    style.colored_header("MVP", "batting")
    al_col, nl_col = st.columns(2)
    with al_col:
        st.markdown("**AL**")
        _mvp_table("Maj-AL")
    with nl_col:
        st.markdown("**NL**")
        _mvp_table("Maj-NL")

    style.colored_header("Cy Young", "pitching")
    al_col2, nl_col2 = st.columns(2)
    with al_col2:
        st.markdown("**AL**")
        _cy_young_table("Maj-AL")
    with nl_col2:
        st.markdown("**NL**")
        _cy_young_table("Maj-NL")

    style.colored_header("Rookie of the Year", "fielding")
    al_col3, nl_col3 = st.columns(2)
    with al_col3:
        st.markdown("**AL**")
        _roy_table("Maj-AL")
    with nl_col3:
        st.markdown("**NL**")
        _roy_table("Maj-NL")
