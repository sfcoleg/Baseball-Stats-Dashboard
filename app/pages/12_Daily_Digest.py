import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))
import articles
import db
import style
import teams

st.set_page_config(page_title="Clubhouse Report | Diamond Metrics", layout="wide")
st.title("Clubhouse Report")

today = db.today_pacific()
yesterday = today - timedelta(days=1)

all_articles = articles.load_articles()
if all_articles:
    style.colored_header("Articles", "headliners")
    for article in all_articles:
        with st.container(border=True):
            st.markdown(f"### {article['title']}")
            byline = " · ".join(p for p in (article["author"], article["date"]) if p)
            if byline:
                st.caption(byline)
            if article.get("image_path") and article["image_path"].exists():
                st.image(str(article["image_path"]), width=320)
            elif article.get("mlbid"):
                st.image(style.headshot_url(article["mlbid"], width=360), width=320)
            st.markdown(article["body"])
    st.divider()

if not db.DB_PATH.exists():
    st.error("No data found yet. Run the ingest script first.")
    st.stop()

mtime = db.db_mtime()
season = db.get_seasons("batting")[0]
recent_batting = db.load_recent_batting(season, mtime)
recent_pitching = db.load_recent_pitching(season, mtime)
milestones = db.get_milestones(season, mtime)

txs = db.load_transactions(2)
txs_yesterday = txs[txs["date"] == yesterday.isoformat()] if not txs.empty else txs
il_moves = txs_yesterday[
    (txs_yesterday["type"] == "Status Change")
    & txs_yesterday["description"].str.contains("injured list", case=False, na=False)
    & ~txs_yesterday["description"].str.contains("activated", case=False, na=False)
] if not txs_yesterday.empty else txs_yesterday

style.colored_header("On This Day", "headliners")
otd = db.load_on_this_day(today.month, today.day)
otd_games, otd_highlights = otd["games"], otd["highlights"]

notable = [g for g in otd_games if g["blowout"]]

# One markdown call for the whole section — each row is still its own
# inline-styled div, but rendering them all through a single st.markdown
# gives them one stElementContainer, and so one bubble, instead of a
# bubble per row.
otd_rows_html = []
if otd_highlights:
    shown_highlights = sorted(otd_highlights, key=lambda h: h["years_ago"])[:8]
    otd_rows_html += [style.on_this_day_highlight_card(h) for h in shown_highlights]

if notable:
    shown_games = sorted(notable, key=lambda g: g["years_ago"])[:6]
    for g in shown_games:
        tag = "Blowout" if g["blowout"] else None
        tag_html = (
            f"<span style='background-color:var(--dm-blue-soft);color:var(--dm-text);padding:2px 8px;"
            f"border-radius:6px;font-weight:700;font-size:0.75rem;margin-left:8px'>{tag}</span>"
            if tag else ""
        )
        otd_rows_html.append(
            f"<div style='background-color:var(--dm-surface-mute);border-left:4px solid var(--dm-blue);padding:8px 14px;"
            f"border-radius:6px;margin:4px 0'>"
            f"<span style='color:var(--dm-dim);font-size:0.85rem'>{g['years_ago']} year{'s' if g['years_ago'] != 1 else ''} ago ({g['year']})</span>"
            f"{tag_html}"
            f"<div style='color:var(--dm-text)'>{g['away_team']} {g['away_score']} @ {g['home_team']} {g['home_score']}</div></div>"
        )

if otd_rows_html:
    st.markdown("<div>" + "".join(otd_rows_html) + "</div>", unsafe_allow_html=True)

if not otd_highlights and not notable:
    # Without this, a date with nothing notable in the past 15 years just
    # renders an empty header and nothing else — reads as broken/stuck
    # rather than "genuinely nothing happened", the same reason Milestones
    # below has its own "Nothing notable yesterday." fallback.
    st.caption("No cycles, big HR games, no-hitters, or blowouts on this date in the past 15 years.")

