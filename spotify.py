"""
Spotify OAuth Authorization Code flow.

Why not Client Credentials? Spotify locks playlist endpoints behind a user
context for dev-mode apps post-Nov 2024 — every request returns 403 Forbidden
with no detail. The only stable workaround is to authorize ONCE as a real
Spotify user and keep that user's refresh token.

One-time setup (the user does this — see frontend "Connect Spotify" flow):
  1. Add SPOTIFY_REDIRECT_URI to .env (e.g. http://dgserver.local:8080/spotify/auth/callback)
  2. Add the same URI to the Spotify dev dashboard → Edit Settings → Redirect URIs
  3. Visit Butler → Import from Spotify → Connect Spotify, log in, allow
  4. The refresh token is saved in butler.db (spotify_auth table)

After that, any playlist visible to the authorizing account is importable.
"""

import re
import time
import base64
import secrets
import asyncio
import httpx
from urllib.parse import urlencode
from typing import Optional

from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI
from database import get_db

# Scopes: read public + private + collaborative playlists. No write, no library.
SCOPES = "playlist-read-private playlist-read-collaborative"

# In-process access-token cache (refresh tokens live in the DB)
_TOKEN_CACHE: dict = {"token": None, "expires": 0.0}
_TOKEN_LOCK = asyncio.Lock()

# Short-lived OAuth state values waiting for a callback (state -> created_at)
_PENDING_STATE: dict = {}


# ── URL parsing ───────────────────────────────────────────────────────────────

def extract_playlist_id(url: str) -> str:
    s = (url or "").strip()
    patterns = [
        r"spotify:playlist:([A-Za-z0-9]+)",
        r"open\.spotify\.com/(?:embed/)?playlist/([A-Za-z0-9]+)",
        r"^([A-Za-z0-9]{22})$",
    ]
    for p in patterns:
        m = re.search(p, s)
        if m:
            return m.group(1)
    raise ValueError("Could not parse Spotify playlist URL")


# ── OAuth state helpers ───────────────────────────────────────────────────────

def make_state() -> str:
    state = secrets.token_urlsafe(16)
    _PENDING_STATE[state] = time.time()
    # GC anything older than 10 minutes
    cutoff = time.time() - 600
    for k in [k for k, t in _PENDING_STATE.items() if t < cutoff]:
        _PENDING_STATE.pop(k, None)
    return state


def consume_state(state: str) -> bool:
    if state and state in _PENDING_STATE:
        _PENDING_STATE.pop(state, None)
        return True
    return False


# ── Authorize URL ─────────────────────────────────────────────────────────────

def build_auth_url(state: str) -> str:
    if not SPOTIFY_CLIENT_ID:
        raise Exception("SPOTIFY_CLIENT_ID is not set in .env")
    if not SPOTIFY_REDIRECT_URI:
        raise Exception("SPOTIFY_REDIRECT_URI is not set in .env")
    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "state": state,
        "scope": SCOPES,
        "show_dialog": "false",
    }
    return "https://accounts.spotify.com/authorize?" + urlencode(params)


# ── Token exchange / refresh ──────────────────────────────────────────────────

def _basic_header() -> str:
    return "Basic " + base64.b64encode(
        f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()


async def exchange_code(code: str) -> dict:
    """Exchange an auth code for {access_token, refresh_token, expires_in, scope}."""
    if not SPOTIFY_CLIENT_SECRET:
        raise Exception("SPOTIFY_CLIENT_SECRET is not set in .env")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            headers={
                "Authorization": _basic_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": SPOTIFY_REDIRECT_URI,
            },
        )
    if r.status_code != 200:
        raise Exception(f"Token exchange failed ({r.status_code}): {r.text[:200]}")
    return r.json()


