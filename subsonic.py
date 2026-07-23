"""
Subsonic API compatibility layer.

Implements the core of the Subsonic REST API (http://www.subsonic.org/pages/api.jsp)
so existing Subsonic-compatible clients (DSub, Substreamer, Symfonium, play:Sub,
Amperfy, etc.) can browse and stream a Butler library without any custom client.

Scope: enough of the ID3-tag-based browsing scheme (getArtists/getArtist/getAlbum),
streaming, cover art, search, playlists, starring, and scrobble/now-playing to cover
what typical mobile clients need for day-to-day listening. Not implemented: the
older folder-browsing endpoints (getMusicDirectory), podcasts, internet radio,
bookmarks, shares, or XML responses (JSON only, via f=json, which is what modern
clients request).

Auth: only the plain-password scheme (?p=...) is supported, not the salted-token
scheme (?t=&s=). Butler stores bcrypt password hashes, which are one-way by design
-- computing the token scheme's md5(password + salt) server-side would require
knowing the plaintext password, which bcrypt deliberately makes impossible to
recover. Most Subsonic clients have a "plaintext password" fallback option; this
is a real, permanent limitation of pairing Subsonic auth with proper password
hashing, not a bug.
"""
import base64
import os

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from auth import verify_password
from database import get_db
from config import MUSIC_DIR

router = APIRouter(prefix="/rest")

API_VERSION = "1.16.1"


def _ok(**data):
    resp = {"status": "ok", "version": API_VERSION, "type": "butler", "serverVersion": "1.0.0"}
    resp.update(data)
    return JSONResponse({"subsonic-response": resp})


def _fail(code: int, message: str):
    return JSONResponse({"subsonic-response": {
        "status": "failed", "version": API_VERSION, "type": "butler", "serverVersion": "1.0.0",
        "error": {"code": code, "message": message},
    }})


def _artist_id(artist: str) -> str:
    return "ar_" + base64.urlsafe_b64encode((artist or "").lower().encode()).decode().rstrip("=")


def _decode_artist_id(aid: str) -> str:
    pad = aid[3:] + "=" * (-len(aid[3:]) % 4)
    return base64.urlsafe_b64decode(pad).decode()


def _album_id(artist: str, album: str) -> str:
    raw = f"{(artist or '').lower()}\x1f{(album or '').lower()}"
    return "al_" + base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_album_id(alid: str):
    pad = alid[3:] + "=" * (-len(alid[3:]) % 4)
    artist, album = base64.urlsafe_b64decode(pad).decode().split("\x1f", 1)
    return artist, album


def _album_display_name(album: str) -> str:
    return album if album else "Singles"


async def _authenticate(request: Request):
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            params.update(dict(form))
        except Exception:
            pass

    username = params.get("u")
    password = params.get("p")
    if password and password.startswith("enc:"):
        try:
            password = bytes.fromhex(password[4:]).decode()
        except Exception:
            pass

    if not username or not password:
        if params.get("t"):
            return None, _fail(43, "Token-based auth isn't supported; enable "
                                    "'plaintext password' in your client's login options.")
        return None, _fail(10, "Required parameter 'u' or 'p' is missing.")

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    if not row or not verify_password(password, row["password_hash"]):
        return None, _fail(40, "Wrong username or password.")

    return dict(row), params


def _song_child(row) -> dict:
    return {
        "id": str(row["id"]),
        "parent": _album_id(row["artist"], row["album"]),
        "isDir": False,
        "title": row["title"],
        "album": _album_display_name(row["album"]),
        "artist": row["artist"] or "Unknown",
        "coverArt": str(row["id"]),
        "contentType": "audio/mpeg",
        "suffix": "mp3",
        "duration": row["duration"] or 0,
        "bitRate": 192,
        "path": f"{row['artist'] or 'Unknown'}/{row['title']}.mp3",
        "created": row["added_at"],
        "albumId": _album_id(row["artist"], row["album"]),
        "artistId": _artist_id(row["artist"]),
        "type": "music",
        "isVideo": False,
    }


