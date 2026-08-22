"""NHL Game Center — one game in full: score and status, three stars,
goal-by-goal scoring summary, a shot map of every attempt by both teams
on one rink, shots by period, penalties, and full box scores. Live games
refresh every 20 seconds (the underlying loaders have a 20s TTL).

Reached from Today's Games and the Daily Digest (st.switch_page with
nhl_selected_game set), or directly via ?game=<gameId>. Not in the nav."""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style
from nhl import db as ndb
from nhl import style as nstyle
from nhl import teams as nteams

st.set_page_config(page_title="NHL Game Center | Diamond Metrics", layout="wide")

if "nhl_selected_game" not in st.session_state and "game" in st.query_params:
    try:
        st.session_state["nhl_selected_game"] = int(st.query_params["game"])
    except (TypeError, ValueError):
        pass
if "nhl_selected_game" not in st.session_state:
    st.title("Game Center")
    st.info("Open a game from Today's Games or the Daily Digest.")
    st.stop()
game_id = int(st.session_state["nhl_selected_game"])
if st.query_params.get("game") != str(game_id):
    st.query_params["game"] = str(game_id)

landing = ndb.load_game_landing(game_id)
if not landing:
    st.title("Game Center")
    st.error("Couldn't load this game — the NHL's API may be temporarily down.")
    st.stop()

away, home = landing["awayTeam"], landing["homeTeam"]
a_abbr, h_abbr = away["abbrev"], home["abbrev"]
a_color, h_color = nteams.color_for_abbr(a_abbr), nteams.color_for_abbr(h_abbr)
state = landing.get("gameState")
is_final = state in ("OFF", "FINAL")
is_live = state in ("LIVE", "CRIT")
started = is_final or is_live
season = int(str(landing.get("season", "20252026"))[:4])


def _name(obj) -> str:
    if not obj:
        return ""
    if isinstance(obj, dict) and "default" in obj:
        return obj["default"]
    first = (obj.get("firstName") or {}).get("default", "")
    last = (obj.get("lastName") or {}).get("default", "")
    return f"{first} {last}".strip() or (obj.get("name") or {}).get("default", "")


def _status_line() -> str:
    if is_final:
        last = (landing.get("gameOutcome") or {}).get("lastPeriodType") or (landing.get("periodDescriptor") or {}).get("periodType", "REG")
        return "Final" if last == "REG" else f"Final / {last}"
    if is_live:
        pd_ = landing.get("periodDescriptor") or {}
        clock = (landing.get("clock") or {})
        label = {"REG": f"Period {pd_.get('number')}", "OT": "Overtime", "SO": "Shootout"}.get(pd_.get("periodType"), "Live")
        if clock.get("inIntermission"):
            return f"{label} — Intermission"
        return f"{label} — {clock.get('timeRemaining', '')}"
    try:
        utc = datetime.fromisoformat(landing["startTimeUTC"].replace("Z", "+00:00"))
        return utc.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")
    except Exception:
        return "Scheduled"


