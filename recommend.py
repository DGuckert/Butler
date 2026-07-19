"""
Recommendation engine.
- Pulls top artists from play history + liked songs
- Finds unplayed songs by those artists in songs_meta.db
- Discovery: mix of unheard local tracks + YouTube trending search
"""
import sqlite3
import random
import os
from database import get_db
from songs_db import get_meta_db

def get_recommendations(user_id: int, limit: int = 20) -> list:
    """Songs by artists the user likes/plays, that they haven't played yet."""
    db = get_db()

    # Top artists from play history (last 200 plays)
    history_artists = db.execute("""
        SELECT s.artist, COUNT(*) as c FROM play_history ph
        JOIN songs s ON s.id = ph.song_id
        WHERE ph.user_id = ? AND s.artist IS NOT NULL
        GROUP BY s.artist ORDER BY c DESC LIMIT 20
    """, (user_id,)).fetchall()

    # Artists from liked songs
    liked_artists = db.execute("""
        SELECT s.artist, COUNT(*) as c FROM liked_songs ls
        JOIN songs s ON s.id = ls.song_id
        WHERE ls.user_id = ? AND s.artist IS NOT NULL
        GROUP BY s.artist ORDER BY c DESC LIMIT 20
    """, (user_id,)).fetchall()

    # Already played youtube_ids
    played = db.execute("""
        SELECT DISTINCT s.title_key FROM play_history ph
        JOIN songs s ON s.id = ph.song_id
        WHERE ph.user_id = ?
    """, (user_id,)).fetchall()
    db.close()

    # Merge artists, weight liked > history
    artist_scores = {}
    for row in history_artists:
        artist_scores[row["artist"].lower()] = row["c"]
    for row in liked_artists:
        a = row["artist"].lower()
        artist_scores[a] = artist_scores.get(a, 0) + row["c"] * 2

    if not artist_scores:
        return []

    played_keys = {r["title_key"] for r in played if r["title_key"]}
    top_artists = sorted(artist_scores, key=artist_scores.get, reverse=True)[:15]

    meta = get_meta_db()
    results = []
    per_artist = max(2, limit // len(top_artists))

    for artist_lower in top_artists:
        rows = meta.execute("""
            SELECT title, artist, duration FROM tracks
            WHERE artist_lower = ?
            ORDER BY RANDOM() LIMIT ?
        """, (artist_lower, per_artist * 3)).fetchall()

        for r in rows:
            key = f"{r['title'].lower()}|{r['artist'].lower()}"
            if key not in played_keys:
                results.append({
                    "title": r["title"], "artist": r["artist"],
                    "duration": r["duration"], "youtube_id": None,
                    "downloaded": 0, "source": "recommended"
                })
                if len(results) >= limit:
                    break
        if len(results) >= limit:
            break

    meta.close()
    random.shuffle(results)
    return results[:limit]


def get_discovery(user_id: int, limit: int = 20) -> list:
    """Mix of unheard local tracks + discovery seeds for YouTube."""
    db = get_db()
    played_titles = db.execute("""
        SELECT DISTINCT LOWER(s.title) FROM play_history ph
        JOIN songs s ON s.id = ph.song_id WHERE ph.user_id = ?
    """, (user_id,)).fetchall()
    db.close()

    played_set = {r[0] for r in played_titles}

    meta = get_meta_db()
    # Random unheard tracks from local DB
    rows = meta.execute("""
        SELECT title, artist, duration FROM tracks
        ORDER BY RANDOM() LIMIT 200
    """).fetchall()
    meta.close()

    unheard = [
        {"title": r["title"], "artist": r["artist"], "duration": r["duration"],
         "youtube_id": None, "downloaded": 0, "source": "discovery"}
        for r in rows if r["title"].lower() not in played_set
    ]

    random.shuffle(unheard)
    return unheard[:limit]