@router.api_route("/ping.view", methods=["GET", "POST", "HEAD"])
async def ping(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    return _ok()


@router.api_route("/getLicense.view", methods=["GET", "POST", "HEAD"])
async def get_license(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    return _ok(license={"valid": True})


@router.api_route("/getMusicFolders.view", methods=["GET", "POST", "HEAD"])
async def get_music_folders(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    return _ok(musicFolders={"musicFolder": [{"id": 1, "name": "Butler"}]})


@router.api_route("/getUser.view", methods=["GET", "POST", "HEAD"])
async def get_user(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    return _ok(user={
        "username": user["username"], "adminRole": user["id"] == 1, "settingsRole": True,
        "downloadRole": True, "uploadRole": False, "playlistRole": True, "coverArtRole": True,
        "commentRole": False, "podcastRole": False, "streamRole": True, "jukeboxRole": False,
        "shareRole": False, "scrobblingEnabled": True,
    })


@router.api_route("/getArtists.view", methods=["GET", "POST", "HEAD"])
async def get_artists(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    db = get_db()
    rows = db.execute("""
        SELECT artist, COUNT(*) c FROM songs
        WHERE artist IS NOT NULL AND artist != '' AND downloaded=1
        GROUP BY LOWER(artist) ORDER BY LOWER(artist)
    """).fetchall()
    db.close()

    buckets = {}
    for r in rows:
        letter = (r["artist"][:1] or "#").upper()
        letter = letter if letter.isalpha() else "#"
        buckets.setdefault(letter, []).append({
            "id": _artist_id(r["artist"]), "name": r["artist"], "albumCount": None, "coverArt": None,
        })
    index = [{"name": k, "artist": v} for k, v in sorted(buckets.items())]
    return _ok(artists={"ignoredArticles": "", "index": index})


@router.api_route("/getIndexes.view", methods=["GET", "POST", "HEAD"])
async def get_indexes(request: Request):
    return await get_artists(request)


@router.api_route("/getArtist.view", methods=["GET", "POST", "HEAD"])
async def get_artist(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    aid = params.get("id", "")
    if not aid.startswith("ar_"):
        return _fail(70, "Artist not found.")
    artist_lower = _decode_artist_id(aid)

    db = get_db()
    display_row = db.execute(
        "SELECT artist FROM songs WHERE LOWER(artist)=? LIMIT 1", (artist_lower,)
    ).fetchone()
    display_name = display_row["artist"] if display_row else artist_lower
    rows = db.execute(
        "SELECT DISTINCT album FROM songs WHERE LOWER(artist)=? AND downloaded=1",
        (artist_lower,),
    ).fetchall()
    db.close()

    albums = [{
        "id": _album_id(artist_lower, r["album"]), "name": _album_display_name(r["album"]),
        "artist": display_name, "artistId": aid, "coverArt": None,
    } for r in rows]

    return _ok(artist={"id": aid, "name": display_name, "albumCount": len(albums), "album": albums})


@router.api_route("/getAlbum.view", methods=["GET", "POST", "HEAD"])
async def get_album(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    alid = params.get("id", "")
    if not alid.startswith("al_"):
        return _fail(70, "Album not found.")
    artist_lower, album = _decode_album_id(alid)

    db = get_db()
    if album:
        rows = db.execute(
            "SELECT * FROM songs WHERE LOWER(artist)=? AND LOWER(COALESCE(album,''))=? AND downloaded=1",
            (artist_lower, album),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM songs WHERE LOWER(artist)=? AND (album IS NULL OR album='') AND downloaded=1",
            (artist_lower,),
        ).fetchall()
    db.close()

    display_name = rows[0]["artist"] if rows else artist_lower
    songs = [_song_child(r) for r in rows]
    return _ok(album={
        "id": alid, "name": _album_display_name(album), "artist": display_name,
        "artistId": _artist_id(artist_lower), "songCount": len(songs),
        "duration": sum(s["duration"] for s in songs), "song": songs,
    })


@router.api_route("/getSong.view", methods=["GET", "POST", "HEAD"])
async def get_song(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    sid = params.get("id", "")
    db = get_db()
    row = db.execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone()
    db.close()
    if not row:
        return _fail(70, "Song not found.")
    return _ok(song=_song_child(row))


@router.api_route("/search3.view", methods=["GET", "POST", "HEAD"])
async def search3(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    q = (params.get("query") or "").strip().strip('"')
    db = get_db()
    if q:
        rows = db.execute(
            "SELECT * FROM songs WHERE downloaded=1 AND (title LIKE ? OR artist LIKE ?) LIMIT 40",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM songs WHERE downloaded=1 LIMIT 40").fetchall()
    db.close()
    songs = [_song_child(r) for r in rows]
    return _ok(searchResult3={"song": songs})


@router.api_route("/getPlaylists.view", methods=["GET", "POST", "HEAD"])
async def get_playlists(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    db = get_db()
    rows = db.execute("SELECT * FROM playlists WHERE user_id=?", (user["id"],)).fetchall()
    counts = db.execute("SELECT playlist_id, COUNT(*) c FROM playlist_songs GROUP BY playlist_id").fetchall()
    db.close()
    count_map = {c["playlist_id"]: c["c"] for c in counts}
    playlists = [{
        "id": str(r["id"]), "name": r["name"], "owner": user["username"], "public": bool(r["shared"]),
        "songCount": count_map.get(r["id"], 0), "duration": 0,
    } for r in rows]
    return _ok(playlists={"playlist": playlists})


@router.api_route("/getPlaylist.view", methods=["GET", "POST", "HEAD"])
async def get_playlist(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    pid = params.get("id", "")
    db = get_db()
    pl = db.execute("SELECT * FROM playlists WHERE id=? AND user_id=?", (pid, user["id"])).fetchone()
    if not pl:
        db.close()
        return _fail(70, "Playlist not found.")
    rows = db.execute("""
        SELECT s.* FROM playlist_songs ps JOIN songs s ON s.id=ps.song_id
        WHERE ps.playlist_id=? ORDER BY ps.added_at
    """, (pid,)).fetchall()
    db.close()
    songs = [_song_child(r) for r in rows]
    return _ok(playlist={
        "id": str(pl["id"]), "name": pl["name"], "owner": user["username"], "public": bool(pl["shared"]),
        "songCount": len(songs), "duration": sum(s["duration"] for s in songs), "entry": songs,
    })


@router.api_route("/star.view", methods=["GET", "POST", "HEAD"])
async def star(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    sid = params.get("id")
    if sid:
        db = get_db()
        db.execute("INSERT OR IGNORE INTO liked_songs (user_id, song_id) VALUES (?,?)", (user["id"], sid))
        db.commit(); db.close()
    return _ok()


@router.api_route("/unstar.view", methods=["GET", "POST", "HEAD"])
async def unstar(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    sid = params.get("id")
    if sid:
        db = get_db()
        db.execute("DELETE FROM liked_songs WHERE user_id=? AND song_id=?", (user["id"], sid))
        db.commit(); db.close()
    return _ok()


@router.api_route("/getStarred2.view", methods=["GET", "POST", "HEAD"])
async def get_starred2(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    db = get_db()
    rows = db.execute("""
        SELECT s.* FROM liked_songs ls JOIN songs s ON s.id=ls.song_id
        WHERE ls.user_id=? AND s.downloaded=1
    """, (user["id"],)).fetchall()
    db.close()
    songs = [_song_child(r) for r in rows]
    return _ok(starred2={"song": songs})


@router.api_route("/scrobble.view", methods=["GET", "POST", "HEAD"])
async def scrobble(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    sid = params.get("id")
    submission = params.get("submission", "true").lower() != "false"
    if sid and submission:
        db = get_db()
        db.execute("INSERT INTO play_history (user_id, song_id) VALUES (?,?)", (user["id"], sid))
        song = db.execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone()
        db.commit(); db.close()
        if song:
            try:
                from scrobbling import scrobble_for_user
                await scrobble_for_user(user["id"], dict(song))
            except Exception:
                pass
    return _ok()


@router.api_route("/getCoverArt.view", methods=["GET", "POST", "HEAD"])
async def get_cover_art(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    cid = params.get("id", "")
    db = get_db()
    row = db.execute("SELECT thumbnail FROM songs WHERE id=?", (cid,)).fetchone()
    db.close()
    if not row or not row["thumbnail"]:
        raise HTTPException(404, "No cover art")
    import requests as _r
    try:
        resp = _r.get(row["thumbnail"], timeout=5)
        return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"))
    except Exception:
        raise HTTPException(404, "Could not fetch cover art")


@router.api_route("/stream.view", methods=["GET", "POST", "HEAD"])
@router.api_route("/download.view", methods=["GET", "POST", "HEAD"])
async def stream(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    sid = params.get("id", "")
    db = get_db()
    row = db.execute("SELECT youtube_id FROM songs WHERE id=?", (sid,)).fetchone()
    db.close()
    if not row or not row["youtube_id"]:
        raise HTTPException(404, "Song not found")
    file_path = os.path.join(MUSIC_DIR, f"{row['youtube_id']}.mp3")
    if not os.path.exists(file_path):
        from downloader import ensure_downloaded
        await ensure_downloaded(row["youtube_id"])
    if not os.path.exists(file_path):
        raise HTTPException(503, "Not downloaded yet")
    return FileResponse(file_path, media_type="audio/mpeg", headers={"Accept-Ranges": "bytes"})
