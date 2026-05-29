"""
One-time script to get your Spotify refresh token.
Run locally, NOT on Render.

Usage:
  pip install requests
  python get_token.py

Then copy the printed REFRESH_TOKEN into your Render env vars.
"""

import os
import urllib.parse
import webbrowser
import json
import base64
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Fill these in ─────────────────────────────────────────────────────────────
CLIENT_ID     = input("Spotify Client ID: ").strip()
CLIENT_SECRET = input("Spotify Client Secret: ").strip()
REDIRECT_URI  = "http://127.0.0.1:8888/callback"

SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
    "app-remote-control",
    "streaming",
])

# ── Step 1: Open auth URL ──────────────────────────────────────────────────────
params = urllib.parse.urlencode({
    "client_id":     CLIENT_ID,
    "response_type": "code",
    "redirect_uri":  REDIRECT_URI,
    "scope":         SCOPES,
    "show_dialog":   "true",
})
auth_url = f"https://accounts.spotify.com/authorize?{params}"
print(f"\nOpening browser for Spotify auth...\n{auth_url}\n")
webbrowser.open(auth_url)

# ── Step 2: Catch the callback ─────────────────────────────────────────────────
auth_code = None

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        qs     = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            auth_code = qs["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Authorised! You can close this tab.</h2>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h2>Error - no code returned.</h2>")
    def log_message(self, *a): pass  # suppress logs

server = HTTPServer(("localhost", 8888), Handler)
print("Waiting for Spotify callback on http://localhost:8888/callback ...")
server.handle_request()

if not auth_code:
    print("No auth code received. Exiting.")
    raise SystemExit(1)

# ── Step 3: Exchange code for tokens ──────────────────────────────────────────
r = requests.post(
    "https://accounts.spotify.com/api/token",
    data={
        "grant_type":   "authorization_code",
        "code":         auth_code,
        "redirect_uri": REDIRECT_URI,
    },
    auth=(CLIENT_ID, CLIENT_SECRET),
)
r.raise_for_status()
tokens = r.json()

# ── Done ───────────────────────────────────────────────────────────────────────
print("\n" + "─" * 60)
print("✅  Success! Add these to your Render environment variables:\n")
print(f"  SPOTIFY_CLIENT_ID      = {CLIENT_ID}")
print(f"  SPOTIFY_CLIENT_SECRET  = {CLIENT_SECRET}")
print(f"  SPOTIFY_REFRESH_TOKEN  = {tokens['refresh_token']}")
print("─" * 60 + "\n")