# --- Header -----------------------------------------------------------------
@st.fragment(run_every=20 if is_live else None)
def _render():
    landing = ndb.load_game_landing(game_id)
    away, home = landing["awayTeam"], landing["homeTeam"]

    def _side(team, color, align):
        return (
            f"<div style='text-align:{align};flex:1'>"
            f"<img src='{team.get('logo', '')}' style='height:64px;width:64px;object-fit:contain'>"
            f"<div style='margin-top:4px'><span style='background-color:{color}66;color:#FAFAFA;padding:2px 10px;"
            f"border-radius:8px;font-weight:700'>{team['abbrev']}</span></div>"
            f"<div style='font-weight:700;font-size:1.1rem;margin-top:4px'>{nteams.nickname_for_abbr(team['abbrev'])}</div>"
            f"<div style='color:#9AA3B5;font-size:0.85rem'>SOG {team.get('sog', '—')}</div></div>"
        )

    score_html = (
        f"<div style='font-size:3rem;font-weight:800'>{away.get('score', 0)} – {home.get('score', 0)}</div>"
        if started else "<div style='font-size:2rem;color:#9AA3B5'>@</div>"
    )
    live_badge = (
        "<span style='background-color:#D32F2F;color:#FFF;padding:3px 12px;border-radius:8px;"
        "font-weight:700;font-size:0.75rem;letter-spacing:0.5px'>LIVE</span> " if is_live else ""
    )
    venue = (landing.get("venue") or {}).get("default", "")
    st.markdown(
        "<div style='display:flex;align-items:center;gap:16px;padding:12px 0'>"
        + _side(away, a_color, "right")
        + f"<div style='text-align:center;flex:0 0 200px'>{score_html}"
        f"<div style='margin-top:4px'>{live_badge}<span style='color:#9AA3B5'>{_status_line()}</span></div>"
        f"<div style='color:#9AA3B5;font-size:0.8rem'>{venue}</div></div>"
        + _side(home, h_color, "left") + "</div>",
        unsafe_allow_html=True,
    )

    if not started:
        p_home = ndb.game_win_prob(h_abbr, a_abbr)
        if p_home is not None:
            st.caption(f"Our Elo model: {a_abbr} {100 * (1 - p_home):.0f}% — {h_abbr} {100 * p_home:.0f}%")
        return

    summary = landing.get("summary") or {}

    # --- Three stars ---------------------------------------------------------
    stars = summary.get("threeStars") or []
    if stars:
        style.colored_header("Three Stars", "headliners")
        cols = st.columns(3)
        for col, s in zip(cols, stars):
            tm = s.get("teamAbbrev", "")
            color = nteams.color_for_abbr(tm)
            if s.get("position") == "G":
                line = f"{s.get('savePctg', 0) * 100:.1f} SV%, {s.get('goalsAgainst', 0)} GA" if "savePctg" in s else "Goalie"
            else:
                line = f"{s.get('goals', 0)} G, {s.get('assists', 0)} A"
            with col:
                with st.container(border=True):
                    st.markdown(
                        f"<div style='display:flex;align-items:center;gap:12px'>"
                        f"<img src='{s.get('headshot', '')}' style='width:64px;height:64px;border-radius:10px;object-fit:cover;"
                        f"object-position:center 15%;background:#1A1F2E'>"
                        f"<div><div style='color:#F5B942;font-weight:700;font-size:0.8rem'>{'★' * int(s.get('star', 1))} STAR {s.get('star')}</div>"
                        f"<div style='font-size:1.1rem;font-weight:700'><a href='{nstyle.player_link(s['playerId'], season)}' target='_self' "
                        f"style='color:inherit;text-decoration:none'>{_name(s.get('name'))}</a> "
                        f"<span style='background-color:{color}66;color:#FAFAFA;padding:2px 8px;border-radius:6px;font-size:0.7em;font-weight:600'>{tm}</span></div>"
                        f"<div style='color:#93C5FD;font-weight:600;font-size:0.9rem'>{line}</div></div></div>",
                        unsafe_allow_html=True,
                    )

    # --- Scoring summary ---------------------------------------------------------
    style.colored_header("Scoring", "batting")
    periods = summary.get("scoring") or []
    any_goal = False
    for per in periods:
        goals = per.get("goals") or []
        if not goals:
            continue
        any_goal = True
        pd_ = per.get("periodDescriptor") or {}
        label = {"REG": f"Period {pd_.get('number')}", "OT": "Overtime", "SO": "Shootout"}.get(pd_.get("periodType"), f"Period {pd_.get('number')}")
        st.markdown(f"**{label}**")
        for g in goals:
            tm = (g.get("teamAbbrev") or {}).get("default", "")
            color = nteams.color_for_abbr(tm)
            assists = ", ".join(
                f"{_name(a.get('name'))} ({a.get('assistsToDate', '')})" for a in (g.get("assists") or [])
            ) or "Unassisted"
            strength = {"pp": "PP", "sh": "SH"}.get(g.get("strength"), "")
            modifier = g.get("goalModifier", "")
            tags = " ".join(
                f"<span style='background-color:#3B4A8244;color:#93C5FD;padding:1px 7px;border-radius:6px;font-size:0.75rem;font-weight:700'>{t}</span>"
                for t in (strength, "EN" if modifier == "empty-net" else "", "PS" if modifier == "penalty-shot" else "") if t
            )
            clip = g.get("highlightClipSharingUrl")
            clip_html = f" <a href='{clip}' target='_blank' style='color:#9AA3B5;font-size:0.8rem'>▶ clip</a>" if clip else ""
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;padding:4px 0;border-top:1px solid #2A3347'>"
                f"<span style='color:#9AA3B5;width:48px;flex-shrink:0'>{g.get('timeInPeriod', '')}</span>"
                f"<span style='background-color:{color}66;color:#FAFAFA;padding:2px 8px;border-radius:6px;font-weight:700;flex-shrink:0'>{tm}</span>"
                f"<img src='{g.get('headshot', '')}' style='width:32px;height:32px;border-radius:6px;object-fit:cover;object-position:center 15%;background:#1A1F2E'>"
                f"<div style='flex:1'><a href='{nstyle.player_link(g['playerId'], season)}' target='_self' style='color:inherit;text-decoration:none;font-weight:700'>"
                f"{_name(g)}</a> <span style='color:#9AA3B5'>({g.get('goalsToDate', '')})</span> {tags}{clip_html}"
                f"<div style='color:#9AA3B5;font-size:0.85rem'>{assists}</div></div>"
                f"<span style='font-weight:700;flex-shrink:0'>{g.get('awayScore', '')} – {g.get('homeScore', '')}</span></div>",
                unsafe_allow_html=True,
            )
    if not any_goal:
        st.caption("No goals yet.")

    # --- Shot map + shots by period -------------------------------------------------
    shots = ndb.load_game_shots(game_id)
    if not shots.empty:
        style.colored_header("Shot Map", "chart")
        st.caption(f"Every attempt. {a_abbr} shoots left, {h_abbr} shoots right. Stars are goals; hover for the shooter.")
        fig = go.Figure()
        nstyle.rink_outline(fig)
        for is_home, abbr, color in ((False, a_abbr, a_color), (True, h_abbr, h_color)):
            sub = shots[shots["is_home"] == is_home]
            for result, symbol, size, alpha in (("blocked-shot", "x", 7, 0.45), ("missed-shot", "circle-open", 7, 0.7),
                                                ("shot-on-goal", "circle", 9, 0.9), ("goal", "star", 16, 1.0)):
                r = sub[sub["result"] == result]
                if r.empty:
                    continue
                # Goals are yellow stars on both sides; the team-colored
                # outline is what says whose goal it was.
                is_goal = result == "goal"
                fig.add_trace(go.Scatter(
                    x=r["x"], y=r["y"], mode="markers",
                    name=f"{abbr} {nstyle._RESULT_LABELS[result].lower()} ({len(r)})",
                    marker=dict(color="#FACC15" if is_goal else color, symbol=symbol, size=size, opacity=alpha,
                                line=dict(width=2 if is_goal else 1, color=color if is_goal else "#FFFFFF")),
                    text=[f"{s.shooter} — P{s.period} {s.time} ({s.shotType or ''})" for s in r.itertuples()],
                    hoverinfo="text",
                ))
        nstyle.rink_layout(fig, height=460, legend=dict(orientation="h", yanchor="bottom", y=-0.08, x=0, font=dict(size=11)))
        st.plotly_chart(fig, use_container_width=True)

        on_net = shots[shots["result"].isin(["goal", "shot-on-goal"])]
        by_period = on_net.groupby(["period", "is_home"]).size().unstack(fill_value=0)
        if not by_period.empty:
            table = pd.DataFrame({
                "Period": [{"4": "OT"}.get(str(p), str(p)) for p in by_period.index],
                a_abbr: by_period.get(False, 0).values, h_abbr: by_period.get(True, 0).values,
            })
            total = pd.DataFrame({"Period": ["Total"], a_abbr: [table[a_abbr].sum()], h_abbr: [table[h_abbr].sum()]})
            st.markdown("**Shots on goal by period**")
            st.dataframe(pd.concat([table, total], ignore_index=True), hide_index=True, use_container_width=False)

    # --- Penalties ---------------------------------------------------------------------
    pens = [(per, p) for per in (summary.get("penalties") or []) for p in (per.get("penalties") or [])]
    if pens:
        style.colored_header("Penalties", "fielding")
        rows = []
        for per, p in pens:
            pd_ = per.get("periodDescriptor") or {}
            rows.append({
                "Period": {"REG": str(pd_.get("number")), "OT": "OT"}.get(pd_.get("periodType"), str(pd_.get("number"))),
                "Time": p.get("timeInPeriod", ""), "Team": (p.get("teamAbbrev") or {}).get("default", ""),
                "Player": _name(p.get("committedByPlayer")) or "Bench",
                "Penalty": (p.get("descKey") or "").replace("-", " ").title(),
                "Min": p.get("duration", ""), "Drawn by": _name(p.get("drawnBy")),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    # --- Box score ----------------------------------------------------------------------
    box = ndb.load_game_boxscore(game_id)
    pbs = (box or {}).get("playerByGameStats") or {}
    if pbs:
        style.colored_header("Box Score", "pitching")
        tab_a, tab_h = st.tabs([f"{a_abbr} — {nteams.nickname_for_abbr(a_abbr)}", f"{h_abbr} — {nteams.nickname_for_abbr(h_abbr)}"])
        for tab, key, color in ((tab_a, "awayTeam", a_color), (tab_h, "homeTeam", h_color)):
            team = pbs.get(key) or {}
            skaters = (team.get("forwards") or []) + (team.get("defense") or [])
            with tab:
                if skaters:
                    sk = pd.DataFrame([{
                        "Player": _name(s.get("name")), "Pos": s.get("position"), "G": s.get("goals", 0),
                        "A": s.get("assists", 0), "P": s.get("points", 0), "+/-": s.get("plusMinus", 0),
                        "SOG": s.get("sog", 0), "Hits": s.get("hits", 0), "Blk": s.get("blockedShots", 0),
                        "PIM": s.get("pim", 0), "TOI": s.get("toi", ""),
                        "FO%": round(s["faceoffWinningPctg"] * 100) if s.get("faceoffWinningPctg") else float("nan"),
                    } for s in skaters]).sort_values(["P", "G", "SOG"], ascending=False)
                    st.dataframe(sk, hide_index=True, use_container_width=True, height=min(600, 38 * (len(sk) + 1)))
                goalies = team.get("goalies") or []
                if goalies:
                    gl = pd.DataFrame([{
                        "Goalie": _name(g.get("name")), "Dec": g.get("decision", ""), "Saves": g.get("saves", 0),
                        "Shots": g.get("shotsAgainst", 0), "GA": g.get("goalsAgainst", 0),
                        "SV%": round(g["savePctg"] * 100, 1) if g.get("savePctg") is not None else None,
                        "TOI": g.get("toi", ""),
                    } for g in goalies])
                    st.dataframe(gl, hide_index=True, use_container_width=True)


_render()