# Up near the top rather than at the bottom of the page — this section's
# own leaderboard fetch (a single league-wide Statcast pull) can still
# take 30+ seconds cold on its own, since that's one external call that
# can't be split up further, but load_on_this_day above (which used to
# make this whole page feel stuck) is now fast, so there's no longer a
# reason to bury this down at the end.
style.colored_header("Statcast Highlights", "batting")
with st.spinner("Loading Statcast highlights..."):
    leaderboard = db.load_statcast_daily_leaderboard(yesterday.isoformat())
    # The leaderboard only has mlbID + a stat detail (no name/team — Statcast
    # doesn't give us those directly), so look each one up against yesterday's
    # already-loaded recent_batting/recent_pitching, the same player pool that
    # played that date. A player Statcast reports but recent_batting/pitching
    # doesn't (a rare Baseball-Reference/Statcast ID mismatch) is skipped
    # rather than shown without a name/team.
    LEADERBOARD_ENTRIES = [
        ("hardest_hit", "Hardest Hit Ball", recent_batting),
        ("fastest_pitch", "Fastest Pitch", recent_pitching),
        ("longest_hr", "Longest Home Run", recent_batting),
    ]
    matched = []
    for key, label, pool in LEADERBOARD_ENTRIES:
        entry = leaderboard.get(key)
        if not entry or pool.empty:
            continue
        # recent_batting's mlbID column comes back int32, but recent_pitching's
        # comes back as str (a pre-existing dtype quirk, not something to fix
        # broadly here) — compare as strings on both sides so either works.
        match = pool[pool["mlbID"].astype(str) == str(entry["mlbID"])]
        if match.empty:
            continue
        matched.append((key, label, entry, match.iloc[0]))

    # Each entry's highlight clip is its own network round trip — fired off
    # together via a thread pool rather than one at a time, same reasoning
    # as the Milestones section below. "fastest_pitch" is skipped entirely —
    # MLB Film Room's search for it keeps matching the wrong pitch, so a
    # clip is worse than none rather than just unnecessary.
    def _find_clip(args):
        key = args[3]
        return db.find_statcast_highlight(*args) if key != "fastest_pitch" else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        clip_urls = list(pool.map(
            _find_clip,
            [
                (entry["mlbID"], teams.team_meta_from_city(player_row["Tm"], player_row.get("Lev"))[0], yesterday.isoformat(), key, entry["detail"])
                for key, label, entry, player_row in matched
            ],
        ))

for (key, label, entry, player_row), clip_url in zip(matched, clip_urls):
    with st.container(border=True):
        abbr, _, color = teams.team_meta_from_city(player_row["Tm"], player_row.get("Lev"))
        style.milestone_card(entry["mlbID"], player_row["Name"], abbr, color, f"{label}: {entry['detail']}")
        if clip_url:
            st.video(clip_url)
if not matched:
    st.caption("No Statcast data available for this date.")

style.colored_header("Milestones", "headliners")
if milestones:
    # Each milestone's highlight clip is its own network round trip (a
    # schedule lookup + a content/highlights fetch) — fired off together
    # via a thread pool rather than one at a time in the render loop below,
    # since they're independent I/O-bound calls with nothing to gain from
    # running sequentially. Milestones are rare (most days have none), so
    # this rarely matters, but costs nothing when it does.
    milestone_abbrs = [teams.team_meta_from_city(m["Tm"], m.get("Lev"))[0] for m in milestones]
    with ThreadPoolExecutor(max_workers=8) as pool:
        milestone_clips = list(pool.map(
            lambda args: db.find_milestone_highlight(*args),
            [(m["mlbID"], abbr, yesterday.isoformat(), m["category"]) for m, abbr in zip(milestones, milestone_abbrs)],
        ))
    for m, abbr, clip_url in zip(milestones, milestone_abbrs, milestone_clips):
        with st.container(border=True):
            _, _, color = teams.team_meta_from_city(m["Tm"], m.get("Lev"))
            style.milestone_card(m["mlbID"], m["Name"], abbr, color, m["text"])
            if clip_url:
                st.video(clip_url)
else:
    st.caption("Nothing notable yesterday.")