async def _refresh_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            headers={
                "Authorization": _basic_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
    if r.status_code != 200:
        # Spotify returns 400 + "invalid_grant" when the refresh token is dead
        try:
            err = r.json().get("error", "")
        except Exception:
            err = ""
        if r.status_code == 400 and err == "invalid_grant":
            _clear_refresh_token()
            raise Exception("Spotify connection expired — please reconnect on the Import page.")
        raise Exception(f"Spotify token refresh failed ({r.status_code}): {r.text[:200]}")
    return r.json()


# ── DB-backed refresh-token storage ───────────────────────────────────────────

def _load_refresh_token() -> Optional[str]:
    db = get_db()
    row = db.execute("SELECT refresh_token FROM spotify_auth WHERE id=1").fetchone()
    db.close()
    return row["refresh_token"] if row else None


def save_connection(refresh_token: str, scope: str, user_id: int, username: str) -> None:
    db = get_db()
    # ON CONFLICT lets us overwrite a previous connection cleanly
    db.execute("""
        INSERT INTO spotify_auth (id, refresh_token, scope, connected_by, connected_username, updated_at)
        VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            refresh_token=excluded.refresh_token,
            scope=excluded.scope,
            connected_by=excluded.connected_by,
            connected_username=excluded.connected_username,
            updated_at=CURRENT_TIMESTAMP
    """, (refresh_token, scope, user_id, username))
    db.commit()
    db.close()
    _TOKEN_CACHE["token"] = None
    _TOKEN_CACHE["expires"] = 0.0


def _clear_refresh_token() -> None:
    db = get_db()
    db.execute("DELETE FROM spotify_auth WHERE id=1")
    db.commit()
    db.close()
    _TOKEN_CACHE["token"] = None
    _TOKEN_CACHE["expires"] = 0.0


def disconnect() -> None:
    _clear_refresh_token()


def connection_info() -> dict:
    db = get_db()
    row = db.execute(
        "SELECT connected_username, scope, updated_at FROM spotify_auth WHERE id=1"
    ).fetchone()
    db.close()
    if not row:
        return {"connected": False}
    return {
        "connected": True,
        "username": row["connected_username"],
        "scope": row["scope"],
        "connected_at": row["updated_at"],
    }


# ── Token getter (refreshing) ─────────────────────────────────────────────────

async def _get_user_token() -> str:
    now = time.time()
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["expires"] - 60 > now:
        return _TOKEN_CACHE["token"]

    async with _TOKEN_LOCK:
        now = time.time()
        if _TOKEN_CACHE["token"] and _TOKEN_CACHE["expires"] - 60 > now:
            return _TOKEN_CACHE["token"]

        refresh = _load_refresh_token()
        if not refresh:
            raise Exception("Spotify is not connected. Go to Import from Spotify and click Connect Spotify.")

        data = await _refresh_access_token(refresh)
        _TOKEN_CACHE["token"] = data["access_token"]
        _TOKEN_CACHE["expires"] = time.time() + int(data.get("expires_in", 3600))

        # Spotify sometimes rotates the refresh token; persist the new one if so.
        new_refresh = data.get("refresh_token")
        if new_refresh and new_refresh != refresh:
            db = get_db()
            db.execute(
                "UPDATE spotify_auth SET refresh_token=?, updated_at=CURRENT_TIMESTAMP WHERE id=1",
                (new_refresh,),
            )
            db.commit()
            db.close()

        return _TOKEN_CACHE["token"]


async def fetch_me() -> dict:
    """Return {display_name, id} for the connected Spotify account.
    Used right after the OAuth callback to record who we authorized as.
    Pass an access_token explicitly (we haven't saved the refresh token yet)."""
    raise NotImplementedError("Use fetch_me_with_token instead.")


async def fetch_me_with_token(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://api.spotify.com/v1/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if r.status_code != 200:
        return {"display_name": None, "id": None}
    data = r.json()
    return {"display_name": data.get("display_name") or data.get("id"), "id": data.get("id")}


# ── Playlist fetch ────────────────────────────────────────────────────────────

def _format_error(status: int, body) -> str:
    msg = ""
    if isinstance(body, dict):
        msg = (body.get("error", {}) or {}).get("message") or body.get("error_description") or ""
    if status == 404:
        return ("Playlist not found. Make sure the URL is correct and that the playlist "
                "is visible to the connected Spotify account.")
    if status == 403:
        return (f"Spotify refused the request (403). The playlist may be private to another "
                f"account or region-locked. Details: {msg or 'Forbidden'}")
    if status == 401:
        return "Spotify rejected the access token. Try reconnecting Spotify on the Import page."
    if status == 429:
        return "Spotify rate-limited the request. Try again in a minute."
    return f"Spotify API error ({status}){': ' + msg if msg else ''}"


async def fetch_playlist(playlist_id: str) -> dict:
    """{"name": str, "tracks": [{"title","artist","duration"}], "truncated": bool}

    Reads tracks inline from /v1/playlists/{id} (the /tracks subpath is blocked
    in Spotify dev-mode and 403s — discovered the hard way).
    For playlists > 100 tracks we follow tracks.next; if Spotify 403s the
    continuation we stop and return a partial result with truncated=True.
    """
    token = await _get_user_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    seen = set()
    tracks: list = []
    truncated = False

    def _ingest(items_list):
        for item in items_list or []:
            track = item.get("track") if isinstance(item, dict) else None
            if not track:
                continue
            title = (track.get("name") or "").strip()
            if not title:
                continue
            artists = track.get("artists") or []
            artist = ", ".join(
                (a.get("name") or "").strip()
                for a in artists
                if isinstance(a, dict) and a.get("name")
            ).strip()
            dur_ms = track.get("duration_ms") or 0
            key = (title.lower(), artist.lower())
            if key in seen:
                continue
            seen.add(key)
            tracks.append({
                "title": title,
                "artist": artist,
                "duration": int(dur_ms) // 1000,
            })

    async with httpx.AsyncClient(timeout=20) as client:
        # Single call to the main endpoint — returns playlist meta + first 100 tracks inline.
        r = await client.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}",
            headers=headers,
        )
        if r.status_code == 401:
            _TOKEN_CACHE["expires"] = 0.0
            token = await _get_user_token()
            headers["Authorization"] = f"Bearer {token}"
            r = await client.get(
                f"https://api.spotify.com/v1/playlists/{playlist_id}",
                headers=headers,
            )
        if r.status_code != 200:
            try:
                body = r.json()
            except Exception:
                body = r.text
            raise Exception(_format_error(r.status_code, body))

        data = r.json()
        name = (data.get("name") or "Imported Playlist").strip()

        # Dev-mode Spotify apps get the `tracks` field stripped from this response
        # entirely (the endpoint returns 200 but no tracks key), AND get 403'd on
        # the /v1/playlists/{id}/tracks subpath. Detect this and bail out with a
        # message that actually tells the user what to do.
        if "tracks" not in data:
            raise Exception(
                "Spotify is blocking us from reading playlist tracks "
                "(dev-mode restriction — affects every playlist, even ones you "
                "own). Use the CSV importer below instead: export the playlist "
                "from exportify.net and upload the file."
            )

        tracks_obj = data.get("tracks") or {}
        _ingest(tracks_obj.get("items"))
        next_url = tracks_obj.get("next")

        # Best-effort pagination. /tracks subpath 403s in dev mode — if it does,
        # we accept a partial import rather than failing entirely.
        while next_url:
            r = await client.get(next_url, headers=headers)
            if r.status_code != 200:
                truncated = True
                break
            page = r.json()
            _ingest(page.get("items"))
            next_url = page.get("next")

    return {"name": name, "tracks": tracks, "truncated": truncated}


# Back-compat alias
fetch_playlist_embed = fetch_playlist
