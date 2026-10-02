# Deploying VERTEX to Railway + Vercel (no VPS)

This is the alternative to `DEPLOYMENT.md` (VPS + Nginx + Certbot). It uses
the same pattern as this account's other always-on project (Bid Copilot):

1. **Railway** — runs the FastAPI backend as an always-on Docker container
   (the continuous 24/7 scan/analysis loop needs a long-lived process, which
   is why the backend can't go on Vercel — Vercel is serverless/request-driven
   and would kill the background loop between requests).
2. **Vercel** — hosts the Next.js dashboard (static + serverless, free tier
   is enough for this).

No VPS to rent, no SSH, no Nginx/Certbot to configure — both platforms give
you HTTPS and a public domain automatically. Both also run their infra
outside Iran, so Binance/Twelve Data/Finnhub are reachable normally (unlike
an Iran-hosted VPS, where Binance in particular actively blocks the IP
range).

You'll deploy straight from your own machine with each platform's CLI — no
GitHub repo required, though you can connect one later if you'd rather deploy
by `git push`.

## 0. Prerequisites on your machine

- Unzip the `vertex.zip` you received somewhere on your computer.
- Install Node.js 18+ if you don't already have it (you need it for the
  Railway/Vercel CLIs either way, and you already needed it for Bid Copilot).

## 1. Deploy the backend to Railway

```bash
npm install -g @railway/cli
railway login          # opens a browser to sign in / sign up
cd vertex               # the unzipped project root — railway.toml lives here
railway init            # creates a new Railway project, pick a name like "vertex"
railway up              # uploads this directory and builds it with backend/Dockerfile
```

Railway auto-detects `railway.toml` at the repo root, which points it at
`backend/Dockerfile` and sets the health check to `/api/health`.

**After the first deploy, in the Railway dashboard** (railway.app → your
project → the service that was just created):

1. **Settings → Networking → Generate Domain** — gives you a public URL like
   `https://vertex-backend-production.up.railway.app`. Copy it.
2. **Settings → Volumes → New Volume** — mount a volume at `/data` (this is
   where SQLite persists alerts/signals/trade-call history across restarts —
   without it, a redeploy wipes history).
3. **Variables** — add every key from your `.env` file (the same ones you
   already filled in: `VERTEX_FOREX_API_KEY`, `VERTEX_ECONOMIC_CALENDAR_API_KEY`,
   etc.), plus:
   ```
   VERTEX_DATABASE_PATH=/data/vertex.db
   VERTEX_CORS_ORIGINS=https://your-project.vercel.app
   ```
   (You won't have the real Vercel URL yet — come back and set this after
   step 2. Leaving it as `http://localhost:3000` temporarily is fine; the
   backend will just reject browser requests from the dashboard until you
   fix it.)

Railway injects its own `$PORT` — the Dockerfile already respects that
(`--port ${PORT:-8000}`), so you don't need to set `PORT` yourself.

Verify it's alive:
```bash
curl https://YOUR-RAILWAY-DOMAIN/api/health
```

## 2. Deploy the frontend to Vercel

```bash
npm install -g vercel
cd vertex/frontend
vercel login
vercel --prod
```

When prompted, accept the defaults (it auto-detects Next.js). Before or
right after the first deploy, set the environment variable in the Vercel
dashboard (Project → Settings → Environment Variables), for **Production**:

```
NEXT_PUBLIC_VERTEX_API_URL=https://YOUR-RAILWAY-DOMAIN
```

`NEXT_PUBLIC_*` vars are baked in at build time, so after setting/changing
it you need to redeploy: `vercel --prod` again (or click **Redeploy** in the
dashboard).

## 3. Close the loop: point CORS at the real Vercel domain

Once Vercel gives you the real domain (`https://your-project.vercel.app`),
go back to **Railway → Variables** and set:

```
VERTEX_CORS_ORIGINS=https://your-project.vercel.app
```

Railway redeploys automatically when a variable changes. Reload the
dashboard — live data, alerts and the Trade Desk should now load without
CORS errors in the browser console.

## 4. Keep it updated

```bash
# backend
cd vertex && railway up

# frontend
cd vertex/frontend && vercel --prod
```

## Notes

- **Cost**: Railway's Hobby plan is ~$5/month (or start on the one-time $5
  trial credit); Vercel's free (Hobby) tier is enough for this dashboard.
- **SQLite is fine here** — light polling traffic, and the Railway Volume
  keeps it durable across deploys/restarts. If you ever outgrow it, swap
  `storage/db.py` for Postgres (e.g. a Supabase project, same as Bid Copilot)
  without touching the API surface.
- **Telegram alerts** keep firing even with the dashboard tab closed, as
  long as the Railway service is running — that's the whole point of a
  long-lived container instead of a VPS you have to keep patched yourself.
- If you'd rather deploy by `git push` instead of the CLI, push this project
  to a GitHub repo and connect it from each platform's dashboard
  ("New Project → Deploy from GitHub repo", root directory `frontend` for
  Vercel, repo root for Railway) — functionally identical, just a different
  trigger for redeploys.
