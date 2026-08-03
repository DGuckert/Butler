import sqlite3
from config import DATABASE_URL

def get_db():
    conn = sqlite3.connect(DATABASE_URL)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT,
            album TEXT,
            duration INTEGER,
            youtube_id TEXT UNIQUE,
            file_path TEXT,
            downloaded INTEGER DEFAULT 0,
            title_key TEXT,
            thumbnail TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            shared INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS playlist_songs (
            playlist_id INTEGER NOT NULL,
            song_id INTEGER NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (playlist_id, song_id),
            FOREIGN KEY (playlist_id) REFERENCES playlists(id),
            FOREIGN KEY (song_id) REFERENCES songs(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS liked_songs (
            user_id INTEGER NOT NULL,
            song_id INTEGER NOT NULL,
            liked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, song_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (song_id) REFERENCES songs(id)
        )
    """)

    # API keys -- lets SSO-only accounts (whose real password_hash is a
    # locked random value, see the OIDC migration below) still authenticate
    # third-party Subsonic clients and other non-browser tools that only
    # understand a username/password pair. key_hash is SHA-256, not bcrypt:
    # these are 256-bit random tokens the user never chooses, not
    # human-chosen passwords, so there's no brute-force-slowing benefit to
    # bcrypt here and a fast hash keeps lookup an indexed exact match
    # instead of iterating every stored key through a bcrypt verify.
    c.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS play_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            song_id INTEGER NOT NULL,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (song_id) REFERENCES songs(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            created_by INTEGER NOT NULL,
            used_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            used_at TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id),
            FOREIGN KEY (used_by) REFERENCES users(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS server_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS scrobble_config (
            user_id INTEGER PRIMARY KEY,
            listenbrainz_token TEXT,
            enabled INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS artist_info (
            artist_lower TEXT PRIMARY KEY,
            display_name TEXT,
            bio TEXT,
            image TEXT,
            source_url TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Single-row table holding the family-wide Spotify OAuth refresh token.
    # We only ever store id=1; admin connects once and the whole family imports through it.
    c.execute("""
        CREATE TABLE IF NOT EXISTS spotify_auth (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            refresh_token TEXT NOT NULL,
            scope TEXT,
            connected_by INTEGER,
            connected_username TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (connected_by) REFERENCES users(id)
        )
    """)

    # Migrations
    for col, typedef in [
        ("title_key", "TEXT"),
        ("thumbnail", "TEXT"),
        ("shared", "INTEGER DEFAULT 0"),
        ("file_ext", "TEXT DEFAULT 'mp3'"),
    ]:
        try:
            c.execute(f"ALTER TABLE songs ADD COLUMN {col} {typedef}")
        except: pass
    try:
        c.execute("ALTER TABLE playlists ADD COLUMN shared INTEGER DEFAULT 0")
    except: pass

    # OIDC / SSO login support. password_hash stays NOT NULL for every user
    # (including OIDC-only accounts, which get an unusable locked hash --
    # see auth.py create_oidc_locked_hash) so we avoid an SQLite table
    # rebuild just to relax that constraint. oidc_issuer is stored per-user
    # (not just read from config) so a future issuer change doesn't orphan
    # existing linked accounts, and so the partial unique index below can
    # scope correctly if that ever happens.
    for col, typedef in [
        ("oidc_subject", "TEXT"),
        ("oidc_issuer", "TEXT"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")
        except: pass
    c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_oidc
        ON users(oidc_issuer, oidc_subject)
        WHERE oidc_subject IS NOT NULL
    """)

    # Backfills
    c.execute("""
        UPDATE songs SET title_key = LOWER(title) || '|' || LOWER(COALESCE(artist,''))
        WHERE title_key IS NULL
    """)
    c.execute("""
        UPDATE songs SET thumbnail = 'https://img.youtube.com/vi/' || youtube_id || '/mqdefault.jpg'
        WHERE thumbnail IS NULL AND youtube_id IS NOT NULL
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("DB OK")
