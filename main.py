import re
import sqlite3
import os
import asyncio
import secrets
import log_filter
from fastapi import FastAPI, HTTPException, Depends, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from database import init_db, get_db
from auth import hash_password, verify_password, create_token, get_current_user
from downloader import search_youtube, ensure_downloaded, is_downloading, get_download_progress
from songs_db import search_local, add_track
from recommend import get_recommendations, get_discovery
from config import MUSIC_DIR
from album_art import find_album_art

app = FastAPI(title="Butler")
log_filter.install()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
init_db()

class RegisterRequest(BaseModel):
    username: str
    password: str
    invite_code: str

class LoginRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class CreatePlaylistRequest(BaseModel):
    name: str
    shared: bool = False

class UpdatePlaylistRequest(BaseModel):
    name: Optional[str] = None
    shared: Optional[bool] = None

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/auth/register")
def register(req: RegisterRequest):
    db = get_db()
    is_first_user = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"] == 0

    invite = None
    if not is_first_user:
        # Every account after the first (the admin) needs an invite code.
        # The first user has nobody to get one from, so they bootstrap the
        # server instead of being locked out of their own fresh install.
        invite = db.execute(
            "SELECT * FROM invite_codes WHERE code=? AND used_by IS NULL",
            (req.invite_code.strip(),)
        ).fetchone()
        if not invite:
            db.close(); raise HTTPException(400, "Invalid or already-used invite code")

    if db.execute("SELECT id FROM users WHERE username=?", (req.username,)).fetchone():
        db.close(); raise HTTPException(400, "Username taken")
    db.execute("INSERT INTO users (username, password_hash) VALUES (?,?)",
               (req.username, hash_password(req.password)))
    db.commit()
    user = db.execute("SELECT * FROM users WHERE username=?", (req.username,)).fetchone()
    if invite:
        db.execute("UPDATE invite_codes SET used_by=?, used_at=CURRENT_TIMESTAMP WHERE id=?",
                   (user["id"], invite["id"]))
        db.commit()
    db.close()
    return {"token": create_token(user["id"]), "username": user["username"]}

@app.post("/auth/login")
def login(req: LoginRequest):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=?", (req.username,)).fetchone()
    db.close()
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    return {"token": create_token(user["id"]), "username": user["username"]}

@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    return {"id": user["id"], "username": user["username"], "created_at": user["created_at"]}

@app.post("/auth/change-password")
def change_password(req: ChangePasswordRequest, user=Depends(get_current_user)):
    if not verify_password(req.current_password, user["password_hash"]):
        raise HTTPException(400, "Current password is wrong")
    if len(req.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")
    db = get_db()
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (hash_password(req.new_password), user["id"]))
    db.commit(); db.close()
    return {"updated": True}

# ── Invite codes (admin only) ─────────────────────────────────────────────────

@app.post("/admin/invites")
def create_invite(user=Depends(get_current_user)):
    if user["id"] != 1: raise HTTPException(403, "Admin only")
    code = secrets.token_urlsafe(12)
    db = get_db()
    db.execute("INSERT INTO invite_codes (code, created_by) VALUES (?,?)", (code, user["id"]))
    db.commit(); db.close()
    return {"code": code}

@app.get("/admin/invites")
def list_invites(user=Depends(get_current_user)):
    if user["id"] != 1: raise HTTPException(403, "Admin only")
    db = get_db()
    rows = db.execute("""
        SELECT ic.*, u.username as used_by_name FROM invite_codes ic
        LEFT JOIN users u ON u.id = ic.used_by
        ORDER BY ic.created_at DESC
    """).fetchall()
    db.close()
    return {"invites": [dict(r) for r in rows]}

@app.delete("/admin/invites/{code}")
def delete_invite(code: str, user=Depends(get_current_user)):
    if user["id"] != 1: raise HTTPException(403, "Admin only")
    db = get_db()
    db.execute("DELETE FROM invite_codes WHERE code=? AND used_by IS NULL", (code,))
    db.commit(); db.close()
    return {"deleted": True}

# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/search")
def search(q: str, user=Depends(get_current_user)):
    if not q or len(q.strip()) < 2: raise HTTPException(400, "Query too short")
    db = get_db()
    downloaded = [dict(r) for r in db.execute(
        "SELECT * FROM songs WHERE title LIKE ? OR artist LIKE ? LIMIT 5",
        (f"%{q}%", f"%{q}%")
    ).fetchall()]
    downloaded_titles = {r["title"].lower() for r in downloaded}
    db.close()
    local_meta = [r for r in search_local(q, 10) if r["title"].lower() not in downloaded_titles]
    yt_results = []
    if len(downloaded) + len(local_meta) < 5:
        yt_raw = search_youtube(q, max_results=8)
        known = downloaded_titles | {r["title"].lower() for r in local_meta}
        for r in yt_raw:
            if r["title"].lower() not in known:
                yt_results.append(r); add_track(r["title"], r["artist"], r["duration"])
    return {"results": [r for r in _resolve_song_rows(downloaded + local_meta + yt_results) if r.get("youtube_id")][:10]}

