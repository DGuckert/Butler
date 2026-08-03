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
from downloader import local_file_path

_AUDIO_CONTENT_TYPES = {
    "mp3": "audio/mpeg", "m4a": "audio/mp4", "opus": "audio/opus",
    "webm": "audio/webm", "ogg": "audio/ogg", "flac": "audio/flac", "wav": "audio/wav",
}

router = APIRouter(prefix="/rest")

API_VERSION = "1.16.1"


def _ok(**data):
    # openSubsonic is mandatory, not decorative -- OpenSubsonic-aware
    # clients (Substreamer, Symfonium, ...) use it to decide whether to
    # trust extended features at all. Without it, a client can fall back
    # to a much more conservative plain-Subsonic feature set, which is
    # very likely why playlists (an area OpenSubsonic clients often gate
    # behind capability detection) looked broken before this was added.
    resp = {"status": "ok", "version": API_VERSION, "type": "butler", "serverVersion": "1.0.0", "openSubsonic": True}
    resp.update(data)
    return JSONResponse({"subsonic-response": resp})


def _fail(code: int, message: str):
    return JSONResponse({"subsonic-response": {
        "status": "failed", "version": API_VERSION, "type": "butler", "serverVersion": "1.0.0", "openSubsonic": True,
        "error": {"code": code, "message": message},
    }})


@router.api_route("/getOpenSubsonicExtensions.view", methods=["GET", "POST", "HEAD"])
async def get_open_subsonic_extensions(request: Request):
    """OpenSubsonic-aware clients call this early on to decide what
    extended functionality they can rely on. Only advertise what's
    genuinely implemented to spec -- songLyrics is (see
    getLyricsBySongId above). Butler's API keys are NOT the same thing as
    the real apiKeyAuthentication extension (that means a top-level
    apiKey= query param plus a tokenInfo.view endpoint, neither of which
    exist here -- ours works as a password substitute instead), so it's
    deliberately not claimed here even though it might look related."""
    user, err = await _authenticate(request)
    if not user:
        return err
    return _ok(openSubsonicExtensions=[
        {"name": "songLyrics", "versions": [1]},
    ])


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
    if row and verify_password(password, row["password_hash"]):
        return dict(row), params

    # Password didn't match a real local password -- try it as an API key
    # instead. This is what lets an SSO-only account (whose real
    # password_hash is a locked, unusable random value) still authenticate
    # third-party Subsonic clients: generate a key in account settings, use
    # it as the "password" here exactly like a normal one.
    import api_keys
    key_user = api_keys.find_user_by_key(password)
    if key_user and key_user["username"] == username:
        return key_user, params

    return None, _fail(40, "Wrong username or password.")


