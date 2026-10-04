# Mineserver Google authentication

Mineserver uses Google Identity Services for account login. The backend verifies the Google ID token and uses the stable Google account subject as the owner ID for persistent server records.

Set GOOGLE_CLIENT_ID on Cloud Run, add the deployed Mineserver origin to the OAuth client's Authorized JavaScript origins, and enable Firestore for persistent hosted server records.

Each server record is owned by the verified Google account subject. Firestore is used when configured; local development falls back to SQLite.

The browser keeps the ID token in sessionStorage and sends it in the Authorization header. Never put a Google client secret in frontend code.

The complete Pumpkin source tree is not yet vendored into this repository; the available GitHub connector cannot import the full external 164 MB / 13,505-file tree in one wholesale operation.