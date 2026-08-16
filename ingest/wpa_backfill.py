"""Computes Win Probability Added (WPA) per player from the cached
play-by-play (ingest/wp_cache/, built by train_wp_model.py) and the fitted
model artifact (app/wp_model.json), then stores compact aggregates in
stats.db — the heavy per-play data never enters the repo database:

  - wpa_batting / wpa_pitching: season aggregates per player (total WPA,
    positive/negative splits, biggest single play).
  - wpa_top_plays: the top plays of each day league-wide (for the Daily
    Digest and Game Center callouts).

Run after training:  python ingest/wpa_backfill.py 2025 2026
The nightly refresh recomputes the current season the same way via
update_season() — cheap because the current season's cache only grows by
one day at a time (refresh_data downloads yesterday's chunk first).
"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
from train_wp_model import (  # noqa: E402
    CACHE_DIR,
    ARTIFACT_PATH,
    baseline_features,
    encode_states,
    load_season_events,
    predict_logistic,
)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.db"
TOP_PLAYS_PER_DAY = 5


def _wp_series(df: pd.DataFrame, artifact: dict) -> np.ndarray:
    """WP (home perspective) for each PA's starting state, with the
    logistic baseline as fallback for states never seen in training."""
    states = artifact["states"]
    p = df["state_key"].map(lambda k: states.get(k, (None,))[0] if k in states else None)
    missing = p.isna()
    if missing.any():
        b = artifact["baseline"]
        xb = baseline_features(df[missing])
        p[missing] = predict_logistic(
            xb, np.array(b["coef"]), b["intercept"], np.array(b["mean"]), np.array(b["std"])
        )
    return p.to_numpy().astype(float)


def compute_season_wpa(season: int) -> pd.DataFrame:
    """Per-play WPA for a whole cached season."""
    plays = _per_play_wpa(load_season_events(season))
    plays["season"] = season
    return plays


def aggregate(plays: pd.DataFrame, season: int) -> dict[str, pd.DataFrame]:
    def _agg(id_col: str, sign: int) -> pd.DataFrame:
        credit = plays["wpa_batter"] * sign
        g = plays.assign(credit=credit).groupby(id_col)
        out = pd.DataFrame({
            "wpa": g["credit"].sum(),
            "wpa_plus": g["credit"].apply(lambda s: s[s > 0].sum()),
            "wpa_minus": g["credit"].apply(lambda s: s[s < 0].sum()),
            "pa": g.size(),
        })
        best_idx = g["credit"].idxmax()
        out["best_play_wpa"] = plays.loc[best_idx, "wpa_batter"].to_numpy() * sign
        out["best_play_desc"] = plays.loc[best_idx, "des"].fillna("").str.slice(0, 200).to_numpy()
        out["best_play_date"] = plays.loc[best_idx, "game_date"].to_numpy()
        out = out.reset_index().rename(columns={id_col: "mlbID"})
        out["season"] = season
        return out

    batting = _agg("batter", +1)
    pitching = _agg("pitcher", -1)

    # League-wide top plays per day (absolute swing, batter perspective).
    plays = plays.assign(abs_swing=plays["wpa_batter"].abs())
    top = (
        plays.sort_values("abs_swing", ascending=False)
        .groupby("game_date")
        .head(TOP_PLAYS_PER_DAY)
        [["game_date", "game_pk", "batter", "pitcher", "events", "des",
          "wpa_batter", "wp_before", "wp_after"]]
        .rename(columns={"game_date": "date"})
    )
    top["season"] = season
    return {"wpa_batting": batting, "wpa_pitching": pitching, "wpa_top_plays": top}


def _store(conn: sqlite3.Connection, table: str, df: pd.DataFrame, season: int) -> None:
    try:
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if existing and existing != set(df.columns):
            conn.execute(f"DROP TABLE {table}")
        else:
            conn.execute(f"DELETE FROM {table} WHERE season = ?", (season,))
    except sqlite3.OperationalError:
        pass
    df.to_sql(table, conn, if_exists="append", index=False)
    conn.commit()


def update_season(season: int) -> None:
    plays = compute_season_wpa(season)
    tables = aggregate(plays, season)
    with sqlite3.connect(DB_PATH) as conn:
        for name, df in tables.items():
            _store(conn, name, df, season)
            print(f"  {name} {season}: {len(df)} rows", flush=True)


def update_day(day: str) -> None:
    """Incremental nightly update: fetch just `day`'s play-by-play from
    Savant, compute its WPA, and fold it into the season aggregates.
    Cache-free on purpose — the deployed nightly refresh has no wp_cache
    directory, only the repo's stats.db and the model artifact."""
    from pybaseball import statcast

    from train_wp_model import EVENT_COLS

    artifact = json.loads(ARTIFACT_PATH.read_text())
    raw = statcast(start_dt=day, end_dt=day, verbose=False)
    if raw is None or raw.empty:
        print(f"  wpa {day}: no games")
        return
    pa = raw[raw["events"].notna() & (raw["events"] != "")]
    pa = pa[[c for c in EVENT_COLS if c in pa.columns]]
    pa = pa.dropna(subset=["inning", "inning_topbot", "outs_when_up", "home_score", "away_score"])
    finals = pa.groupby("game_pk").agg(h=("post_home_score", "max"), a=("post_away_score", "max"))
    finals = finals[finals["h"] != finals["a"]]
    pa = pa[pa["game_pk"].isin(finals.index)]
    if pa.empty:
        print(f"  wpa {day}: no decided games")
        return
    pa = pa.merge((finals["h"] > finals["a"]).rename("home_win"), on="game_pk")
    pa = encode_states(pa)

    season = int(day[:4])
    day_plays = _per_play_wpa(pa)
    day_tables = aggregate(day_plays, season)

    with sqlite3.connect(DB_PATH) as conn:
        for id_table in ("wpa_batting", "wpa_pitching"):
            inc = day_tables[id_table]
            try:
                cur = pd.read_sql(f"SELECT * FROM {id_table} WHERE season=?", conn, params=(season,))
            except pd.errors.DatabaseError:
                cur = pd.DataFrame(columns=inc.columns)
            merged = pd.concat([cur, inc], ignore_index=True)
            agg = merged.groupby(["mlbID", "season"], as_index=False).agg(
                wpa=("wpa", "sum"), wpa_plus=("wpa_plus", "sum"),
                wpa_minus=("wpa_minus", "sum"), pa=("pa", "sum"),
                best_play_wpa=("best_play_wpa", "max"),
            )
            # Keep the description/date belonging to whichever best play won.
            best = merged.sort_values("best_play_wpa", ascending=False).drop_duplicates("mlbID")
            agg = agg.merge(best[["mlbID", "best_play_desc", "best_play_date"]], on="mlbID")
            agg = agg[list(inc.columns)]
            _store(conn, id_table, agg, season)

        top_inc = day_tables["wpa_top_plays"]
        try:
            conn.execute("DELETE FROM wpa_top_plays WHERE date = ?", (day,))
        except sqlite3.OperationalError:
            pass
        top_inc.to_sql("wpa_top_plays", conn, if_exists="append", index=False)
        conn.commit()
    print(f"  wpa {day}: {len(day_plays)} plays folded in")


