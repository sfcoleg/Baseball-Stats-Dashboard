"""NHL stat glossary — reached from the small link on the stat-heavy pages
(see nhl/style.py::glossary_link), not from the sidebar nav. Plain
reference content, grouped to match the site's own page sections."""
import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import style

st.set_page_config(page_title="NHL Glossary | Diamond Metrics", layout="wide")
st.title("Stat Glossary")


def _entry(term: str, definition: str):
    st.markdown(f"**{term}** — {definition}")


style.colored_header("Skaters — Standard", "batting")
_entry("GP", "Games played.")
_entry("G / A / P", "Goals, assists, and points (goals + assists).")
_entry("PPG", "Points per game.")
_entry("+/-", "Plus-minus — even-strength and shorthanded goals for minus against while on the ice.")
_entry("PIM", "Penalty minutes.")
_entry("PP G / PP P", "Power-play goals and points.")
_entry("SH G / SH P", "Shorthanded goals and points.")
_entry("GWG / OTG", "Game-winning goals and overtime goals.")
_entry("S", "Shots on goal.")
_entry("S%", "Shooting percentage — goals per shot on goal.")
_entry("TOI/GP", "Time on ice per game, in seconds (1200 = 20:00).")
_entry("FO%", "Faceoff win percentage. Blank for players who don't take draws.")

style.colored_header("Skaters — Possession & Expected Goals", "headliners")
_entry("xG", "Expected goals for a skater's own shots, from MoneyPuck's public model — the number of goals an average shooter would score on those attempts.")
_entry("G − xG", "Goals minus expected goals. Positive means finishing above what the chances were worth.")
_entry("SLOT", "Our own expected-goals model (Shot Location & Outcome Threat) — see below.")
_entry("G − SLOT", "Goals minus SLOT expected goals — the same finishing idea, measured against our model instead of MoneyPuck's.")
_entry("HD xG", "Expected goals from high-danger chances only.")
_entry("xGF% / xGF% 5v5", "Share of the expected goals generated while this player is on the ice — 50% means the team creates as much as it concedes with them out there.")
_entry("Off-ice xGF%", "The same share for the team while the player is on the bench, for comparison.")
_entry("CF% / CF% Rel", "Corsi For percentage — share of all shot attempts (including blocked and missed) while on the ice. \"Rel\" is that number relative to the team's rate without the player.")
_entry("FF% / FF% Rel", "Fenwick For percentage — the same as Corsi but excluding blocked shots.")
_entry("PDO", "On-ice shooting percentage plus on-ice save percentage. A luck gauge that regresses toward 100.")
_entry("OZ Start%", "Share of shifts starting with an offensive-zone faceoff — high numbers mean sheltered deployment.")
_entry("G/60, A/60, P/60, A1/60, A2/60", "Production rates per 60 minutes at 5v5. A1 is primary assists, A2 secondary.")
_entry("Hits / Blocks / TK / GV", "Hits, blocked shots, takeaways, and giveaways.")
_entry("Pen Drawn / Net Pen/60", "Penalties drawn, and penalties drawn minus taken per 60 minutes.")

style.colored_header("Skaters — Special Teams", "pitching")
_entry("PP Shots / PP S%", "Power-play shots on goal and shooting percentage.")
_entry("PPG/60 / PPP/60", "Power-play goals and points per 60 minutes of power-play time.")
_entry("PP TOI/GP / PK TOI/GP", "Power-play and penalty-kill time on ice per game, in seconds.")
_entry("PP Share% / PK Share%", "Share of the team's total power-play or penalty-kill time this player is on for.")
_entry("SHP/60", "Shorthanded points per 60 minutes of penalty-kill time.")
_entry("PPGA/60 (on PK)", "Power-play goals allowed per 60 minutes while this player is killing the penalty.")

style.colored_header("Skaters — Shot Types", "batting")
_entry("Wrist / Snap / Slap / Backhand", "Goals, shots on net, and shooting percentage split by how the shot was taken.")
_entry("Tip / Deflect / Wrap", "Tip-ins, deflections, and wrap-arounds.")

style.colored_header("Goalies", "pitching")
_entry("GS / W / L / OTL", "Games started, wins, losses, and overtime losses.")
_entry("GA / GAA", "Goals against, and goals against average per 60 minutes.")
_entry("SA / SV / SV%", "Shots against, saves, and save percentage.")
_entry("SO", "Shutouts.")
_entry("QS / QS%", "Quality starts — starts with a save percentage at or above league average — and the rate of them.")
_entry("CG / CG% / ICG", "Complete games (not pulled), the rate of them, and incomplete games.")
_entry("SA/60", "Shots faced per 60 minutes — workload.")
_entry("xGA / HD xGA", "Expected goals against on the shots faced, and on high-danger shots only.")
_entry("GSAx", "Goals saved above expected — expected goals against minus actual goals allowed. Positive means stopping more than the shot quality suggested.")
_entry("Team GF / Team GF/GP", "Goal support — what the goalie's team scored in their games.")

style.colored_header("Standings & Team", "headliners")
_entry("PTS", "Points — two for a win, one for an overtime or shootout loss.")
_entry("ROW", "Regulation plus overtime wins, excluding shootout wins. The standard tiebreaker.")
_entry("GD", "Goal differential — goals for minus goals against.")
_entry("L10 / Streak", "Record over the last ten games, and the current winning or losing streak.")
_entry("Clinch marks", "x = clinched a playoff berth, y = clinched the division, z = clinched the conference, p = Presidents' Trophy.")

style.colored_header("Our own models", "headliners")
_entry(
    "SLOT (Shot Location & Outcome Threat)",
    "Our expected-goals model. It rates every unblocked shot attempt on the chance it becomes a "
    "goal, using where it was taken (distance and angle to the net), how (shot type), the game "
    "state (skaters on each side, whether the net is empty), whether it came off a rebound, and "
    "how long since the previous attempt. No player identity is an input, which is what makes "
    "G − SLOT readable as finishing talent rather than a description of who took the shot. "
    "Trained on every unblocked attempt of the season and validated on a holdout of games it "
    "never saw. Blocked shots are excluded because the NHL records them from the blocking "
    "team's point of view, and shootout attempts are excluded as a different kind of event. "
    "It sits alongside MoneyPuck's xG as a second opinion, not a replacement.",
)
_entry(
    "Elo rating",
    "Our team power rating, updated game by game and adjusted for margin of victory, with a "
    "home-ice bonus. It's what drives the win probabilities shown on Today's Games, the "
    "Schedule, and each team's upcoming slate — and it often disagrees with the standings early "
    "in a season, before results catch up to performance.",
)