# ── Recommendations ───────────────────────────────────────────────────────────


# ── Helpers for resolving recommended/discovery rows ──────────────────────────
def _resolve_song_rows(rows):
    """Fill youtube_id/duration/thumbnail/downloaded from the songs table.

    Drops rows that we still can't resolve so clients never see null ids.
    """
    if not rows:
        return rows
    db = get_db()
    out = []
    for r in rows:
        if r.get("youtube_id"):
            out.append(r)
            continue
        title = (r.get("title") or "").strip()
        artist = (r.get("artist") or "").strip()
        if not title:
            continue
        key = f"{title.lower()}|{artist.lower()}"
        row = db.execute(
            "SELECT youtube_id, title, artist, duration, thumbnail, downloaded "
            "FROM songs WHERE title_key=? OR (LOWER(title)=? AND LOWER(artist)=?) "
            "LIMIT 1",
            (key, title.lower(), artist.lower()),
        ).fetchone()
        if not row or not row["youtube_id"]:
            continue
        merged = dict(r)
        merged["youtube_id"] = row["youtube_id"]
        merged["duration"] = row["duration"] or merged.get("duration") or 0
        merged["thumbnail"] = row["thumbnail"] or (
            f"https://img.youtube.com/vi/{row['youtube_id']}/mqdefault.jpg"
        )
        merged["downloaded"] = row["downloaded"]
        out.append(merged)
    db.close()
    return out

@app.get("/recommendations")
def recommendations(user=Depends(get_current_user)):
    return {"songs": _resolve_song_rows(get_recommendations(user["id"], limit=40))[:20]}

@app.get("/discovery")
def discovery(user=Depends(get_current_user)):
    return {"songs": _resolve_song_rows(get_discovery(user["id"], limit=40))[:20]}

# ── Play / Stream ─────────────────────────────────────────────────────────────

@app.post("/songs/play/{youtube_id}")
async def play(youtube_id: str, user=Depends(get_current_user)):
    db = get_db()
    song = db.execute("SELECT * FROM songs WHERE youtube_id=?", (youtube_id,)).fetchone()
    if not song:
        results = search_youtube(youtube_id, max_results=1)
        if not results: db.close(); raise HTTPException(404, "Song not found")
        r = results[0]
        title_key = f"{r['title'].lower()}|{(r['artist'] or '').lower()}"
        thumbnail = find_album_art(r["title"], r["artist"], youtube_id)
        db.execute("INSERT OR IGNORE INTO songs (title,artist,duration,youtube_id,downloaded,title_key,thumbnail) VALUES (?,?,?,?,0,?,?)",
                   (r["title"], r["artist"], r["duration"], youtube_id, title_key, thumbnail))
        db.commit(); add_track(r["title"], r["artist"], r["duration"])
        song = db.execute("SELECT * FROM songs WHERE youtube_id=?", (youtube_id,)).fetchone()
    song = dict(song)
    db.execute("INSERT INTO play_history (user_id,song_id) VALUES (?,?)", (user["id"], song["id"]))
    db.commit(); db.close()
    file_path = os.path.join(MUSIC_DIR, f"{youtube_id}.mp3")
    if os.path.exists(file_path):
        return {"status": "ready", "stream_url": f"/songs/stream/{youtube_id}", "song": song}
    if not is_downloading(youtube_id):
        asyncio.create_task(ensure_downloaded(youtube_id))
    return {"status": "downloading", "stream_url": f"/songs/stream/{youtube_id}", "song": song}

@app.post("/songs/resolve")
async def resolve_song(body: dict, user=Depends(get_current_user)):
    q = f"{body.get('title','')} {body.get('artist','')}".strip()
    results = search_youtube(q, max_results=3)
    if not results: raise HTTPException(404, "Could not find on YouTube")
    return results[0]

@app.get("/songs/status/{youtube_id}")
def song_status(youtube_id: str, user=Depends(get_current_user)):
    file_path = os.path.join(MUSIC_DIR, f"{youtube_id}.mp3")
    if os.path.exists(file_path): return {"status": "ready", "progress": 100}
    if is_downloading(youtube_id): return {"status": "downloading", "progress": get_download_progress(youtube_id)}
    return {"status": "not_downloaded", "progress": 0}

@app.get("/songs/stream/{youtube_id}")
async def stream(youtube_id: str, user=Depends(get_current_user)):
    file_path = os.path.join(MUSIC_DIR, f"{youtube_id}.mp3")
    for _ in range(240):
        if os.path.exists(file_path):
            return FileResponse(
                file_path, media_type="audio/mpeg",
                headers={"Cache-Control": "private, max-age=86400", "Accept-Ranges": "bytes"}
            )
        await asyncio.sleep(0.5)
    raise HTTPException(503, "Download timed out")