style.colored_header("Biggest Plays", "headliners")
top_plays = db.load_wpa_top_plays(yesterday.year, mtime)
plays_yday = top_plays[top_plays["date"] == yesterday.isoformat()] if not top_plays.empty else top_plays
if plays_yday is not None and not plays_yday.empty:
    batting_names = db.load_batting(yesterday.year, mtime)[["mlbID", "Name"]]
    name_by_id = dict(zip(batting_names["mlbID"], batting_names["Name"]))
    for _, p in plays_yday.sort_values("wpa_batter", key=abs, ascending=False).head(5).iterrows():
        batter_name = name_by_id.get(int(p["batter"]), "")
        swing = abs(p["wpa_batter"]) * 100
        before, after = p["wp_before"] * 100, p["wp_after"] * 100
        desc = p["des"] if isinstance(p["des"], str) and p["des"] else p["events"]
        st.markdown(
            f"<div style='background-color:var(--dm-surface-mute);border-left:4px solid var(--dm-amber);padding:8px 14px;"
            f"border-radius:6px;margin:4px 0'>"
            f"<span style='color:var(--dm-amber);font-weight:700'>{swing:.0f}% swing</span> "
            f"<span style='color:var(--dm-dim);font-size:0.85rem'>home win probability {before:.0f}% → {after:.0f}%"
            + (f" · {batter_name}" if batter_name else "") + "</span>"
            f"<div style='color:var(--dm-text)'>{desc}</div></div>",
            unsafe_allow_html=True,
        )

style.colored_header("Top Batting Performances", "batting")
top_batters = db.top_n_recent_batters(recent_batting, "day", 5)
if top_batters.empty:
    st.caption("No batting data yet.")
else:
    for _, row in top_batters.iterrows():
        with st.container(border=True):
            abbr, _, color = teams.team_meta_from_city(row["Tm"], row.get("Lev"))
            text = style.batting_day_stat_line(row)
            style.milestone_card(row["mlbID"], row["Name"], abbr, color, text)

style.colored_header("Top Pitching Performances", "pitching")
top_pitchers = db.top_n_recent_pitchers(recent_pitching, "day", 5)
if top_pitchers.empty:
    st.caption("No pitching data yet.")
else:
    for _, row in top_pitchers.iterrows():
        with st.container(border=True):
            abbr, _, color = teams.team_meta_from_city(row["Tm"], row.get("Lev"))
            text = style.pitching_day_stat_line(row)
            style.milestone_card(row["mlbID"], row["Name"], abbr, color, text)

style.colored_header("Transactions", "fielding")
if txs_yesterday.empty:
    st.caption("No transactions logged for this date.")
else:
    tx_rows_html = []
    for _, row in txs_yesterday.iterrows():
        badges = ""
        for tabbr in [row["to_abbr"], row["from_abbr"]]:
            if isinstance(tabbr, str):
                color = teams.color_for_abbr(tabbr)
                badges += (
                    f"<span style='background-color:{color}66;color:var(--dm-text);padding:2px 8px;"
                    f"border-radius:6px;font-weight:700;font-size:0.8rem;margin-right:6px'>{tabbr}</span>"
                )
        tx_rows_html.append(
            f"<div style='background-color:var(--dm-surface-mute);border-left:4px solid var(--dm-blue);padding:8px 14px;"
            f"border-radius:6px;margin:4px 0'>{badges}"
            f"<span style='color:var(--dm-dim);font-size:0.85rem'>{row['type']}</span>"
            f"<div style='color:var(--dm-text)'>{row['description']}</div></div>"
        )
    # One markdown call for all rows — one bubble for the section instead
    # of one per transaction.
    st.markdown("<div>" + "".join(tx_rows_html) + "</div>", unsafe_allow_html=True)

style.colored_header("New Injured List Moves", "pitching")
if il_moves.empty:
    st.caption("No new injured-list placements for this date.")
else:
    il_rows_html = [
        f"<div style='background-color:var(--dm-surface-mute);border-left:4px solid var(--dm-red);padding:8px 14px;"
        f"border-radius:6px;margin:4px 0;color:var(--dm-text)'>{row['description']}</div>"
        for _, row in il_moves.iterrows()
    ]
    # One markdown call for all rows — one bubble for the section instead
    # of one per move.
    st.markdown("<div>" + "".join(il_rows_html) + "</div>", unsafe_allow_html=True)
