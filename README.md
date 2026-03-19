# AI Services Orchestrator

A secure proxy for Google Gemini API and Vertex AI with automatic key rotation, request statistics, and an admin API.

## What it does

- Receives AI requests from your backend and forwards them to Google Gemini / Vertex AI
- Rotates API keys and service accounts automatically (round-robin)
- Retries on rate limits (429), blocked keys (403), and service errors (503)
- Records request statistics in PostgreSQL (tokens, latency, errors)
- Provides an admin API with full CRUD for keys/credentials, stats, and health checks

## Quick start

```bash
git clone https://github.com/Crasow/orchestrator.git
cd orchestrator

mkdir -p credentials secrets
# Place credentials (see below)

cp .env.example .env
# Edit .env — set SECURITY__ADMIN_SECRET, SECURITY__ADMIN_USERNAME, SECURITY__ADMIN_PASSWORD_HASH

docker compose -f docker-compose.yaml up -d --build
docker compose -f docker-compose.yaml exec orchestrator alembic upgrade head

curl http://localhost:8000/health
```

See **[RUNBOOK.md](RUNBOOK.md)** for the full deployment guide including password hash generation, backups, and troubleshooting.

## Credentials

```
credentials/
├── gemini/
│   └── api_keys.json          # ["AIzaSy...", "AIzaSy..."]
└── vertex/
    ├── project-a-sa.json      # Google service account JSON
    └── project-b-sa.json
```

## Proxy usage

Send requests to the orchestrator instead of Google directly. No API key needed — the orchestrator injects credentials automatically.

**Gemini:**
```
POST /v1beta/models/gemini-2.0-flash:generateContent
```

**Vertex AI:**
```
POST /v1/projects/ANY/locations/us-central1/publishers/google/models/gemini-2.0-flash:generateContent
```

Access is controlled by IP whitelist (`SECURITY__ALLOWED_CLIENT_IPS`).

**Key management** — add, update, and remove API keys/credentials via the admin API without restarting:
```
POST   /admin/keys/gemini              # add keys
DELETE /admin/keys/gemini/{index}       # remove a key
POST   /admin/keys/vertex              # upload service account
DELETE /admin/keys/vertex/{project_id}  # remove credential
```

See **[API_DOCS.md](API_DOCS.md)** for full API reference including admin endpoints and configuration.

## Development

```bash
# Hot reload, PostgreSQL port exposed
docker compose up
```

## Testing

```bash
uv run pytest
uv run pytest --cov=app
```

## Tech stack

- **FastAPI** — async web framework
- **PostgreSQL** + SQLAlchemy async — request statistics
- **Alembic** — database migrations
- **httpx** — async HTTP client for upstream requests
- **uv** — dependency management