@app.delete("/songs/{youtube_id}")
def delete_song(youtube_id: str, user=Depends(get_current_user)):
    db = get_db()
    song = db.execute("SELECT * FROM songs WHERE youtube_id=?", (youtube_id,)).fetchone()
    if not song: db.close(); raise HTTPException(404, "Not found")
    song = dict(song)
    path = os.path.join(MUSIC_DIR, f"{youtube_id}.mp3")
    if os.path.exists(path): os.remove(path)
    for tbl in ["liked_songs","play_history","playlist_songs"]:
        col = "song_id"
        db.execute(f"DELETE FROM {tbl} WHERE {col}=?", (song["id"],))
    db.execute("DELETE FROM songs WHERE id=?", (song["id"],))
    db.commit(); db.close()
    return {"deleted": True}

@app.get("/library")
def library(user=Depends(get_current_user),
            sort: str = Query("date", enum=["date","title","artist"]),
            downloaded_only: bool = False):
    db = get_db()
    order = {"date":"added_at DESC","title":"title ASC","artist":"artist ASC"}[sort]
    where = "WHERE downloaded=1" if downloaded_only else ""
    songs = db.execute(f"SELECT * FROM songs {where} ORDER BY {order}").fetchall()
    db.close()
    return {"songs": [dict(s) for s in songs]}

@app.get("/history")
def history(user=Depends(get_current_user),
            limit: int = Query(50, le=200)):
    db = get_db()
    rows = db.execute("""
        SELECT s.*, ph.played_at FROM play_history ph
        JOIN songs s ON s.id=ph.song_id
        WHERE ph.user_id=? ORDER BY ph.played_at DESC LIMIT ?
    """, (user["id"], limit)).fetchall()
    db.close()
    return {"history": [dict(r) for r in rows]}

# ── Liked ─────────────────────────────────────────────────────────────────────

@app.post("/songs/{youtube_id}/like")
def like_song(youtube_id: str, user=Depends(get_current_user)):
    db = get_db()
    song = db.execute("SELECT id FROM songs WHERE youtube_id=?", (youtube_id,)).fetchone()
    if not song: db.close(); raise HTTPException(404, "Not found")
    db.execute("INSERT OR IGNORE INTO liked_songs (user_id,song_id) VALUES (?,?)", (user["id"], song["id"]))
    db.commit(); db.close()
    return {"liked": True}

@app.delete("/songs/{youtube_id}/like")
def unlike_song(youtube_id: str, user=Depends(get_current_user)):
    db = get_db()
    song = db.execute("SELECT id FROM songs WHERE youtube_id=?", (youtube_id,)).fetchone()
    if not song: db.close(); raise HTTPException(404, "Not found")
    db.execute("DELETE FROM liked_songs WHERE user_id=? AND song_id=?", (user["id"], song["id"]))
    db.commit(); db.close()
    return {"liked": False}

@app.get("/liked")
def liked_songs(user=Depends(get_current_user),
                sort: str = Query("date", enum=["date","title","artist"])):
    db = get_db()
    order = {"date":"ls.liked_at DESC","title":"s.title ASC","artist":"s.artist ASC"}[sort]
    rows = db.execute(f"""
        SELECT s.*, ls.liked_at FROM liked_songs ls
        JOIN songs s ON s.id=ls.song_id
        WHERE ls.user_id=? ORDER BY {order}
    """, (user["id"],)).fetchall()
    db.close()
    return {"songs": [dict(r) for r in rows]}

# ── Playlists ─────────────────────────────────────────────────────────────────

@app.post("/playlists")
def create_playlist(req: CreatePlaylistRequest, user=Depends(get_current_user)):
    db = get_db()
    db.execute("INSERT INTO playlists (user_id,name,shared) VALUES (?,?,?)",
               (user["id"], req.name, 1 if req.shared else 0))
    db.commit()
    p = db.execute("SELECT * FROM playlists WHERE user_id=? ORDER BY id DESC LIMIT 1", (user["id"],)).fetchone()
    db.close()
    return dict(p)

@app.get("/playlists")
def get_playlists(user=Depends(get_current_user)):
    db = get_db()
    rows = db.execute("""
        SELECT p.*, u.username as owner_name FROM playlists p
        JOIN users u ON u.id=p.user_id
        WHERE p.user_id=? OR p.shared=1
        ORDER BY p.user_id=? DESC, p.created_at DESC
    """, (user["id"], user["id"])).fetchall()
    result = []
    for p in rows:
        p = dict(p)
        first = db.execute("""
            SELECT s.youtube_id FROM playlist_songs ps
            JOIN songs s ON s.id=ps.song_id WHERE ps.playlist_id=? LIMIT 1
        """, (p["id"],)).fetchone()
        p["thumbnail"] = f"https://img.youtube.com/vi/{first['youtube_id']}/mqdefault.jpg" if first else None
        p["song_count"] = db.execute("SELECT COUNT(*) FROM playlist_songs WHERE playlist_id=?", (p["id"],)).fetchone()[0]
        result.append(p)
    db.close()
    return {"playlists": result}

