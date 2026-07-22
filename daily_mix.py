"""
Daily Mix generator.

Once a day, for each user, build a personalised playlist entirely from their
own library (songs already known to Butler, i.e. downloaded or previously
resolved) — no external AI/API calls, no network access required.

Scoring, per candidate song:
  - Artist matches one of the user's top-played artists  -> weighted by rank
  - Artist matches one of the user's top-liked artists    -> flat bonus
  - The song itself is liked                              -> flat bonus
  - Never played before                                   -> small discovery bonus
  - Played very recently                                  -> excluded outright

Selection is weighted-random (not just top-N by score) so the mix still
varies day to day instead of freezing on the same songs, and it's reseeded
per (user, date) so re-running on the same day gives the same mix.

We also keep a stable playlist named 'Daily Mix' that we rewrite each day so
the home screen has a known reference.
"""
from __future__ import annotations

import logging
import os
import random
import sys
import time
from datetime import date

# Allow running this script standalone (e.g. from cron/systemd) regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_db  # noqa: E402

MIX_SIZE = 25
RECENT_EXCLUDE = 15  # don't re-suggest the last N played songs
TOP_ARTIST_LIMIT = 8

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("daily_mix")


def fetch_user_signals(db, user_id: int) -> dict:
    """Top played artists (ranked), liked artists, liked song ids, recently played song ids."""
    top_artists = db.execute(
        """
        SELECT s.artist, COUNT(*) c FROM play_history ph
        JOIN songs s ON s.id = ph.song_id
        WHERE ph.user_id=? AND s.artist IS NOT NULL AND s.artist != ''
        GROUP BY s.artist ORDER BY c DESC LIMIT ?
        """,
        (user_id, TOP_ARTIST_LIMIT),
    ).fetchall()
    liked_artists = db.execute(
        """
        SELECT DISTINCT s.artist FROM liked_songs ls
        JOIN songs s ON s.id = ls.song_id
        WHERE ls.user_id=? AND s.artist IS NOT NULL AND s.artist != ''
        """,
        (user_id,),
    ).fetchall()
    liked_song_ids = db.execute(
        "SELECT song_id FROM liked_songs WHERE user_id=?", (user_id,)
    ).fetchall()
    recent_ids = db.execute(
        """
        SELECT song_id FROM play_history WHERE user_id=?
        ORDER BY played_at DESC LIMIT ?
        """,
        (user_id, RECENT_EXCLUDE),
    ).fetchall()
    played_ever = db.execute(
        "SELECT DISTINCT song_id FROM play_history WHERE user_id=?", (user_id,)
    ).fetchall()

    # Rank weight: top artist gets highest weight, tapering off
    artist_rank = {
        r["artist"]: (TOP_ARTIST_LIMIT - i) for i, r in enumerate(top_artists)
    }
    return {
        "artist_rank": artist_rank,
        "liked_artists": {r["artist"] for r in liked_artists},
        "liked_song_ids": {r["song_id"] for r in liked_song_ids},
        "recent_song_ids": {r["song_id"] for r in recent_ids},
        "played_song_ids": {r["song_id"] for r in played_ever},
    }


def score_candidates(db, signals: dict) -> list[tuple[int, float]]:
    """Return [(song_id, weight), ...] for every song eligible for the mix."""
    rows = db.execute(
        "SELECT id, artist FROM songs WHERE downloaded=1"
    ).fetchall()

    weighted: list[tuple[int, float]] = []
    for r in rows:
        sid = r["id"]
        if sid in signals["recent_song_ids"]:
            continue  # don't repeat what they just heard

        weight = 1.0  # baseline so every eligible song has a chance
        artist = r["artist"] or ""
        weight += signals["artist_rank"].get(artist, 0) * 1.5
        if artist in signals["liked_artists"]:
            weight += 4.0
        if sid in signals["liked_song_ids"]:
            weight += 6.0
        if sid not in signals["played_song_ids"]:
            weight += 2.0  # nudge toward stuff they haven't heard yet

        weighted.append((sid, weight))
    return weighted


def weighted_sample(weighted: list[tuple[int, float]], k: int, rng: random.Random) -> list[int]:
    """Weighted sample without replacement, roulette-wheel style."""
    pool = list(weighted)
    chosen: list[int] = []
    while pool and len(chosen) < k:
        total = sum(w for _, w in pool)
        pick = rng.uniform(0, total)
        upto = 0.0
        for idx, (sid, w) in enumerate(pool):
            upto += w
            if upto >= pick:
                chosen.append(sid)
                pool.pop(idx)
                break
    return chosen


def ensure_daily_playlist(db, user_id: int) -> int:
    """Return the playlist id of the user's 'Daily Mix' (creating if needed)."""
    row = db.execute(
        "SELECT id FROM playlists WHERE user_id=? AND name='Daily Mix' LIMIT 1",
        (user_id,),
    ).fetchone()
    if row:
        return row["id"]
    db.execute(
        "INSERT INTO playlists (user_id, name, shared) VALUES (?, 'Daily Mix', 0)",
        (user_id,),
    )
    db.commit()
    return db.execute(
        "SELECT id FROM playlists WHERE user_id=? AND name='Daily Mix' LIMIT 1",
        (user_id,),
    ).fetchone()["id"]


def rewrite_playlist(db, playlist_id: int, song_ids: list[int]) -> None:
    db.execute("DELETE FROM playlist_songs WHERE playlist_id=?", (playlist_id,))
    for sid in song_ids:
        db.execute(
            "INSERT OR IGNORE INTO playlist_songs (playlist_id, song_id) VALUES (?,?)",
            (playlist_id, sid),
        )
    db.commit()


def build_for_user(db, user_id: int, username: str) -> int:
    log.info("Building Daily Mix for %s (id=%d)", username, user_id)
    signals = fetch_user_signals(db, user_id)
    if not signals["played_song_ids"] and not signals["liked_song_ids"]:
        log.info("  no listening data yet, skipping")
        return 0

    weighted = score_candidates(db, signals)
    if not weighted:
        log.info("  no eligible songs in library, skipping")
        return 0

    # Deterministic per (user, day) so re-running today doesn't reshuffle,
    # but tomorrow's run gets a fresh draw.
    rng = random.Random(f"{username}:{date.today().isoformat()}")
    song_ids = weighted_sample(weighted, MIX_SIZE, rng)

    if not song_ids:
        log.info("  selected 0 tracks, skipping")
        return 0

    pid = ensure_daily_playlist(db, user_id)
    rewrite_playlist(db, pid, song_ids)
    log.info("  wrote %d tracks to playlist id=%d", len(song_ids), pid)
    return len(song_ids)


def main() -> int:
    started = time.time()
    db = get_db()
    users = db.execute("SELECT id, username FROM users").fetchall()
    total = 0
    for u in users:
        try:
            total += build_for_user(db, u["id"], u["username"])
        except Exception as e:
            log.exception("Daily mix for %s failed: %s", u["username"], e)
    db.close()
    log.info("Done. %d tracks added across %d users in %.1fs",
              total, len(users), time.time() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
