# Covered Call Strategy Analyser

A FastAPI + Streamlit application that analyses covered call strategies using live NSE/BSE market data from the ICICI Breeze API.

---

## Architecture

```
covered-call-analyser/
├── backend/
│   ├── main.py             # FastAPI entry point + API routes
│   ├── breeze_client.py    # Breeze API session management
│   ├── data_fetcher.py     # get_cmp, get_lot_size, get_option_chain
│   ├── calculator.py       # Covered call maths (pure functions)
│   ├── models.py           # Pydantic request/response models
│   ├── config.py           # Environment variable config (pydantic-settings)
│   ├── requirements.txt
│   ├── .env.example        # Template — copy to .env and fill in
│   └── tests/
│       └── test_phase1.py
├── frontend/
│   ├── app.py              # Streamlit UI
│   └── requirements.txt
├── render.yaml             # Render deployment config
└── README.md
```

---

## Local Setup

### 1. Prerequisites

- Python 3.10 or higher (`python --version`)
- Git
- An ICICI Direct account with Breeze API access

### 2. Clone and set up virtual environment

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd covered-call-analyser
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
pip install -r frontend/requirements.txt
```

### 3. Configure environment variables

```bash
cp backend/.env.example backend/.env
# Edit backend/.env with your real credentials
```

### 4. Start the backend

```bash
# Run from the covered-call-analyser/ directory
uvicorn backend.main:app --reload --port 8000
```

Visit [http://localhost:8000/docs](http://localhost:8000/docs) for the Swagger UI.

### 5. Start the frontend (in a second terminal)

```bash
BACKEND_URL=http://localhost:8000 streamlit run frontend/app.py
```

Visit [http://localhost:8501](http://localhost:8501).

---

## Generating a Breeze Session Token (Daily)

The Breeze API session token **expires every day at midnight**. You must generate a new one each morning:

1. Visit [https://api.icicidirect.com/apiuser/login?api_key=YOUR_API_KEY](https://api.icicidirect.com/apiuser/login?api_key=YOUR_API_KEY)
2. Log in with your ICICI Direct credentials + TOTP (Google Authenticator).
3. After login you are redirected to:
   ```
   https://your-redirect-url/?apisession=XXXXXXXXXXXXX
   ```
4. Copy the value after `apisession=` — this is your `BREEZE_SESSION_TOKEN`.

**Locally:** Update `backend/.env` and restart uvicorn.

**On Render:** Either:
- Update the `BREEZE_SESSION_TOKEN` environment variable in the Render dashboard and trigger a manual redeploy, OR
- Call the refresh endpoint (Phase 5):
  ```bash
  curl -X POST https://covered-call-backend.onrender.com/refresh-session \
    -H "Content-Type: application/json" \
    -d '{"session_token": "NEW_TOKEN_HERE"}'
  ```

---

## Running Tests

```bash
# From covered-call-analyser/ directory
pytest backend/tests/ -v

# Run only offline tests (no Breeze credentials needed):
pytest backend/tests/test_phase1.py -v

# Run the live integration test (requires real .env):
pytest backend/tests/test_phase1.py::test_live_cmp_mnm -v -s
```

---

## Testing with Hoppscotch

[Hoppscotch](https://hoppscotch.io) is a browser-based API client (like Postman).

### Phase 1 Endpoints

| Endpoint | Method | URL | Expected Response |
|----------|--------|-----|-------------------|
| Health check | `GET` | `http://localhost:8000/health` | `{"status":"ok","breeze_connected":true}` |
| Get CMP — RELIANCE | `GET` | `http://localhost:8000/quote/RELIANCE` | `{"symbol":"RELIANCE","cmp":2850.5,...}` |
| Get CMP — M&M | `GET` | `http://localhost:8000/quote/M%26M` | `{"symbol":"M&M","cmp":2104.0,...}` |