@app.get("/playlists/{playlist_id}")
def get_playlist(playlist_id: int, user=Depends(get_current_user)):
    db = get_db()
    p = db.execute("""
        SELECT p.*, u.username as owner_name FROM playlists p
        JOIN users u ON u.id=p.user_id
        WHERE p.id=? AND (p.user_id=? OR p.shared=1)
    """, (playlist_id, user["id"])).fetchone()
    if not p: db.close(); raise HTTPException(404, "Playlist not found")
    songs = db.execute("""
        SELECT s.*, ps.added_at as added_to_playlist FROM playlist_songs ps
        JOIN songs s ON s.id=ps.song_id WHERE ps.playlist_id=? ORDER BY ps.added_at
    """, (playlist_id,)).fetchall()
    songs = [dict(s) for s in songs]
    p = dict(p)
    p["thumbnail"] = f"https://img.youtube.com/vi/{songs[0]['youtube_id']}/mqdefault.jpg" if songs and songs[0].get("youtube_id") else None
    p["can_edit"] = p["user_id"] == user["id"]
    db.close()
    return {"playlist": p, "songs": songs}

@app.patch("/playlists/{playlist_id}")
def update_playlist(playlist_id: int, req: UpdatePlaylistRequest, user=Depends(get_current_user)):
    db = get_db()
    p = db.execute("SELECT * FROM playlists WHERE id=? AND user_id=?", (playlist_id, user["id"])).fetchone()
    if not p: db.close(); raise HTTPException(404, "Not yours")
    if req.name is not None:
        db.execute("UPDATE playlists SET name=? WHERE id=?", (req.name, playlist_id))
    if req.shared is not None:
        db.execute("UPDATE playlists SET shared=? WHERE id=?", (1 if req.shared else 0, playlist_id))
    db.commit(); db.close()
    return {"updated": True}

@app.post("/playlists/{playlist_id}/songs/{youtube_id}")
def add_to_playlist(playlist_id: int, youtube_id: str, user=Depends(get_current_user)):
    db = get_db()
    p = db.execute("SELECT id FROM playlists WHERE id=? AND (user_id=? OR shared=1)", (playlist_id, user["id"])).fetchone()
    if not p: db.close(); raise HTTPException(404, "Not found")
    song = db.execute("SELECT id FROM songs WHERE youtube_id=?", (youtube_id,)).fetchone()
    if not song: db.close(); raise HTTPException(404, "Play the song first")
    db.execute("INSERT OR IGNORE INTO playlist_songs (playlist_id,song_id) VALUES (?,?)", (playlist_id, song["id"]))
    db.commit(); db.close()
    return {"added": True}

@app.delete("/playlists/{playlist_id}/songs/{youtube_id}")
def remove_from_playlist(playlist_id: int, youtube_id: str, user=Depends(get_current_user)):
    db = get_db()
    p = db.execute("SELECT id FROM playlists WHERE id=? AND user_id=?", (playlist_id, user["id"])).fetchone()
    if not p: db.close(); raise HTTPException(404, "Not yours")
    song = db.execute("SELECT id FROM songs WHERE youtube_id=?", (youtube_id,)).fetchone()
    if song:
        db.execute("DELETE FROM playlist_songs WHERE playlist_id=? AND song_id=?", (playlist_id, song["id"]))
        db.commit()
    db.close()
    return {"removed": True}

@app.delete("/playlists/{playlist_id}")
def delete_playlist(playlist_id: int, user=Depends(get_current_user)):
    db = get_db()
    p = db.execute("SELECT id FROM playlists WHERE id=? AND user_id=?", (playlist_id, user["id"])).fetchone()
    if not p: db.close(); raise HTTPException(404, "Not yours")
    db.execute("DELETE FROM playlist_songs WHERE playlist_id=?", (playlist_id,))
    db.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))
    db.commit(); db.close()
    return {"deleted": True}

# ── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin/users")
def list_users(user=Depends(get_current_user)):
    if user["id"] != 1: raise HTTPException(403, "Admin only")
    db = get_db()
    users = db.execute("SELECT id,username,created_at FROM users ORDER BY id").fetchall()
    db.close()
    return {"users": [dict(u) for u in users]}

@app.delete("/admin/users/{user_id}")
def delete_user(user_id: int, user=Depends(get_current_user)):
    if user["id"] != 1: raise HTTPException(403, "Admin only")
    if user_id == 1: raise HTTPException(400, "Cannot delete admin")
    db = get_db()
    for q in [
        "DELETE FROM play_history WHERE user_id=?",
        "DELETE FROM liked_songs WHERE user_id=?",
        "DELETE FROM playlist_songs WHERE playlist_id IN (SELECT id FROM playlists WHERE user_id=?)",
        "DELETE FROM playlists WHERE user_id=?",
        "DELETE FROM users WHERE id=?"
    ]:
        db.execute(q, (user_id,))
    db.commit(); db.close()
    return {"deleted": True}



