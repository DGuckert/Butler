"""
Daily Mix generator.

Once a day, for each user:
  1. Pull the user's top artists + most-played songs from history + likes.
  2. Ask an LLM (via OpenRouter) for ~25 song suggestions in that style.
  3. For each suggestion, resolve a YouTube id (cheap: search_youtube top hit).
  4. Persist songs into the songs table and (re)create a 'Daily Mix YYYY-MM-DD'
     playlist for that user. We also keep a stable playlist named 'Daily Mix'
     that we rewrite each day so the home screen has a known reference.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import date

import requests

# Allow running this script standalone (e.g. from cron/systemd) regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_db                          # noqa: E402
from downloader import search_youtube                # noqa: E402

OPENROUTER_KEY_FILE = os.environ.get("OPENROUTER_KEY_FILE", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

def _read_api_key() -> str:
    if OPENROUTER_API_KEY:
        return OPENROUTER_API_KEY
    if OPENROUTER_KEY_FILE:
        try:
            return open(OPENROUTER_KEY_FILE).read().strip()
        except Exception:
            return ""
    return ""

MIX_SIZE = 25

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("daily_mix")


def fetch_user_seed(db, user_id: int) -> dict:
    """Build the prompt seed: top artists, recent plays, top liked artists."""
    top_artists = db.execute(
        """
        SELECT s.artist, COUNT(*) c FROM play_history ph
        JOIN songs s ON s.id = ph.song_id
        WHERE ph.user_id=? AND s.artist IS NOT NULL AND s.artist != ''
        GROUP BY s.artist ORDER BY c DESC LIMIT 8
        """,
        (user_id,),
    ).fetchall()
    liked_artists = db.execute(
        """
        SELECT s.artist, COUNT(*) c FROM liked_songs ls
        JOIN songs s ON s.id = ls.song_id
        WHERE ls.user_id=? AND s.artist IS NOT NULL AND s.artist != ''
        GROUP BY s.artist ORDER BY c DESC LIMIT 8
        """,
        (user_id,),
    ).fetchall()
    recent = db.execute(
        """
        SELECT s.title, s.artist FROM play_history ph
        JOIN songs s ON s.id = ph.song_id
        WHERE ph.user_id=? ORDER BY ph.played_at DESC LIMIT 12
        """,
        (user_id,),
    ).fetchall()
    return {
        "top_artists": [r["artist"] for r in top_artists if r["artist"]],
        "liked_artists": [r["artist"] for r in liked_artists if r["artist"]],
        "recent": [f"{r['title']} — {r['artist']}" for r in recent],
    }


def ask_llm(seed: dict) -> list[dict]:
    """Returns [{title, artist}, ...] suggestions."""
    artists = ", ".join(seed["top_artists"][:8]) or "(none yet)"
    liked = ", ".join(seed["liked_artists"][:8]) or "(none)"
    recent = "\n".join(seed["recent"][:10]) or "(none)"

    prompt = (
        f"You are building a personalised daily mix for a music listener.\n"
        f"Top played artists: {artists}\n"
        f"Top liked artists: {liked}\n"
        f"Recently played:\n{recent}\n\n"
        f"Suggest {MIX_SIZE} songs they would likely enjoy. Mix familiar artists "
        f"with adjacent / similar acts. Avoid suggesting tracks already in their "
        f"'Recently played' list. Output ONLY a JSON array of objects with keys "
        f"'title' and 'artist'. No prose, no markdown fence."
    )
    api_key = _read_api_key()
    if not api_key:
        log.error("OpenRouter API key missing (set OPENROUTER_API_KEY or OPENROUTER_KEY_FILE)")
        return []
    log.info("Querying OpenRouter (%s) with %d top artists, %d recent",
             OPENROUTER_MODEL, len(seed['top_artists']), len(seed['recent']))
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://butler.local",
            "X-Title": "Butler Music Daily Mix",
        },
        json={
            "model": OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens": 1200,
        },
        timeout=60,
    )
    if resp.status_code >= 400:
        log.warning("OpenRouter HTTP %s: %s", resp.status_code, resp.text[:300])
        return []
    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        log.warning("Unexpected OpenRouter response: %s", str(data)[:300])
        return []
    # Extract first JSON array we can find
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        log.warning("No JSON array in response: %s", text[:200])
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        log.warning("JSON parse failed: %s", e)
        return []
    out = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        artist = (item.get("artist") or "").strip()
        if title and artist:
            out.append({"title": title, "artist": artist})
    return out


def resolve_to_youtube(db, title: str, artist: str) -> str | None:
    """Return a youtube_id for (title, artist), reusing existing rows."""
    title_key = f"{title.lower()}|{artist.lower()}"
    row = db.execute(
        "SELECT youtube_id FROM songs WHERE title_key=? OR (LOWER(title)=? AND LOWER(artist)=?)",
        (title_key, title.lower(), artist.lower()),
    ).fetchone()
    if row and row["youtube_id"]:
        return row["youtube_id"]
    # Fall back to YouTube search
    try:
        hits = search_youtube(f"{title} {artist}", max_results=1)
    except Exception as e:
        log.warning("search_youtube failed for %r %r: %s", title, artist, e)
        return None
    if not hits:
        return None
    h = hits[0]
    yid = h.get("youtube_id")
    if not yid:
        return None
    # Persist for next time
    try:
        thumb = f"https://img.youtube.com/vi/{yid}/mqdefault.jpg"
        db.execute(
            "INSERT OR IGNORE INTO songs "
            "(title, artist, duration, youtube_id, downloaded, title_key, thumbnail) "
            "VALUES (?,?,?,?,0,?,?)",
            (h["title"] or title, h["artist"] or artist, h.get("duration") or 0,
             yid, title_key, thumb),
        )
        db.commit()
    except Exception:
        pass
    return yid


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
    seed = fetch_user_seed(db, user_id)
    if not seed["top_artists"] and not seed["liked_artists"] and not seed["recent"]:
        log.info("  no listening data yet, skipping")
        return 0

    suggestions = ask_llm(seed)
    log.info("  LLM returned %d suggestions", len(suggestions))
    if not suggestions:
        return 0

    song_ids: list[int] = []
    seen_yids: set[str] = set()
    for s in suggestions:
        yid = resolve_to_youtube(db, s["title"], s["artist"])
        if not yid or yid in seen_yids:
            continue
        seen_yids.add(yid)
        row = db.execute("SELECT id FROM songs WHERE youtube_id=?", (yid,)).fetchone()
        if row:
            song_ids.append(row["id"])
        if len(song_ids) >= MIX_SIZE:
            break

    if not song_ids:
        log.info("  resolved 0 tracks, skipping")
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
