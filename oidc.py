"""
OIDC / SSO login -- multi-provider (Authorization Code + PKCE where the
provider supports it).

Each entry in config.PROVIDERS is one enabled provider (see config.py for
how OIDC_PROVIDERS/env vars build that dict). Two kinds:

  - 'google' / 'oidc' -- real OIDC, id_token verified via the provider's
    own JWKS. 'google' is the fixed accounts.google.com issuer; 'oidc'
    covers any self-hosted/custom provider (Authelia, Authentik,
    Keycloak, ...) discovered from its own issuer. Both use a normal
    static client_secret.
  - 'apple' -- also real OIDC (fixed issuer https://appleid.apple.com,
    real discovery doc, real JWKS), but Apple doesn't hand out a static
    client_secret -- it has to be a short-lived ES256 JWT that Butler
    signs itself with your Apple private key (Team ID + Key ID + the
    .p8 file), regenerated fresh for every token exchange. Apple also
    requires response_mode=form_post when requesting the name/email
    scopes, so its callback arrives as a POST with a form body instead
    of GET query params -- see the POST /auth/oidc/callback route in
    main.py, which shares the same core handling as the GET one.

Every provider shares one redirect_uri (config.OIDC_REDIRECT_URI) and one
callback route -- which provider a callback belongs to is looked up from
the `state` value, not the URL, so only one URI needs registering with
each provider's console no matter how many are enabled at once.

Flow:
  1. GET /auth/oidc/login?provider=<key>   -> redirect to that provider's
     authorize URL
  2. User authenticates with the provider
  3. GET or POST /auth/oidc/callback       -> exchange code for tokens,
     verify identity, find-or-create the local user, mint a Butler JWT,
     redirect back to the web app with the token in the URL *fragment*
     (never sent to the server or logged, unlike a query param).

Account linking: a brand-new identity (any provider) needs an invite
code, same as normal registration -- passed through as ?invite=... on
/auth/oidc/login and carried through the state. Exception: if the server
has zero users yet, the first SSO login bootstraps the admin account,
exactly like the existing first-user-skips-invite rule in /auth/register.
Once an identity is linked to a user row it can log in again with no
invite needed.
"""

import time
import base64
import hashlib
import secrets
import asyncio
import httpx
from urllib.parse import urlencode
from jose import jwt

from config import OIDC_REDIRECT_URI, PROVIDERS

OIDC_ENABLED = bool(PROVIDERS)


def list_providers() -> list:
    """What the login screen renders buttons from."""
    return [{"key": k, "display_name": v["display_name"]} for k, v in PROVIDERS.items()]


def _provider(key: str) -> dict:
    p = PROVIDERS.get(key)
    if not p:
        raise Exception(f"Unknown or disabled SSO provider: {key}")
    return p


# ── Discovery + JWKS caching (per issuer, so google/apple/each custom ───
# provider don't clobber each other's cache) ─────────────────────────────
_discovery_cache: dict = {}   # issuer -> discovery doc
_jwks_cache: dict = {}        # issuer -> {"keys": [...], "fetched_at": ts}
_JWKS_TTL_SECONDS = 3600
_cache_lock = asyncio.Lock()


async def get_discovery(issuer: str) -> dict:
    if issuer in _discovery_cache:
        return _discovery_cache[issuer]
    async with _cache_lock:
        if issuer in _discovery_cache:
            return _discovery_cache[issuer]
        url = issuer.rstrip("/") + "/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
        if r.status_code != 200:
            raise Exception(f"OIDC discovery failed for {issuer} ({r.status_code}): {r.text[:200]}")
        _discovery_cache[issuer] = r.json()
        return _discovery_cache[issuer]


async def _get_jwks(issuer: str) -> list:
    now = time.time()
    cached = _jwks_cache.get(issuer)
    if cached and now - cached["fetched_at"] < _JWKS_TTL_SECONDS:
        return cached["keys"]
    disc = await get_discovery(issuer)
    jwks_uri = disc.get("jwks_uri")
    if not jwks_uri:
        raise Exception(f"{issuer}'s discovery document has no jwks_uri")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(jwks_uri)
    if r.status_code != 200:
        raise Exception(f"Fetching JWKS from {issuer} failed ({r.status_code}): {r.text[:200]}")
    keys = r.json().get("keys", [])
    _jwks_cache[issuer] = {"keys": keys, "fetched_at": now}
    return keys


