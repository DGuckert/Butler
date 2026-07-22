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
    ]:
        try:
            c.execute(f"ALTER TABLE songs ADD COLUMN {col} {typedef}")
        except: pass
    try:
        c.execute("ALTER TABLE playlists ADD COLUMN shared INTEGER DEFAULT 0")
    except: pass

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
