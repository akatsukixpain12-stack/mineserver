# Mineserver web authentication

Mineserver is a web hosting control plane. Google Identity Services authenticates the browser, and FastAPI verifies the Google ID token server-side. The verified Google account subject is used as the persistent server owner ID.

## Required Google setup

Set `GOOGLE_CLIENT_ID` on the Mineserver Cloud Run control plane.

For a Web application OAuth client, add the exact Mineserver web origin to **Authorized JavaScript origins**. Google documents that the Web Client ID identifies the application and that the site's origin must be registered. citeturn635625search0turn635625search2

For GitHub Pages/static hosting, set the Mineserver API URL in the login panel. The static frontend cannot magically discover an unrelated Cloud Run hostname.

## Persistent servers

The control plane stores each server with the verified Google account subject as `owner_id`. Firestore is used when configured; local development falls back to SQLite.

The browser stores the short-lived ID token in `sessionStorage` and sends it as a Bearer token. No Google client secret is placed in the web UI.

## Native core

The `server/` directory is the headless native Mineserver core used by the web control plane. Desktop-only/development-only Pumpkin app files are not part of the hosting panel. Upstream GPL-3.0 notices and required attribution remain in the native source.