# Apple support commented out for now (per Daniel) -- code kept, just inert.
# def _apple_client_secret(provider: dict) -> str:
#     """Apple client_secret isn't a stored value -- it's a JWT Butler signs
#     on the spot with the ES256 private key from your .p8 file. Kept
#     short-lived (a few minutes) since we only need it to survive one
#     token-exchange request; no reason to hold a long-lived one in memory."""
#     now = int(time.time())
#     claims = {
#         "iss": provider["team_id"],
#         "iat": now,
#         "exp": now + 300,
#         "aud": "https://appleid.apple.com",
#         "sub": provider["client_id"],
#     }
#     return jwt.encode(claims, provider["private_key"], algorithm="ES256",
#                        headers={"kid": provider["key_id"]})


# ── PKCE + state ──────────────────────────────────────────────────────────
# Keyed by state: (provider_key, code_verifier, invite_code, client, created_at).
# Single-use, GC'd after 10 minutes same as spotify.py's _PENDING_STATE.
_PENDING: dict = {}


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


async def start_login(provider_key: str, invite_code: str = "", client: str = "web") -> str:
    """Create state + PKCE, stash it, return the authorize URL to
    redirect the browser to. `client` is "web" or "android" -- carried
    through the state so the callback knows whether to hand the token
    back via a URL fragment (web) or the app's deep link (android);
    every provider only ever sees the one fixed OIDC_REDIRECT_URI
    either way, this only affects Butler's own last-mile redirect."""
    provider = _provider(provider_key)
    state = secrets.token_urlsafe(16)
    verifier, challenge = _pkce_pair()

    _PENDING[state] = (provider_key, verifier, invite_code.strip(), client, time.time())
    cutoff = time.time() - 600
    for k in [k for k, v in _PENDING.items() if v[4] < cutoff]:
        _PENDING.pop(k, None)

    disc = await get_discovery(provider["issuer"])
    params = {
        "client_id": provider["client_id"],
        "response_type": "code",
        "redirect_uri": OIDC_REDIRECT_URI,
        # Apple support commented out for now (per Daniel) -- this used to
        # branch to "openid email name" + response_mode=form_post for
        # provider["kind"] == "apple". Restore that branch alongside
        # config.py's/find _apple_client_secret's commented block if it
        # comes back.
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return disc["authorization_endpoint"] + "?" + urlencode(params)


def consume_state(state: str):
    """Returns (provider_key, code_verifier, invite_code, client) or None
    if the state is unknown/expired."""
    entry = _PENDING.pop(state, None)
    if not entry:
        return None
    provider_key, verifier, invite_code, client, created_at = entry
    if time.time() - created_at > 600:
        return None
    return provider_key, verifier, invite_code, client


# ── Token exchange + identity verification ─────────────────────────────────

async def _exchange_oidc_code(provider: dict, code: str, code_verifier: str) -> dict:
    disc = await get_discovery(provider["issuer"])
    # Apple support commented out for now (per Daniel) -- this used to
    # branch to _apple_client_secret(provider) for provider["kind"] == "apple".
    client_secret = provider["client_secret"]
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            disc["token_endpoint"],
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OIDC_REDIRECT_URI,
                "client_id": provider["client_id"],
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )
    if r.status_code != 200:
        raise Exception(f"Token exchange failed ({r.status_code}): {r.text[:200]}")
    return r.json()