# ── Spotify Import ────────────────────────────────────────────────────────────

class SpotifyImportRequest(BaseModel):
    url: str
    shared: bool = False

# Track import jobs in memory
_import_jobs = {}  # job_id -> {status, total, done, playlist_id, errors}

# ── Spotify OAuth (admin connects the family-wide Spotify account) ────────────

@app.get("/spotify/auth/status")
def spotify_auth_status(user=Depends(get_current_user)):
    from spotify import connection_info
    from config import SPOTIFY_REDIRECT_URI, SPOTIFY_CLIENT_ID
    info = connection_info()
    info["is_admin"] = (user["id"] == 1)
    info["configured"] = bool(SPOTIFY_CLIENT_ID and SPOTIFY_REDIRECT_URI)
    info["redirect_uri"] = SPOTIFY_REDIRECT_URI or None
    return info

@app.get("/spotify/auth/start")
def spotify_auth_start(user=Depends(get_current_user)):
    """Admin calls this to get the Spotify authorize URL. Encodes the
    Butler user id into `state` so the callback can record who connected."""
    if user["id"] != 1:
        raise HTTPException(403, "Only the admin can connect Spotify")
    from spotify import make_state, build_auth_url
    try:
        token_part = make_state()
        # state = <random>:<user_id> — callback verifies the random part
        state = f"{token_part}:{user['id']}"
        url = build_auth_url(state)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"url": url}

@app.get("/spotify/callback")
async def spotify_auth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Spotify redirects the browser here after the user authorizes.
    No auth dependency — this is an unauthenticated browser redirect.
    Path must match a Redirect URI registered in the Spotify dashboard."""
    from spotify import (
        consume_state, exchange_code, fetch_me_with_token, save_connection
    )

    def html_page(title: str, body: str, ok: bool) -> HTMLResponse:
        color = "#1db954" if ok else "#f15e6c"
        return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title>
<style>
body{{background:#121212;color:#fff;font-family:-apple-system,BlinkMacSystemFont,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
.card{{max-width:420px;padding:32px;background:#1e1e1e;border-radius:12px}}
h1{{color:{color};margin:0 0 12px 0;font-size:1.4rem}}
p{{color:#b3b3b3;line-height:1.5;font-size:14px}}
button{{background:{color};color:#000;border:0;padding:10px 24px;border-radius:24px;
font-weight:700;cursor:pointer;margin-top:16px}}
</style></head><body><div class="card">
<h1>{title}</h1><p>{body}</p>
<button onclick="window.close();if(window.opener)window.opener.location.reload();else location.href='/'">Close</button>
</div></body></html>""")

    if error:
        return html_page("Authorization denied",
                         f"Spotify returned: {error}. You can close this window.",
                         ok=False)
    if not code or not state:
        return html_page("Missing code", "Spotify didn't send back an auth code.", ok=False)

    try:
        token_part, _, user_id_str = state.partition(":")
        if not consume_state(token_part):
            return html_page("Invalid or expired state",
                             "Please start the connect flow again from Butler.",
                             ok=False)
        butler_user_id = int(user_id_str or "1")
    except Exception:
        return html_page("Bad state", "State parameter was malformed.", ok=False)

    try:
        tokens = await exchange_code(code)
    except Exception as e:
        return html_page("Token exchange failed", str(e), ok=False)

    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")
    scope = tokens.get("scope", "")
    if not refresh_token:
        return html_page("No refresh token",
                         "Spotify didn't return a refresh token. Try connecting again.",
                         ok=False)

    me = await fetch_me_with_token(access_token) if access_token else {"display_name": None}
    username = me.get("display_name") or "unknown"

    save_connection(refresh_token, scope, butler_user_id, username)

    return html_page(
        "Spotify connected!",
        f"Connected as <b>{username}</b>. You can close this window and return to Butler.",
        ok=True,
    )

@app.post("/spotify/auth/disconnect")
def spotify_auth_disconnect(user=Depends(get_current_user)):
    if user["id"] != 1:
        raise HTTPException(403, "Only the admin can disconnect Spotify")
    from spotify import disconnect
    disconnect()
    return {"disconnected": True}

