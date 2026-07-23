"""
Scrobbling: reports finished listens to ListenBrainz.

ListenBrainz was chosen over Last.fm because it only needs a personal user
token (grabbed from listenbrainz.org/profile once, no app registration),
whereas Last.fm requires registering an API application to get an API
key + shared secret and doing an auth handshake -- a lot more setup for
one person's self-hosted server. Last.fm can be added the same way later
if it's ever worth the extra registration step.

Scrobbles are best-effort: any failure (no token configured, network
error, ListenBrainz down) is swallowed so a broken scrobble never
interrupts playback.
"""
import time
import logging
import requests

from database import get_db

log = logging.getLogger("scrobbling")

LISTENBRAINZ_SUBMIT_URL = "https://api.listenbrainz.org/1/submit-listens"
_TIMEOUT = 5


def get_config(user_id: int) -> dict | None:
    db = get_db()
    row = db.execute("SELECT * FROM scrobble_config WHERE user_id=?", (user_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def save_config(user_id: int, listenbrainz_token: str, enabled: bool):
    db = get_db()
    db.execute("""
        INSERT INTO scrobble_config (user_id, listenbrainz_token, enabled)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET listenbrainz_token=excluded.listenbrainz_token,
                                            enabled=excluded.enabled
    """, (user_id, listenbrainz_token, 1 if enabled else 0))
    db.commit()
    db.close()


async def scrobble_for_user(user_id: int, song: dict):
    cfg = get_config(user_id)
    if not cfg or not cfg.get("enabled") or not cfg.get("listenbrainz_token"):
        return

    title = (song.get("title") or "").strip()
    artist = (song.get("artist") or "").strip()
    if not title or not artist:
        return

    payload = {
        "listen_type": "single",
        "payload": [{
            "listened_at": int(time.time()),
            "track_metadata": {
                "artist_name": artist,
                "track_name": title,
                "additional_info": (
                    {"duration": int(song["duration"])} if song.get("duration") else {}
                ),
            },
        }],
    }
    headers = {
        "Authorization": f"Token {cfg['listenbrainz_token']}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(LISTENBRAINZ_SUBMIT_URL, json=payload, headers=headers, timeout=_TIMEOUT)
        if resp.status_code >= 400:
            log.info("ListenBrainz scrobble failed for user %s: %s %s", user_id, resp.status_code, resp.text[:200])
    except Exception as e:
        log.info("ListenBrainz scrobble error for user %s: %s", user_id, e)