def _per_play_wpa(df: pd.DataFrame) -> pd.DataFrame:
    """Shared per-play WPA computation for a pre-encoded PA frame."""
    artifact = json.loads(ARTIFACT_PATH.read_text())
    df = df.sort_values(["game_pk", "at_bat_number"]).reset_index(drop=True)
    wp_now = _wp_series(df, artifact)
    next_in_game = df.groupby("game_pk")["state_key"].shift(-1).notna().to_numpy()
    wp_next = np.empty(len(df))
    wp_next[:-1] = wp_now[1:]
    wp_next[-1] = df["home_win"].iloc[-1]
    is_last = ~next_in_game
    wp_next[is_last] = df.loc[is_last, "home_win"].astype(float).to_numpy()
    delta_home = wp_next - wp_now
    batting_home = (df["half"] == 1).to_numpy()
    plays = df[["game_pk", "game_date", "batter", "pitcher", "events", "des",
                "inning", "half", "home_win"]].copy()
    plays["wpa_batter"] = np.where(batting_home, delta_home, -delta_home)
    plays["wp_before"] = wp_now
    plays["wp_after"] = wp_next
    return plays


if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    end = int(sys.argv[2]) if len(sys.argv) > 2 else start
    for yr in range(start, end + 1):
        print(f"=== {yr} ===")
        update_season(yr)
    print("done")