def _song_child(row) -> dict:
    ext = (row["file_ext"] if "file_ext" in row.keys() else None) or "mp3"
    return {
        "id": str(row["id"]),
        "parent": _album_id(row["artist"], row["album"]),
        "isDir": False,
        "title": row["title"],
        "album": _album_display_name(row["album"]),
        "artist": row["artist"] or "Unknown",
        "coverArt": str(row["id"]),
        "contentType": _AUDIO_CONTENT_TYPES.get(ext, "audio/mpeg"),
        "suffix": ext,
        "duration": row["duration"] or 0,
        "bitRate": 192,
        "path": f"{row['artist'] or 'Unknown'}/{row['title']}.{ext}",
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


def _albumlist_child(r) -> dict:
    return {
        "id": _album_id(r["artist"], r["album"]),
        "name": _album_display_name(r["album"]),
        "artist": r["artist"] or "Unknown",
        "artistId": _artist_id(r["artist"]),
        "songCount": r["song_count"],
        "duration": r["duration"] or 0,
        "created": r["created"],
        "coverArt": None,
    }


@router.api_route("/getAlbumList2.view", methods=["GET", "POST", "HEAD"])
async def get_album_list2(request: Request):
    """The ID3-tag browsing scheme's album list -- what most modern clients'
    "Albums" tab actually calls (getArtists/getArtist only covers browsing
    by artist). Butler has no albums table, only songs grouped by
    (artist, album), so every list type here is a GROUP BY over songs
    rather than a real table scan.

    byYear/byGenre aren't supported (Butler doesn't track either) and
    fall back to alphabeticalByName rather than erroring -- a client
    asking for a year range it can't get still gets *something* browsable
    instead of a dead tab."""
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    list_type = (params.get("type") or "alphabeticalByName").strip()
    try:
        size = max(1, min(int(params.get("size", 20)), 500))
    except ValueError:
        size = 20
    try:
        offset = max(0, int(params.get("offset", 0)))
    except ValueError:
        offset = 0

    db = get_db()
    if list_type in ("frequent", "recent"):
        order_col = "total_plays" if list_type == "frequent" else "last_played"
        rows = db.execute(f"""
            SELECT s.artist, s.album, COUNT(*) song_count, SUM(s.duration) duration,
                   MAX(s.added_at) created, SUM(ph.play_count) total_plays, MAX(ph.last_played) last_played
            FROM songs s
            JOIN (
                SELECT song_id, COUNT(*) play_count, MAX(played_at) last_played
                FROM play_history WHERE user_id=? GROUP BY song_id
            ) ph ON ph.song_id = s.id
            WHERE s.downloaded=1
            GROUP BY LOWER(s.artist), LOWER(COALESCE(s.album,''))
            ORDER BY {order_col} DESC
            LIMIT ? OFFSET ?
        """, (user["id"], size, offset)).fetchall()
    elif list_type == "starred":
        rows = db.execute("""
            SELECT s.artist, s.album, COUNT(*) song_count, SUM(s.duration) duration, MAX(s.added_at) created
            FROM songs s JOIN liked_songs ls ON ls.song_id=s.id
            WHERE s.downloaded=1 AND ls.user_id=?
            GROUP BY LOWER(s.artist), LOWER(COALESCE(s.album,''))
            ORDER BY LOWER(s.album)
            LIMIT ? OFFSET ?
        """, (user["id"], size, offset)).fetchall()
    else:
        order = {
            "newest": "created DESC",
            "random": "RANDOM()",
            "alphabeticalByArtist": "LOWER(artist), LOWER(album)",
        }.get(list_type, "LOWER(album), LOWER(artist)")
        rows = db.execute(f"""
            SELECT artist, album, COUNT(*) song_count, SUM(duration) duration, MAX(added_at) created
            FROM songs WHERE downloaded=1
            GROUP BY LOWER(artist), LOWER(COALESCE(album,''))
            ORDER BY {order}
            LIMIT ? OFFSET ?
        """, (size, offset)).fetchall()
    db.close()

    albums = [_albumlist_child(r) for r in rows]
    return _ok(albumList2={"album": albums})


@router.api_route("/getRandomSongs.view", methods=["GET", "POST", "HEAD"])
async def get_random_songs(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    try:
        size = max(1, min(int(params.get("size", 10)), 500))
    except ValueError:
        size = 10
    db = get_db()
    rows = db.execute(
        "SELECT * FROM songs WHERE downloaded=1 ORDER BY RANDOM() LIMIT ?", (size,)
    ).fetchall()
    db.close()
    return _ok(randomSongs={"song": [_song_child(r) for r in rows]})


@router.api_route("/getGenres.view", methods=["GET", "POST", "HEAD"])
async def get_genres(request: Request):
    """Butler doesn't tag or store genre, so this is always empty --
    returned as a valid empty list rather than omitted, since several
    clients probe this on connect and treat a missing/erroring endpoint
    as a broken server rather than just an empty Genres tab."""
    user, err = await _authenticate(request)
    if not user:
        return err
    return _ok(genres={"genre": []})


@router.api_route("/getNowPlaying.view", methods=["GET", "POST", "HEAD"])
async def get_now_playing(request: Request):
    """Butler doesn't track a live "currently playing" registry across
    users -- returned empty rather than omitted, same reasoning as
    getGenres above."""
    user, err = await _authenticate(request)
    if not user:
        return err
    return _ok(nowPlaying={"entry": []})


@router.api_route("/getPodcasts.view", methods=["GET", "POST", "HEAD"])
async def get_podcasts(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    return _ok(podcasts={"channel": []})


@router.api_route("/getInternetRadioStations.view", methods=["GET", "POST", "HEAD"])
async def get_internet_radio_stations(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    return _ok(internetRadioStations={"internetRadioStation": []})


@router.api_route("/getBookmarks.view", methods=["GET", "POST", "HEAD"])
async def get_bookmarks(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    return _ok(bookmarks={"bookmark": []})


@router.api_route("/getShares.view", methods=["GET", "POST", "HEAD"])
async def get_shares(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    return _ok(shares={"share": []})


@router.api_route("/setRating.view", methods=["GET", "POST", "HEAD"])
async def set_rating(request: Request):
    """Subsonic's 0-5 star rating doesn't map to anything Butler stores --
    the closest real equivalent is the like/star system already wired up
    through star.view/unstar.view. Treated as a binary shim: any rating
    >=1 stars the song, a rating of 0 unstars it. A client asking for a
    3-star rating won't get a 3 back on the next fetch, but it also won't
    error out, and the song lands in the same "liked" state a real 3-star
    rating would have implied anyway."""
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    sid = params.get("id")
    try:
        rating = int(params.get("rating", 0))
    except ValueError:
        rating = 0
    if sid:
        db = get_db()
        if rating >= 1:
            db.execute("INSERT OR IGNORE INTO liked_songs (user_id, song_id) VALUES (?,?)", (user["id"], sid))
        else:
            db.execute("DELETE FROM liked_songs WHERE user_id=? AND song_id=?", (user["id"], sid))
        db.commit(); db.close()
    return _ok()


@router.api_route("/createPlaylist.view", methods=["GET", "POST", "HEAD"])
async def create_playlist(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    name = (params.get("name") or "New Playlist").strip()
    song_ids = request.query_params.getlist("songId")
    db = get_db()
    cur = db.execute("INSERT INTO playlists (user_id, name) VALUES (?,?)", (user["id"], name))
    pid = cur.lastrowid
    for sid in song_ids:
        db.execute("INSERT INTO playlist_songs (playlist_id, song_id) VALUES (?,?)", (pid, sid))
    db.commit()
    rows = db.execute("""
        SELECT s.* FROM playlist_songs ps JOIN songs s ON s.id=ps.song_id
        WHERE ps.playlist_id=? ORDER BY ps.added_at
    """, (pid,)).fetchall()
    db.close()
    songs = [_song_child(r) for r in rows]
    return _ok(playlist={
        "id": str(pid), "name": name, "owner": user["username"], "public": False,
        "songCount": len(songs), "duration": sum(s["duration"] for s in songs), "entry": songs,
    })


@router.api_route("/deletePlaylist.view", methods=["GET", "POST", "HEAD"])
async def delete_playlist(request: Request):
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    pid = params.get("id")
    db = get_db()
    owned = db.execute("SELECT id FROM playlists WHERE id=? AND user_id=?", (pid, user["id"])).fetchone()
    if not owned:
        db.close()
        return _fail(70, "Playlist not found.")
    db.execute("DELETE FROM playlist_songs WHERE playlist_id=?", (pid,))
    db.execute("DELETE FROM playlists WHERE id=?", (pid,))
    db.commit(); db.close()
    return _ok()


@router.api_route("/updatePlaylist.view", methods=["GET", "POST", "HEAD"])
async def update_playlist(request: Request):
    """Supports renaming, appending songs (songIdToAdd), and removing by
    index (songIndexToRemove) -- the operations DSub/Symfonium/etc.
    actually send. Full reordering via repeated add/remove isn't
    implemented since no mainstream client's playlist editor needs it
    beyond these two operations."""
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    pid = params.get("playlistId")
    db = get_db()
    owned = db.execute("SELECT id FROM playlists WHERE id=? AND user_id=?", (pid, user["id"])).fetchone()
    if not owned:
        db.close()
        return _fail(70, "Playlist not found.")

    new_name = params.get("name")
    if new_name:
        db.execute("UPDATE playlists SET name=? WHERE id=?", (new_name, pid))

    remove_indices = sorted(
        (int(i) for i in request.query_params.getlist("songIndexToRemove") if i.isdigit()),
        reverse=True,
    )
    if remove_indices:
        # playlist_songs has a composite (playlist_id, song_id) primary key,
        # not a surrogate id -- delete by that pair instead.
        ordered = db.execute(
            "SELECT song_id FROM playlist_songs WHERE playlist_id=? ORDER BY added_at", (pid,)
        ).fetchall()
        for idx in remove_indices:
            if 0 <= idx < len(ordered):
                db.execute(
                    "DELETE FROM playlist_songs WHERE playlist_id=? AND song_id=?",
                    (pid, ordered[idx]["song_id"]),
                )

    for sid in request.query_params.getlist("songIdToAdd"):
        db.execute("INSERT INTO playlist_songs (playlist_id, song_id) VALUES (?,?)", (pid, sid))

    db.commit(); db.close()
    return _ok()


def _parse_lrc(lrc: str) -> list:
    """[mm:ss.xx]lyric line -> [{"start": ms, "value": "lyric line"}, ...],
    the structured shape OpenSubsonic's getLyricsBySongId expects. A line
    can carry more than one timestamp tag (repeated choruses sharing one
    line of text) -- each becomes its own entry, same as the source LRC
    intends."""
    import re
    entries = []
    tag_re = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
    for line in (lrc or "").splitlines():
        tags = list(tag_re.finditer(line))
        if not tags:
            continue
        text = tag_re.sub("", line).strip()
        for m in tags:
            minutes, seconds, frac = m.group(1), m.group(2), m.group(3) or "0"
            frac_ms = int((frac + "000")[:3])
            start_ms = (int(minutes) * 60 + int(seconds)) * 1000 + frac_ms
            entries.append({"start": start_ms, "value": text})
    entries.sort(key=lambda e: e["start"])
    return entries


@router.api_route("/getLyricsBySongId.view", methods=["GET", "POST", "HEAD"])
async def get_lyrics_by_song_id(request: Request):
    """OpenSubsonic extension -- structured, timestamped lyrics per song
    ID, as opposed to the older getLyrics.view's plain-text artist/title
    lookup. Butler already fetches and caches real synced lyrics (see
    /lyrics/{youtube_id} in main.py); this just exposes that same cache
    in the shape Subsonic clients that support synced lyrics expect,
    rather than requiring a second lyrics fetch through a Butler-specific
    endpoint."""
    user, err = await _authenticate(request)
    if not user:
        return err
    params = dict(request.query_params)
    sid = params.get("id", "")
    db = get_db()
    song = db.execute("SELECT youtube_id, title, artist FROM songs WHERE id=?", (sid,)).fetchone()
    if not song:
        db.close()
        return _fail(70, "Song not found.")
    lyr = db.execute(
        "SELECT plain, synced FROM lyrics WHERE youtube_id=?", (song["youtube_id"],)
    ).fetchone()
    db.close()
    if not lyr or (not lyr["plain"] and not lyr["synced"]):
        return _ok(lyricsList={"structuredLyrics": []})

    result = {
        "displayArtist": song["artist"] or "",
        "displayTitle": song["title"] or "",
        "lang": "und",
    }
    if lyr["synced"]:
        result["synced"] = True
        result["line"] = _parse_lrc(lyr["synced"])
    else:
        result["synced"] = False
        result["line"] = [{"value": l} for l in lyr["plain"].splitlines() if l.strip()]
    return _ok(lyricsList={"structuredLyrics": [result]})


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
    file_path = local_file_path(row["youtube_id"])
    if not os.path.exists(file_path):
        from downloader import ensure_downloaded, DownloadsDisabledError
        try:
            await ensure_downloaded(row["youtube_id"])
        except DownloadsDisabledError as e:
            raise HTTPException(503, str(e))
        file_path = local_file_path(row["youtube_id"])
    if not os.path.exists(file_path):
        raise HTTPException(503, "Not downloaded yet")
    ext = file_path.rsplit(".", 1)[-1].lower()
    return FileResponse(file_path, media_type=_AUDIO_CONTENT_TYPES.get(ext, "application/octet-stream"), headers={"Accept-Ranges": "bytes"})
