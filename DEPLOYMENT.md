# Deploying VERTEX to your own VPS + domain

This guide takes you from a bare Ubuntu 22.04+ VPS to `https://yourdomain.com`
serving the dashboard, with the API behind the same domain on `/api` and `/ws`.

## 1. Get a VPS and point your domain at it

1. Rent any VPS (DigitalOcean, Hetzner, OVH, etc.) — 1 vCPU / 1-2GB RAM is enough to start.
2. In your domain registrar's DNS panel, add an **A record**: `yourdomain.com -> <VPS IP>`.
   Wait for DNS to propagate (a few minutes to a few hours).

## 2. Install Docker on the VPS

```bash
ssh root@<VPS IP>
curl -fsSL https://get.docker.com | sh
apt-get install -y docker-compose-plugin
```

## 3. Upload the project and configure it

```bash
# from your own machine
scp -r vertex root@<VPS IP>:/opt/vertex

# on the VPS
cd /opt/vertex
cp .env.example .env
nano .env   # fill in whatever keys you have (see below) — crypto works with none
```

At minimum, set:
```
VERTEX_CORS_ORIGINS=https://yourdomain.com
NEXT_PUBLIC_VERTEX_API_URL=https://yourdomain.com/api
```

## 4. Add Nginx as a reverse proxy with HTTPS

Install Nginx and Certbot on the host (outside Docker is simplest):

```bash
apt-get install -y nginx certbot python3-certbot-nginx
```

Create `/etc/nginx/sites-available/vertex`:

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    location / {
        proxy_pass http://127.0.0.1:3000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/vertex /etc/nginx/sites-enabled/vertex
nginx -t && systemctl reload nginx
certbot --nginx -d yourdomain.com   # issues + installs a free HTTPS cert, auto-renews
```

## 5. Start the stack

```bash
cd /opt/vertex
docker compose --env-file .env up --build -d
docker compose logs -f   # watch it come up; Ctrl+C to stop watching (containers keep running)
```

Visit `https://yourdomain.com`. The dashboard should show live crypto prices
within a few seconds (Binance's public API needs no key). Forex/metals and
the news guard will show "not configured" until you add the free API keys
described in `.env.example` — the panel is honest about this rather than
faking data.

## 6. Keep it updated

```bash
cd /opt/vertex
git pull   # or re-upload with scp
docker compose --env-file .env up --build -d
```

## 7. Optional: 24/7 Telegram alerts

Even with the browser closed, the backend keeps scanning and will push to
Telegram if `VERTEX_TELEGRAM_BOT_TOKEN` / `VERTEX_TELEGRAM_CHAT_ID` are set
(see `.env.example` for the two-step setup with @BotFather).

## Notes on cost and reliability

- A $5-6/mo VPS is enough for this workload (light polling + SQLite).
- SQLite with WAL mode handles this traffic fine; if you outgrow it, swap
  `storage/db.py` for Postgres without touching the API surface.
- Back up `/opt/vertex/data/vertex.db` periodically if alert/signal history matters to you.
- If you'd rather not manage a VPS yourself, the frontend (Next.js) also
  deploys cleanly to Vercel; the backend still needs a host that can run a
  long-lived process (Docker on any VPS, Fly.io, Railway, etc.) since it
  scans continuously in the background — that doesn't fit a serverless model.
