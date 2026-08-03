import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# `or` rather than getenv's own default: an empty string in .env (which
# .env.example ships, so people leave it blank on purpose) should fall
# through to the default too, not be treated as "explicitly set to ''".
MUSIC_DIR = os.getenv("MUSIC_DIR") or str(BASE_DIR / "music")
UPLOADS_DIR = os.getenv("UPLOADS_DIR") or str(BASE_DIR / "uploads")
SECRET_KEY = os.getenv("SECRET_KEY") or "changeme"
DATABASE_URL = os.getenv("DATABASE_URL") or "butler.db"
SONGS_DB_PATH = os.getenv("SONGS_DB_PATH") or str(BASE_DIR / "songs_meta.db")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
# Must match a Redirect URI registered in your Spotify dev dashboard.
# Example for LAN: http://dgserver.local:8080/spotify/auth/callback
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "")

# Optional: SSO login, one or more providers at once. Set OIDC_PROVIDERS
# to a comma list of provider keys to enable -- 'google', 'github', and/or
# any number of your own custom keys for self-hosted OIDC (Authelia,
# Authentik, Keycloak, etc). Whatever's enabled shows up as its own
# button on the login screen; leave OIDC_PROVIDERS blank to show none.
# All providers share one redirect URI -- register this same URL with
# every provider's console, e.g. https://spotify.danielslefhosted.xyz/auth/oidc/callback
OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "")

_provider_keys = [k.strip() for k in (os.getenv("OIDC_PROVIDERS") or "").split(",") if k.strip()]

# Built once at import time so oidc.py doesn't need to know about env
# var naming -- each entry is everything that provider's flow needs.
# 'kind' picks the code path in oidc.py: 'google' and any custom key use
# the generic discovery-based OIDC flow (google's issuer is fixed since
# https://accounts.google.com/.well-known/openid-configuration is
# well-known and doesn't need a per-deployment env var). 'apple' is
# real OIDC too (fixed issuer https://appleid.apple.com) but Apple
# doesn't hand out a static client_secret -- it has to be a short-lived
# ES256 JWT Butler signs itself with your Apple private key, so it needs
# three extra values (team id, key id, the .p8 key) instead of one.
PROVIDERS = {}
for _key in _provider_keys:
    _prefix = _key.upper()
    _client_id = os.getenv(f"{_prefix}_CLIENT_ID", "")
    # Apple support commented out for now (per Daniel) -- code is still here, just inert.
    #     if _key == "apple":
    #         _team_id = os.getenv("APPLE_TEAM_ID", "")
    #         _key_id = os.getenv("APPLE_KEY_ID", "")
    #         _private_key = os.getenv("APPLE_PRIVATE_KEY", "").replace(chr(92)+chr(110), chr(10))
    #         if not (_client_id and _team_id and _key_id and _private_key and OIDC_REDIRECT_URI):
    #             continue
    #         PROVIDERS["apple"] = {
    #             "kind": "apple",
    #             "client_id": _client_id,  # this is your Apple "Services ID", not an App ID
    #             "team_id": _team_id,
    #             "key_id": _key_id,
    #             "private_key": _private_key,
    #             "issuer": "https://appleid.apple.com",
    #             "display_name": os.getenv("APPLE_DISPLAY_NAME") or "Sign in with Apple",
    #         }
    #         continue
    _client_secret = os.getenv(f"{_prefix}_CLIENT_SECRET", "")
    if not (_client_id and _client_secret and OIDC_REDIRECT_URI):
        continue
    if _key == "google":
        PROVIDERS["google"] = {
            "kind": "google",
            "client_id": _client_id,
            "client_secret": _client_secret,
            "issuer": "https://accounts.google.com",
            "display_name": os.getenv("GOOGLE_DISPLAY_NAME") or "Sign in with Google",
        }
    else:
        _issuer = os.getenv(f"{_prefix}_ISSUER", "")
        if not _issuer:
            continue
        PROVIDERS[_key] = {
            "kind": "oidc",
            "client_id": _client_id,
            "client_secret": _client_secret,
            "issuer": _issuer,
            "display_name": os.getenv(f"{_prefix}_DISPLAY_NAME") or f"Sign in with {_key.capitalize()}",
        }
del _provider_keys