**Steps in Hoppscotch:**
1. Open [https://hoppscotch.io](https://hoppscotch.io)
2. Set method to `GET`, paste the URL
3. Click **Send**
4. Verify the response body and status code (should be `200 OK`)

---

## Deploying to Render Web Services

There are two ways to deploy. **Option A (Blueprint)** is faster if you want both services created automatically. **Option B (Manual)** gives you more control.

---

### Option A — Blueprint deploy (recommended)

A Blueprint reads `render.yaml` and creates both services in one shot.

1. Push this repo to GitHub (confirm the `render.yaml` is at the repo root level).
2. Go to [https://dashboard.render.com](https://dashboard.render.com) → click **New** → **Blueprint**.
3. Connect your GitHub account if not already done → select this repository.
4. Render will detect `render.yaml` and show you a preview of two services:
   - `covered-call-backend`
   - `covered-call-frontend`
5. Click **Apply** — Render starts building both.
6. **The build will succeed but the backend will crash** on first start because the three secret env vars are not set yet. That is expected. Continue to step 7.
7. Go to **Dashboard → covered-call-backend → Environment**.
8. Click **Add Environment Variable** and add each of the following:

   | Key | Value |
   |-----|-------|
   | `BREEZE_API_KEY` | your API key from ICICI Direct developer portal |
   | `BREEZE_API_SECRET` | your API secret |
   | `BREEZE_SESSION_TOKEN` | today's session token (see section below) |

9. Click **Save Changes** — Render auto-redeploys the backend.
10. Wait for the backend deploy to finish. Click the backend service URL (e.g. `https://covered-call-backend.onrender.com`) and confirm you see the API docs page.
11. Copy that backend URL. Go to **Dashboard → covered-call-frontend → Environment**.
12. Edit `BACKEND_URL` → paste the exact backend URL (no trailing slash).
13. Click **Save Changes** — Render redeploys the frontend.
14. Open the frontend URL — you should see the health badge turn green.

---

### Option B — Manual service creation

Use this if you want to create services one at a time without a Blueprint.

#### Step 1 — Create the backend service

1. Dashboard → **New** → **Web Service**.
2. Connect your GitHub repo → select it.
3. Fill in:

   | Field | Value |
   |-------|-------|
   | **Name** | `covered-call-backend` |
   | **Region** | Singapore (or closest to you) |
   | **Branch** | `main` |
   | **Runtime** | `Python 3` |
   | **Build Command** | `pip install -r covered-call-analyser/backend/requirements.txt` |
   | **Start Command** | `cd covered-call-analyser && uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |
   | **Plan** | Free (or Starter for always-on) |

4. Scroll down to **Environment Variables** → add:

   | Key | Value |
   |-----|-------|
   | `BREEZE_API_KEY` | your key |
   | `BREEZE_API_SECRET` | your secret |
   | `BREEZE_SESSION_TOKEN` | today's token |
   | `DEFAULT_BROKERAGE` | `40.0` |
   | `DEFAULT_STT_RATE` | `0.001` |
   | `DEFAULT_GST_RATE` | `0.18` |
   | `LOG_LEVEL` | `INFO` |

5. Click **Create Web Service**. Wait for the deploy to complete.
6. Confirm: visit `https://covered-call-backend.onrender.com/health` — you should see `{"status":"ok","breeze_connected":true}`.

#### Step 2 — Create the frontend service

1. Dashboard → **New** → **Web Service**.
2. Same GitHub repo.
3. Fill in:

   | Field | Value |
   |-------|-------|
   | **Name** | `covered-call-frontend` |
   | **Region** | Singapore (match backend) |
   | **Branch** | `main` |
   | **Runtime** | `Python 3` |
   | **Build Command** | `pip install -r covered-call-analyser/frontend/requirements.txt` |
   | **Start Command** | `streamlit run covered-call-analyser/frontend/app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false` |
   | **Plan** | Free |

4. Environment Variables → add:

   | Key | Value |
   |-----|-------|
   | `BACKEND_URL` | `https://covered-call-backend.onrender.com` |

5. Click **Create Web Service**.

---

### Updating BREEZE_SESSION_TOKEN daily (on Render)

The session token expires at midnight every day. Each morning:

1. Generate a new token (see **Generating a Breeze Session Token** section above).
2. Dashboard → **covered-call-backend** → **Environment**.
3. Find `BREEZE_SESSION_TOKEN` → click **Edit** → paste the new token → **Save**.
4. Render automatically redeploys (takes ~60 seconds on free tier).
5. Confirm: hit `/health` again — `breeze_connected` should be `true`.

**Faster alternative (Phase 5):** Call the `/refresh-session` endpoint directly — no redeploy needed.

---

### Free tier — important gotchas

- **Free services sleep after 15 minutes of inactivity.** The first request after sleep takes 30–60 seconds. Upgrade to Starter (£7/mo) if this is unacceptable.
- **Build minutes are limited on free.** If a build fails due to timeout, retry manually via Dashboard → service → **Manual Deploy**.
- **Both services must be in the same region** to keep latency low between frontend and backend calls.

---

## Environment Variable Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BREEZE_API_KEY` | ✅ | — | ICICI Breeze API key |
| `BREEZE_API_SECRET` | ✅ | — | ICICI Breeze API secret |
| `BREEZE_SESSION_TOKEN` | ✅ | — | Daily session token (regenerate each morning) |
| `DEFAULT_BROKERAGE` | ❌ | `40.0` | Fixed brokerage per option leg (INR) |
| `DEFAULT_STT_RATE` | ❌ | `0.001` | STT rate (0.1% on option premium) |
| `DEFAULT_GST_RATE` | ❌ | `0.18` | GST on brokerage (18%) |
| `QUOTAGUARDSTATIC_URL` | ❌ | `None` | QuotaGuard Static proxy URL (Phase 5) |
| `LOG_LEVEL` | ❌ | `INFO` | Python logging level |
| `BACKEND_URL` | ✅ (frontend) | `http://localhost:8000` | FastAPI backend URL (set on Render frontend service) |

---

## Whitelisting Static IP on ICICI Breeze (Phase 5)

1. Sign up for [QuotaGuard Static](https://quotaguard.com) (available as a Render add-on or standalone).
2. You will receive two static IP addresses.
3. Log in to [https://api.icicidirect.com](https://api.icicidirect.com) → API Settings → IP Whitelist.
4. Add both QuotaGuard IPs.
5. Set `QUOTAGUARDSTATIC_URL` environment variable on your Render backend service.

---

## Phase Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Complete | Project scaffold, Breeze auth, `/health`, `/quote` |
| 2 | 🔜 | Lot size lookup, option chain fetcher, expiry dates |
| 3 | 🔜 | Calculator engine, `/analyse` endpoint, unit tests |
| 4 | 🔜 | Streamlit UI — full analysis display |
| 5 | 🔜 | Render deployment, static IP, session refresh |
| 6 | 🔜 | Caching, PDF export, Telegram alerts, multi-stock |
