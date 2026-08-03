"""
API keys -- long-lived credentials a user generates for themselves so
non-browser clients (third-party Subsonic apps, scripts, anything that
only understands a username/password pair) can still authenticate once
SSO is in the picture.

This exists specifically because an SSO-only account has no usable local
password (see oidc.py's _locked_password_hash -- it's a random value
nobody, including the account owner, knows). Without this, an SSO-only
user would be locked out of every Subsonic client, which defeats half the
point of self-hosting: you can log into the web/Android app through your
identity provider, but DSub/Symfonium/etc. have no OAuth flow to piggyback
on, so they need *something* password-shaped to send.

A generated key is used exactly like a password: give a Subsonic client
your Butler username and the key as the password field. No client-side
support for anything new required.

Design note: keys are hashed with SHA-256, not bcrypt like real user
passwords. That's intentional, not a shortcut -- these are 256-bit random
tokens the user never chooses, so there's nothing for bcrypt's slow,
salted hashing to protect against that a fast, indexed exact-match lookup
doesn't already handle just as securely. Iterating every stored key
through a bcrypt verify on every authentication attempt would also just
be slower for no real benefit.
"""

import hashlib
import secrets
from database import get_db

KEY_PREFIX = "butler_"


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_key(user_id: int, label: str) -> str:
    """Creates and stores a new key, returns the full plaintext key.
    This is the ONLY time the full key is ever available -- only its
    hash and a short display prefix are kept from here on."""
    label = (label or "").strip() or "Unnamed key"
    raw = secrets.token_urlsafe(32)
    full_key = f"{KEY_PREFIX}{raw}"
    db = get_db()
    db.execute(
        "INSERT INTO api_keys (user_id, label, key_hash, key_prefix) VALUES (?,?,?,?)",
        (user_id, label, _hash(full_key), full_key[:len(KEY_PREFIX) + 6]),
    )
    db.commit()
    db.close()
    return full_key


def list_keys(user_id: int) -> list:
    db = get_db()
    rows = db.execute(
        "SELECT id, label, key_prefix, created_at, last_used_at FROM api_keys WHERE user_id=? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def revoke_key(user_id: int, key_id) -> bool:
    """Returns False if the key doesn't exist or isn't owned by this user
    (callers should treat that as a 404, not silently succeed)."""
    db = get_db()
    owned = db.execute("SELECT id FROM api_keys WHERE id=? AND user_id=?", (key_id, user_id)).fetchone()
    if not owned:
        db.close()
        return False
    db.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
    db.commit()
    db.close()
    return True


def find_user_by_key(key: str):
    """Looks up which user a plaintext key belongs to and touches
    last_used_at. Returns the user row as a dict, or None if the key is
    missing, malformed, or revoked. Cheap early-out on the prefix check
    avoids a DB round trip for anything that obviously isn't one of ours
    (e.g. a real account password being tried here by a naive caller)."""
    if not key or not key.startswith(KEY_PREFIX):
        return None
    key_hash = _hash(key)
    db = get_db()
    row = db.execute(
        "SELECT u.* FROM api_keys ak JOIN users u ON u.id = ak.user_id WHERE ak.key_hash=?",
        (key_hash,),
    ).fetchone()
    if row:
        db.execute("UPDATE api_keys SET last_used_at=CURRENT_TIMESTAMP WHERE key_hash=?", (key_hash,))
        db.commit()
    db.close()
    return dict(row) if row else None