@app.post("/spotify/import")
async def spotify_import(req: SpotifyImportRequest, user=Depends(get_current_user)):
    from spotify import extract_playlist_id, fetch_playlist
    import uuid

    try:
        playlist_id = extract_playlist_id(req.url)
    except ValueError as e:
        raise HTTPException(400, str(e))

    try:
        result = await fetch_playlist(playlist_id)
    except Exception as e:
        raise HTTPException(400, str(e))

    tracks = result.get("tracks", [])
    if not tracks:
        raise HTTPException(400, "Playlist is empty or could not be read")

    db = get_db()
    db.execute("INSERT INTO playlists (user_id, name, shared) VALUES (?,?,?)",
               (user["id"], result.get("name", "Imported Playlist"), 1 if req.shared else 0))
    db.commit()
    butler_pid = db.execute("SELECT id FROM playlists WHERE user_id=? ORDER BY id DESC LIMIT 1",
                            (user["id"],)).fetchone()["id"]
    db.close()

    job_id = str(uuid.uuid4())[:8]
    initial_errors = []
    if result.get("truncated"):
        initial_errors.append(
            "Note: Spotify limited us to the first 100 tracks of this playlist. "
            "For longer playlists, use the CSV import."
        )
    _import_jobs[job_id] = {
        "status": "running", "total": len(tracks), "done": 0,
        "playlist_id": butler_pid, "playlist_name": result.get("name", "Imported"),
        "errors": initial_errors, "found": 0
    }

    asyncio.create_task(_run_import(job_id, butler_pid, tracks))
    return {"job_id": job_id, "playlist_id": butler_pid, "total": len(tracks), "name": result.get("name")}

async def _run_import(job_id: str, playlist_id: int, tracks: list):
    from downloader import search_youtube, ensure_downloaded
    from songs_db import add_track
    job = _import_jobs[job_id]

    for track in tracks:
        try:
            q = f"{track['title']} {track['artist']}"
            results = search_youtube(q, max_results=2)
            if not results:
                job["errors"].append(f"Not found: {track['title']}")
                job["done"] += 1
                continue

            best = results[0]
            youtube_id = best["youtube_id"]
            title_key = f"{best['title'].lower()}|{(best['artist'] or '').lower()}"
            thumbnail = find_album_art(best["title"], best["artist"], youtube_id)

            db = get_db()
            db.execute("""
                INSERT OR IGNORE INTO songs (title, artist, duration, youtube_id, downloaded, title_key, thumbnail)
                VALUES (?,?,?,?,0,?,?)
            """, (best["title"], best["artist"], best["duration"], youtube_id, title_key, thumbnail))
            db.commit()
            song = db.execute("SELECT id FROM songs WHERE youtube_id=?", (youtube_id,)).fetchone()
            if song:
                db.execute("INSERT OR IGNORE INTO playlist_songs (playlist_id, song_id) VALUES (?,?)",
                           (playlist_id, song["id"]))
                db.commit()
            db.close()
            add_track(best["title"], best["artist"], best["duration"])

            # Download in background
            asyncio.create_task(ensure_downloaded(youtube_id))

            job["found"] += 1
        except Exception as e:
            job["errors"].append(f"{track['title']}: {str(e)[:60]}")

        job["done"] += 1
        await asyncio.sleep(0.3)  # be gentle with YouTube

    job["status"] = "done"

@app.post("/spotify/import-csv")
async def spotify_import_csv(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    shared: bool = Form(False),
    user=Depends(get_current_user)
):
    import csv, io, uuid

    if not (file.filename or '').lower().endswith('.csv'):
        raise HTTPException(400, "File must be a .csv")

    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(400, "CSV too large (max 5 MB)")
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            text = raw.decode('latin-1')
        except Exception:
            raise HTTPException(400, "Could not decode CSV — please save as UTF-8")

    tracks = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        # Normalise headers so we tolerate small variations
        field_map = {(h or '').strip().lower(): h for h in (reader.fieldnames or [])}
        title_key = field_map.get('track name') or field_map.get('track_name') or field_map.get('name')
        artist_key = (field_map.get('artist name(s)') or field_map.get('artist name')
                      or field_map.get('artist names') or field_map.get('artist')
                      or field_map.get('artists'))
        if not title_key or not artist_key:
            raise HTTPException(400, "CSV must include 'Track Name' and 'Artist Name(s)' columns (Exportify format)")
        for row in reader:
            title = (row.get(title_key) or '').strip()
            artist = (row.get(artist_key) or '').strip()
            if title:
                tracks.append({"title": title, "artist": artist})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {str(e)[:120]}")

    if not tracks:
        raise HTTPException(400, "No valid tracks found in CSV")

    playlist_name = (name or '').strip()
    if not playlist_name:
        playlist_name = (file.filename or 'Imported Playlist').rsplit('.', 1)[0] or 'Imported Playlist'

    db = get_db()
    db.execute("INSERT INTO playlists (user_id, name, shared) VALUES (?,?,?)",
               (user["id"], playlist_name, 1 if shared else 0))
    db.commit()
    butler_pid = db.execute(
        "SELECT id FROM playlists WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (user["id"],)
    ).fetchone()["id"]
    db.close()

    job_id = str(uuid.uuid4())[:8]
    _import_jobs[job_id] = {
        "status": "running", "total": len(tracks), "done": 0,
        "playlist_id": butler_pid, "playlist_name": playlist_name,
        "errors": [], "found": 0
    }

    asyncio.create_task(_run_import(job_id, butler_pid, tracks))
    return {"job_id": job_id, "playlist_id": butler_pid, "total": len(tracks), "name": playlist_name}

