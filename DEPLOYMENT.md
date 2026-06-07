# Deploying InvoiceAI as a public multi-user app

This app now uses **Google Sign-In** as its only login. The same Google consent
that signs a user in also grants `gmail.readonly`, so each user sees only their
own invoices. Demo scale (≤100 users) needs **no paid Google verification** —
the OAuth app stays in **Testing** mode with manually-added test users.

> ⚠️ Testing-mode caveats: max 100 test users, and refresh tokens expire after
> ~7 days (users re-consent weekly). Moving the OAuth app to **Production**
> (verified) removes both limits but requires a Google CASA security assessment.

---

## 1. Google Cloud Console (one-time)

In project `invoiceai-497313` (or any project):

1. **APIs**: enable the **Gmail API**.
2. **OAuth consent screen**: User type **External**, publishing status **Testing**.
   - Scopes: `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`, `.../auth/gmail.readonly`.
   - Add every user under **Test users**.
3. **Credentials → Create OAuth client ID → Web application**:
   - Authorized redirect URIs:
     - `http://localhost:8000/api/auth/callback` (local dev)
     - `https://<your-app>.up.railway.app/api/auth/callback` (production)
   - Copy the **Client ID** and **Client Secret**.

> The old Desktop `credentials.json` is no longer used and can be deleted.

## 2. Supabase (one-time)

Run [`backend/db_schema.sql`](backend/db_schema.sql) in the Supabase SQL editor
to create the `users` table and add per-user isolation to `invoices`. Grab the
project URL and the **service-role** key from Project Settings → API.

## 3. Environment variables

Copy [`backend/.env.example`](backend/.env.example) → `backend/.env` and fill in.
Generate the two secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"                       # SESSION_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # TOKEN_ENC_KEY
```

Required: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_REDIRECT_URI`,
`SESSION_SECRET`, `TOKEN_ENC_KEY`, `GEMINI_API_KEY`, `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`.

## 4. Run locally

```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py            # http://localhost:8000
```

Open `http://localhost:8000` → you should see the **Sign in with Google** screen.

## 5. Deploy to Railway

1. Push the repo to GitHub and create a Railway project from it.
2. Railway uses the root [`Procfile`](Procfile) (`uvicorn ... --port $PORT`).
3. Add all env vars from step 3 in the Railway dashboard, and set
   `OAUTH_REDIRECT_URI` to the production callback URL.
4. Add that same production callback URL to the Google OAuth client (step 1).
5. Open the public URL and sign in as a test user.

## Security notes

- Refresh tokens are stored **Fernet-encrypted** in `users.refresh_token`.
- Every data endpoint requires a valid signed session cookie (`get_current_user`).
- All invoice queries filter by `user_email`; users cannot read each other's data.
- Rotate any previously-committed/exposed keys (Gemini, Supabase) before going public.
