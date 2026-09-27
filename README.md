# 🚀 xHamster Resolver API

Standalone **xHamster-only** REST API built with FastAPI and yt-dlp, following the simple structure of the Ak resolver projects.

## What it supports

- xHamster video URLs only
- Metadata returned by yt-dlp
- Progressive/direct video formats
- HLS/m3u8 formats when yt-dlp exposes them
- Audio-only formats when available
- Thumbnail information
- Per-IP rate limiting
- `/health` health check
- Docker deployment
- Render / Railway / VPS / Docker-compatible hosting

It does **not** include Diskwala, YouTube, Instagram, Telegram sessions, Chromium, Node.js, Cloudflare bypass, or FlareSolverr.

## Project structure

```text
xhamster-api/
├── app.py
├── config.py
├── xhamster_resolver.py
├── requirements.txt
├── Dockerfile
├── entrypoint.sh
├── .env.example
├── .dockerignore
├── .gitignore
└── README.md
```

## API

### Root

```http
GET /
```

### Health

```http
GET /health
```

### Resolve

```http
GET /api/xhamster?url=<XHAMSTER_VIDEO_URL>
```

Example:

```bash
curl --get 'http://localhost:8000/api/xhamster' \
  --data-urlencode 'url=https://xhamster.com/videos/example-video-name-1234567'
```

The response keeps yt-dlp's actual media URLs; the resolver does not invent a custom deep-link scheme.

## Run locally

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Then open:

```text
http://127.0.0.1:8000/docs
```

## Docker

```bash
docker build -t xhamster-api .
docker run -d --name xhamster-api \
  --restart unless-stopped \
  -p 8000:8000 \
  -e PORT=8000 \
  xhamster-api
```

## Render / Railway

Use the Dockerfile deployment option. The application reads the platform's `PORT` environment variable.

For a VPS, put Nginx/Caddy in front of port `8000` and add HTTPS with your preferred certificate provider.

## Environment variables

```env
PORT=8000
RATE_LIMIT_PER_MINUTE=30
```

Do not commit secrets into Git.

## Notes

A source video can be private, removed, region-restricted, login-gated, rate-limited, or otherwise unavailable to yt-dlp. In those cases the API returns HTTP `502` with the resolver error instead of pretending that a link was resolved.