@app.get("/spotify/import/{job_id}")
def import_status(job_id: str, user=Depends(get_current_user)):
    job = _import_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job

# ── Static — must be last ─────────────────────────────────────────────────────
# ── Daily mix ─────────────────────────────────────────────────────────────────
@app.get("/daily-mix")
def daily_mix(user=Depends(get_current_user)):
    """Return today's Daily Mix songs for this user (empty if not built yet)."""
    db = get_db()
    p = db.execute(
        "SELECT id, name FROM playlists WHERE user_id=? AND name='Daily Mix' LIMIT 1",
        (user["id"],),
    ).fetchone()
    if not p:
        db.close()
        return {"playlist": None, "songs": []}
    songs = db.execute(
        """
        SELECT s.* FROM playlist_songs ps
        JOIN songs s ON s.id = ps.song_id
        WHERE ps.playlist_id=?
        ORDER BY ps.added_at
        """,
        (p["id"],),
    ).fetchall()
    songs = [dict(s) for s in songs]
    playlist = dict(p)
    playlist["thumbnail"] = (
        f"https://img.youtube.com/vi/{songs[0]['youtube_id']}/mqdefault.jpg"
        if songs and songs[0].get("youtube_id") else None
    )
    playlist["song_count"] = len(songs)
    db.close()
    return {"playlist": playlist, "songs": songs}


@app.post("/daily-mix/regenerate")
def daily_mix_regenerate(user=Depends(get_current_user)):
    """Trigger a regeneration for the current user (synchronous, fire-and-forget)."""
    import subprocess
    import sys
    base_dir = os.path.dirname(os.path.abspath(__file__))
    subprocess.Popen(
        [sys.executable, os.path.join(base_dir, "daily_mix.py")],
        cwd=base_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"queued": True}

# ── Top artists (for dashboard) ───────────────────────────────────────────────
@app.get("/top-artists")
def top_artists(user=Depends(get_current_user), limit: int = Query(8, le=30)):
    db = get_db()
    rows = db.execute(
        """
        SELECT s.artist, COUNT(*) c, MAX(s.thumbnail) thumb, MAX(s.youtube_id) seed_yid
        FROM play_history ph JOIN songs s ON s.id = ph.song_id
        WHERE ph.user_id=? AND s.artist IS NOT NULL AND s.artist != ''
        GROUP BY s.artist ORDER BY c DESC LIMIT ?
        """,
        (user["id"], limit),
    ).fetchall()
    db.close()
    return {"artists": [
        {"name": r["artist"], "play_count": r["c"],
         "thumbnail": r["thumb"], "seed_youtube_id": r["seed_yid"]}
        for r in rows
    ]}

# ── Lyrics ────────────────────────────────────────────────────────────────────
import requests as _lrc_requests


def _clean_title_for_lrclib(t: str, artist: str = "") -> str:
    """Aggressive YouTube-title → song-title cleaner for lrclib matching."""
    if not t:
        return ""
    s = t
    # Remove parentheticals/brackets containing promotional terms
    promo = (r"(?:official|video|music\s*video|lyric(?:s)?|audio|hd|hq|4k|"
             r"remaster.*?|live.*?|slowed.*?|sped.*?up|reverb|bass\s*boost|"
             r"remix|edit|mashup|cover|tiktok|extended|version)")
    s = re.sub(r"\s*[\(\[][^\(\)\[\]]*" + promo + r"[^\(\)\[\]]*[\)\]]\s*",
               " ", s, flags=re.IGNORECASE)
    # Remove any remaining parentheticals that are short marketing-y blurbs
    s = re.sub(r"\s*[\(\[][^\(\)\[\]]{0,40}[\)\]]\s*", " ", s)
    # Strip "ft. X" / "feat X" / "featuring X" — up to a separator
    s = re.sub(r"\s+(?:ft\.?|feat\.?|featuring|w/|with)\s+[^\-–—,|]+",
               "", s, flags=re.IGNORECASE)
    # If artist appears at the start ("Drake - We Made It"), drop that prefix
    if artist:
        a = re.escape(artist.strip())
        s = re.sub(rf"^\s*{a}\s*[-–—:]\s*", "", s, flags=re.IGNORECASE)
    # Drop trailing " - Slowed", " - Remix", etc.
    s = re.sub(r"\s+[-–—]\s+(slow.*|sped.*|remix|edit|mashup|version|cover|live).*$",
               "", s, flags=re.IGNORECASE)
    # Collapse whitespace + smart quotes
    s = re.sub(r"\s+", " ", s).strip(" -–—:,\u2018\u2019\u201c\u201d\"'\t")
    return s

def _clean_artist_for_lrclib(a: str) -> str:
    if not a:
        return ""
    s = a
    # Drop "ft." segments from artist field too
    s = re.split(r"\s+(?:ft\.?|feat\.?|featuring|with|x|&|,)\s+", s, maxsplit=1, flags=re.IGNORECASE)[0]
    return s.strip()