async def _verify_id_token(provider: dict, id_token: str, access_token: str = None) -> dict:
    """Verify signature (via provider JWKS), issuer, audience, expiry.
    Returns the decoded claims dict on success, raises on any failure."""
    issuer = provider["issuer"]
    disc = await get_discovery(issuer)
    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")
    alg = header.get("alg", "RS256")
    keys = await _get_jwks(issuer)
    key = next((k for k in keys if k.get("kid") == kid), None)
    if key is None:
        # kid rotated since our cache -- force one refresh and retry once
        if issuer in _jwks_cache:
            _jwks_cache[issuer]["fetched_at"] = 0.0
        keys = await _get_jwks(issuer)
        key = next((k for k in keys if k.get("kid") == kid), None)
    if key is None:
        raise Exception("id_token signed with an unknown key (kid not in provider JWKS)")
    decode_kwargs = {}
    if access_token:
        # Several providers (Authelia included) include an at_hash claim
        # binding the id_token to the access_token issued alongside it;
        # jose needs the actual access_token to verify that hash, or it
        # hard-errors rather than silently skipping the check.
        decode_kwargs["access_token"] = access_token
    claims = jwt.decode(
        id_token,
        key,
        algorithms=[alg],
        audience=provider["client_id"],
        issuer=disc["issuer"],
        **decode_kwargs,
    )
    return claims


async def exchange_and_verify(provider_key: str, code: str, code_verifier: str, extra: dict = None) -> dict:
    """The one entry point the callback routes need. `extra` carries
    provider-specific data pulled from the callback itself -- currently
    only Apple's one-time-only 'user' POST field (real name, only ever
    sent on the very first authorization) -- merged into the verified
    claims so find_or_create_user() sees it without knowing the source."""
    provider = _provider(provider_key)
    tokens = await _exchange_oidc_code(provider, code, code_verifier)
    id_token = tokens.get("id_token")
    if not id_token:
        raise Exception("Provider did not return an id_token")
    claims = await _verify_id_token(provider, id_token, tokens.get("access_token"))
    if extra and extra.get("name") and not claims.get("name"):
        claims = {**claims, "name": extra["name"]}
    return claims


# ── Local user provisioning ──────────────────────────────────────────────

def _locked_password_hash() -> str:
    """A bcrypt hash of a random value nobody knows -- used for SSO-only
    accounts so password_hash can stay NOT NULL without adding a usable
    local password. /auth/login will simply never verify against it."""
    from auth import hash_password
    return hash_password(secrets.token_urlsafe(32))


def _pick_username(db, claims: dict) -> str:
    base = (claims.get("preferred_username") or (claims.get("email") or "").split("@")[0]
            or claims.get("name") or claims.get("sub"))
    base = "".join(ch for ch in base if ch.isalnum() or ch in "._-") or "user"
    candidate = base
    n = 1
    while db.execute("SELECT id FROM users WHERE username=?", (candidate,)).fetchone():
        n += 1
        candidate = f"{base}{n}"
    return candidate


def find_or_create_user(claims: dict, invite_code: str) -> dict:
    """Look up a user by (issuer, sub); create one if this is the first
    login for that identity. Raises Exception with a user-facing message
    on invite/validation failures. Not async -- sqlite3 calls here are
    the same pattern as the rest of the app (get_db()/close() per call)."""
    from database import get_db
    sub = claims.get("sub")
    if not sub:
        raise Exception("SSO provider did not return a subject identifier")
    issuer = claims.get("iss")
    if not issuer:
        raise Exception("SSO provider did not return an issuer")

    db = get_db()
    try:
        existing = db.execute(
            "SELECT * FROM users WHERE oidc_issuer=? AND oidc_subject=?",
            (issuer, sub),
        ).fetchone()
        if existing:
            return dict(existing)

        is_first_user = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"] == 0
        invite = None
        if not is_first_user:
            invite_code = (invite_code or "").strip()
            if not invite_code:
                raise Exception("This SSO account isn't linked yet -- ask the admin for an invite code and try again with it")
            invite = db.execute(
                "SELECT * FROM invite_codes WHERE code=? AND used_by IS NULL",
                (invite_code,),
            ).fetchone()
            if not invite:
                raise Exception("Invalid or already-used invite code")

        username = _pick_username(db, claims)
        db.execute(
            "INSERT INTO users (username, password_hash, oidc_subject, oidc_issuer) VALUES (?,?,?,?)",
            (username, _locked_password_hash(), sub, issuer),
        )
        db.commit()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if invite:
            db.execute(
                "UPDATE invite_codes SET used_by=?, used_at=CURRENT_TIMESTAMP WHERE id=?",
                (user["id"], invite["id"]),
            )
            db.commit()
        return dict(user)
    finally:
        db.close()
