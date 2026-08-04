# Changelog

All notable changes to Butler are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [1.1.0] - 2026-08-03

### Added
- **Single sign-on (SSO) login** via Google or any self-hosted OIDC provider (Authelia, Authentik, Keycloak, and similar) -- alongside the existing username/password accounts, not a replacement. Enable as many providers at once as you want (`OIDC_PROVIDERS` in `.env`); each shows as its own button on the login screen. New identities need an invite code the first time, exactly like normal registration, except the very first SSO login ever on a fresh server bootstraps the admin account.
- **Apple Sign In support** -- written and logic-verified (ES256 client-secret signing, `response_mode=form_post` handling), but shipped commented out pending real Apple Developer Program credentials. Straightforward to re-enable later.
- **API keys** -- generate a personal key from account settings (or `POST /auth/api-keys`) and use it in place of a password. Solves the gap SSO otherwise creates: SSO-only accounts have no real password, so without this they'd have no way to authenticate third-party Subsonic clients (DSub, Substreamer, Symfonium, etc.) or anything else that only understands username/password. No client-side changes needed -- a key just works as a password.
- **Android SSO support** -- server-select and login are now two separate screens (server address chosen once, remembered after), matching the flow most self-hosted mobile apps use. SSO opens in a Chrome Custom Tab (your browser's real session/password manager, not an in-app WebView) and hands control back to the app via a deep link once the provider redirects back.
- **Admin setting: automatic downloads toggle** -- turn off yt-dlp auto-fetching on play/search to freeze the library to what's already downloaded or manually uploaded. Existing songs keep playing either way; this only affects fetching new ones. Search also now honors this: with it off, `/search` stays local-only instead of still reaching out to YouTube live.
- **Expanded Subsonic API compatibility**: `getAlbumList2` (random/newest/frequent/recent/starred/alphabetical browsing -- previously missing entirely, which broke the primary "Albums" tab in most Subsonic clients), `getRandomSongs`, real playlist management (`createPlaylist`/`updatePlaylist`/`deletePlaylist`, not just read-only), `getLyricsBySongId` exposing Butler's real synced lyrics to any OpenSubsonic-aware client, a `setRating` shim onto the existing like/star system, `getOpenSubsonicExtensions` and the mandatory `openSubsonic: true` response flag (capability-detecting clients like Substreamer gate features -- including playlists -- on this being present), and valid-empty responses for `getGenres`/`getNowPlaying`/`getPodcasts`/`getInternetRadioStations`/`getBookmarks`/`getShares` so clients that probe them on connect don't treat an unimplemented feature as a broken server.
- **`CLIENT_API.md`** -- a full reference for anyone building their own client, covering the Subsonic-compatible layer, the complete native API (verified against the live schema and real request/response pairs), and a minimal end-to-end walkthrough for each.

### Fixed
- API key display had no way to actually copy it on mobile (plain text, no selectable field). Now a proper input with a Copy button.
- README incorrectly documented `lossless_downloads` as an env var (`ADMIN_LOSSLESS_DOWNLOAD`); it's actually a runtime admin-panel setting. Corrected, and documented alongside the automatic-downloads toggle.

## [1.0.0-beta] - 2026-07-29

Initial public beta release. Real album art and artist bios, live synced lyrics (web + Android), ListenBrainz scrobbling, Subsonic API compatibility (read-only), manual upload folder, cross-device playback sync, near-1:1 native Android app with offline downloads and Android Auto.
