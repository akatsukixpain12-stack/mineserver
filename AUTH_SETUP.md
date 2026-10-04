# Mineserver authentication

Mineserver uses Google Identity Services for browser login. The browser receives a Google ID token and sends it to the same-origin FastAPI control plane as a Bearer token.

## Production

Deploy the complete Mineserver image to Cloud Run. Cloud Run serves both the frontend and FastAPI from the same origin:

https://mineserver.example.com/
https://mineserver.example.com/api/config
https://mineserver.example.com/api/auth/check
https://mineserver.example.com/api/servers
https://mineserver.example.com/api/catalog/versions

There is no API URL field in the web application.

Set GOOGLE_CLIENT_ID on Cloud Run. In Google Cloud Console, configure the OAuth Web client with the exact Mineserver web origin under Authorized JavaScript origins.

The backend verifies:
- Google issuer
- OAuth audience against GOOGLE_CLIENT_ID
- token expiry/signature
- the immutable Google sub account identifier

The verified sub is the owner ID for persisted servers.

## Local development

SQLite is used only when Firestore is unavailable. It is a development fallback, not the production datastore.

## Native runtime

server/ contains the headless Mineserver native runtime. The web application and native runtime remain separate components.