def _fetch_lrclib(title: str, artist: str) -> dict | None:
    """Try get(), then several search() variants. Returns the first hit with lyrics."""
    headers = {"User-Agent": "Butler/1.0"}
    def _has_lyrics(d): return bool((d or {}).get("plainLyrics") or (d or {}).get("syncedLyrics"))

    # Stage 1: exact get
    try:
        r = _lrc_requests.get(
            "https://lrclib.net/api/get",
            params={"track_name": title, "artist_name": artist},
            timeout=6, headers=headers,
        )
        if r.status_code == 200:
            data = r.json()
            if _has_lyrics(data):
                return data
    except Exception:
        pass

    # Stage 2: structured search
    attempts = [
        {"track_name": title, "artist_name": artist},
        {"track_name": title},
        {"q": f"{title} {artist}".strip()},
        {"q": title},
    ]
    for params in attempts:
        try:
            r = _lrc_requests.get(
                "https://lrclib.net/api/search",
                params=params, timeout=6, headers=headers,
            )
            if r.status_code != 200:
                continue
            items = r.json() or []
            for item in items[:5]:
                if _has_lyrics(item):
                    return item
        except Exception:
            continue
    return None

@app.get("/lyrics/{youtube_id}")
def get_lyrics(youtube_id: str, force: bool = False, user=Depends(get_current_user)):
    db = get_db()
    if not force:
        row = db.execute(
            "SELECT plain, synced, source, fetched_at FROM lyrics WHERE youtube_id=?",
            (youtube_id,),
        ).fetchone()
        if row:
            db.close()
            return {
                "youtube_id": youtube_id,
                "plain": row["plain"] or "",
                "synced": row["synced"] or "",
                "source": row["source"] or "cache",
                "cached": True,
            }
    song = db.execute(
        "SELECT title, artist FROM songs WHERE youtube_id=?", (youtube_id,)
    ).fetchone()
    if not song:
        db.close(); raise HTTPException(404, "Song not found")
    artist = _clean_artist_for_lrclib((song["artist"] or "").strip())
    title = _clean_title_for_lrclib(song["title"] or "", artist=artist)
    data = _fetch_lrclib(title, artist)
    plain = (data or {}).get("plainLyrics") or ""
    synced = (data or {}).get("syncedLyrics") or ""
    source = "lrclib" if data else "none"
    db.execute(
        "INSERT OR REPLACE INTO lyrics (youtube_id, plain, synced, source, fetched_at) "
        "VALUES (?,?,?,?, CURRENT_TIMESTAMP)",
        (youtube_id, plain, synced, source),
    )
    db.commit(); db.close()
    return {
        "youtube_id": youtube_id,
        "plain": plain,
        "synced": synced,
        "source": source,
        "cached": False,
    }

# ── Now playing / cross-client sync ───────────────────────────────────────────
import time as _np_time
_NOW_PLAYING: dict[int, dict] = {}

@app.post("/now-playing/heartbeat")
def now_playing_heartbeat(body: dict, user=Depends(get_current_user)):
    """Clients call this every few seconds while playing so other clients can see."""
    yid = (body or {}).get("youtube_id") or ""
    if not yid:
        _NOW_PLAYING.pop(user["id"], None)
        return {"ok": True}
    _NOW_PLAYING[user["id"]] = {
        "youtube_id": yid,
        "position_ms": int((body or {}).get("position_ms") or 0),
        "duration_ms": int((body or {}).get("duration_ms") or 0),
        "is_playing": bool((body or {}).get("is_playing")),
        "device": str((body or {}).get("device") or "client")[:32],
        "updated_at": _np_time.time(),
    }
    return {"ok": True}

@app.get("/now-playing")
def now_playing(user=Depends(get_current_user)):
    state = _NOW_PLAYING.get(user["id"])
    if not state:
        return {"song": None}
    age = _np_time.time() - state["updated_at"]
    if age > 30:  # stale — client probably closed
        return {"song": None, "stale_age": age}
    db = get_db()
    song_row = db.execute(
        "SELECT * FROM songs WHERE youtube_id=?", (state["youtube_id"],)
    ).fetchone()
    db.close()
    song = dict(song_row) if song_row else {"youtube_id": state["youtube_id"]}
    # If clients sent a position recently, advance it by the time-since-heartbeat
    # so the web UI scrubber moves smoothly.
    extrapolated = state["position_ms"]
    if state["is_playing"]:
        extrapolated = min(
            state["duration_ms"] or extrapolated + int(age * 1000),
            extrapolated + int(age * 1000),
        )
    return {
        "song": song,
        "position_ms": extrapolated,
        "duration_ms": state["duration_ms"],
        "is_playing": state["is_playing"],
        "device": state["device"],
        "updated_at": state["updated_at"],
    }

app.mount("/", StaticFiles(directory="static", html=True), name="static")
