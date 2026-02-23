# API Documentation — AI Services Orchestrator

> Base URL: `http://<host>:8000`

---

# Part 1: Proxy API (Backend Integration)

The orchestrator is a transparent proxy to Google Gemini API and Vertex AI.
Your backend sends standard Google AI requests — the orchestrator injects credentials,
rotates keys, and retries on rate-limit errors automatically.

**No authentication tokens required.** Access is controlled by IP whitelist
(`SECURITY__ALLOWED_CLIENT_IPS` in `.env`).

---

## 1.1 Routing rules

All proxy requests go through `/v1/...` or `/v1beta/...` prefixes.
The orchestrator detects the provider by whether the path contains `projects/`:

| URL pattern | Provider | Auth injected |
|---|---|---|
| `/v1beta/models/...` | **Gemini** | `?key=<rotated_api_key>` query param |
| `/v1/projects/{any}/locations/...` | **Vertex AI** | `Authorization: Bearer <token>` header, project ID replaced |

**Supported HTTP methods:** GET, POST, PUT, DELETE, PATCH

---

## 1.2 Gemini requests

Send requests exactly as documented in the Google Gemini API, but to the orchestrator
instead of `generativelanguage.googleapis.com`. Do not include an API key — the
orchestrator appends one automatically.

### Text generation

```http
POST /v1beta/models/gemini-2.0-flash:generateContent
Content-Type: application/json

{
  "contents": [
    {
      "role": "user",
      "parts": [{ "text": "Explain quantum computing in simple terms" }]
    }
  ],
  "generationConfig": {
    "temperature": 0.7,
    "maxOutputTokens": 1024
  }
}
```

**Response:** Standard Gemini `GenerateContentResponse` JSON.

### Streaming

```http
POST /v1beta/models/gemini-2.0-flash:streamGenerateContent
Content-Type: application/json

{
  "contents": [
    { "role": "user", "parts": [{ "text": "Write a story" }] }
  ]
}
```

**Response:** Chunked transfer, each chunk is a JSON object with `candidates[]`.

### List models

```http
GET /v1beta/models
```

**Response:** `{ "models": [...] }` — full list of available models.

### Multi-turn chat

```http
POST /v1beta/models/gemini-2.0-flash:generateContent
Content-Type: application/json

{
  "contents": [
    { "role": "user", "parts": [{ "text": "What is Python?" }] },
    { "role": "model", "parts": [{ "text": "Python is a programming language..." }] },
    { "role": "user", "parts": [{ "text": "Show me a Hello World example" }] }
  ]
}
```

---

## 1.3 Vertex AI requests

Send requests to `/v1/projects/{placeholder}/locations/{region}/...`.
The orchestrator replaces `{placeholder}` with the real project ID from the
rotated service account and injects the Bearer token.

### Text generation (Gemini via Vertex)

```http
POST /v1/projects/ANY/locations/us-central1/publishers/google/models/gemini-2.0-flash:generateContent
Content-Type: application/json

{
  "contents": [
    { "role": "user", "parts": [{ "text": "Hello" }] }
  ]
}
```

> `ANY` is a placeholder — it gets replaced with the actual project ID.

### Image generation (Imagen)

```http
POST /v1/projects/ANY/locations/us-central1/publishers/google/models/imagen-3.0-generate-001:predict
Content-Type: application/json

{
  "instances": [
    { "prompt": "A cat in space, digital art" }
  ],
  "parameters": {
    "sampleCount": 1,
    "aspectRatio": "16:9"
  }
}
```

**Response:** `{ "predictions": [{ "bytesBase64Encoded": "...", "mimeType": "image/png" }] }`

### Video generation (Veo)

```http
POST /v1/projects/ANY/locations/us-central1/publishers/google/models/veo-3.0-fast-generate-001:predictLongRunning
Content-Type: application/json

{
  "instances": [
    { "prompt": "A cat jumping in slow motion" }
  ],
  "parameters": {}
}
```

**Response:** Long-running operation object — poll the returned operation name for result.

### Streaming (Vertex)

```http
POST /v1/projects/ANY/locations/us-central1/publishers/google/models/gemini-2.0-flash:streamGenerateContent
Content-Type: application/json

{
  "contents": [
    { "role": "user", "parts": [{ "text": "Write a poem" }] }
  ]
}
```

---

## 1.4 Retry & failover behavior

| Parameter | Value |
|---|---|
| Max retries | `SERVICES__MAX_RETRIES` (default: **10**) |
| Retried HTTP codes | 429 (rate limit), 403 (key blocked), 503 (service unavailable) |
| Retry strategy | Rotate to the next key/credential and retry immediately |
| Request timeout | 120 seconds per upstream attempt |
| Delay between error retries | 500ms (on unexpected exceptions) |

When a retry-eligible error occurs, the orchestrator switches to the next API key
(Gemini) or service account (Vertex) in the rotation pool and retries.

### All retries exhausted

```
HTTP 503
Content-Type: text/plain

All backends exhausted or unavailable
```

### No keys available

```
HTTP 503
Content-Type: text/plain

No Gemini keys available
```

```
HTTP 503
Content-Type: text/plain

No Vertex credentials available
```

---

## 1.5 Health check

```http
GET /health
```

No authentication required. Use this for load balancer / Docker health checks.

**Response (200):**

```json
{
  "status": "healthy",
  "database": "connected",
  "gemini_keys": 3,
  "vertex_credentials": 2
}
```

| `status` value | Meaning |
|---|---|
| `healthy` | DB connected AND at least 1 key/credential loaded |
| `degraded` | DB connected but 0 keys/credentials loaded |
| `unhealthy` | DB unreachable |

---

## 1.6 Headers forwarded to upstream

The orchestrator uses an **allowlist** — only these client headers are forwarded:

- `content-type`
- `accept`
- `accept-encoding`
- `accept-language`
- `user-agent`
- `x-goog-user-project`

All other headers (cookies, authorization, hop-by-hop) are stripped.
The orchestrator adds its own `Authorization` header for Vertex requests.

---

## 1.7 IP access control

Access is controlled by `SECURITY__ALLOWED_CLIENT_IPS`:

- `["*"]` — all IPs allowed (default)
- `["10.0.0.5", "192.168.1.0/24"]` — only listed IPs

If behind a reverse proxy (nginx, Cloudflare), set `SECURITY__TRUST_PROXY_HEADERS=true`
so the orchestrator reads the real client IP from `X-Forwarded-For` / `X-Real-IP`.

---

## 1.8 Error format

Proxy errors use plain text body with the appropriate HTTP status code.
Upstream errors are forwarded as-is (same status code, same JSON body from Google).

---
---

# Part 2: Admin API (Frontend Integration)

All admin endpoints are under the `/admin` prefix.
Authentication is via JWT in an `httpOnly` cookie (`access_token`).

---

## 2.1 Authentication flow

```
1. POST /admin/login        → sets httpOnly cookie
2. All other /admin/* calls  → cookie sent automatically by browser
3. POST /admin/logout        → deletes cookie
```

Alternatively, pass `Authorization: Bearer <token>` header for programmatic access
(e.g., from a script or mobile app).

**Token lifetime:** 30 minutes (configurable via `TOKEN_EXPIRE_MINUTES` env var).

**IP binding:** The JWT contains the client IP. If a request comes from a different
IP than the one used during login, it will be rejected with 401.

---

## 2.2 Endpoints

### POST `/admin/login`

Authenticate and receive a JWT cookie.

**Request:**
```json
{
  "username": "admin",
  "password": "your-password"
}
```

**Success (200):**
```json
{
  "status": "ok",
  "username": "admin"
}
```

Sets `access_token` cookie (`httpOnly`, `SameSite=Lax`, 30 min TTL).
If `SECURITY__COOKIE_SECURE=true`, the cookie has the `Secure` flag.

**Errors:**

| Code | Body | Meaning |
|------|------|---------|
| 401 | `{"detail": "Invalid credentials"}` | Wrong username or password |
| 423 | `{"detail": "Account temporarily locked due to failed attempts"}` | 5 failed attempts → 15 min lockout |
| 500 | `{"detail": "Authentication failed"}` | `SECURITY__ADMIN_PASSWORD_HASH` not configured |

---

### POST `/admin/logout`

Delete the auth cookie. No request body needed.

**Response (200):**
```json
{
  "status": "ok"
}
```

---

### GET `/admin/status`

**Auth required.** Current system status.

**Response (200):**
```json
{
  "status": "operational",
  "vertex_credentials": 2,
  "gemini_keys": 3,
  "admin_user": "admin"
}
```

---

### POST `/admin/reload`

**Auth required.** Hot-reload API keys and service account credentials from disk.
No restart needed.

**Response (200):**
```json
{
  "status": "reloaded",
  "vertex_count": 2,
  "gemini_count": 3
}
```

---

### GET `/admin/providers`

**Auth required.** List all configured keys/credentials with masked identifiers.

**Response (200):**
```json
{
  "gemini": [
    { "index": 0, "mask": "...aB1c" },
    { "index": 1, "mask": "...xY2z" }
  ],
  "vertex": [
    { "project_id": "my-project-123" },
    { "project_id": "my-project-456" }
  ]
}
```

Use `index` (for Gemini) or `project_id` (for Vertex) as `identifier` in `/test-provider`.

---

### POST `/admin/test-provider`

**Auth required.** Test a single key/credential against one model.

**Gemini example:**
```json
{
  "provider": "gemini",
  "identifier": 0,
  "model": {
    "name": "models/gemini-2.0-flash",
    "supportedGenerationMethods": ["generateContent"]
  }
}
```

**Vertex example:**
```json
{
  "provider": "vertex",
  "identifier": "my-project-123",
  "model": {
    "name": "models/gemini-2.0-flash",
    "supportedGenerationMethods": ["generateContent"]
  }
}
```

**Supported `supportedGenerationMethods`:**
- `"generateContent"` — text/chat models (Gemini)
- `"predict"` — image models (Imagen)
- `"predictLongRunning"` — video models (Veo)

**Response (200):**
```json
{
  "model": "models/gemini-2.0-flash",
  "status": "working",
  "code": 200,
  "error": null
}
```

| `status` | Meaning |
|---|---|
| `working` | Model responded with 200 |
| `error` | Non-200 response or exception; see `code` and `error` fields |
| `skipped` | None of the `supportedGenerationMethods` are testable |

---

### POST `/admin/check-keys`

**Auth required.** Test ALL keys/credentials against a list of models.
Runs concurrently (max 10 parallel, 10s timeout per test).

**Request:**
```json
{
  "models": [
    {
      "name": "models/gemini-2.0-flash",
      "supportedGenerationMethods": ["generateContent"]
    },
    {
      "name": "models/imagen-3.0-generate-001",
      "supportedGenerationMethods": ["predict"]
    }
  ]
}
```

**Response (200):**
```json
{
  "gemini": {
    "...aB1c": [
      { "model": "models/gemini-2.0-flash", "status": "working", "code": 200, "error": null },
      { "model": "models/imagen-3.0-generate-001", "status": "error", "code": 404, "error": {...} }
    ],
    "...xY2z": [...]
  },
  "vertex": {
    "my-project-123": [
      { "model": "models/gemini-2.0-flash", "status": "working", "code": 200, "error": null }
    ]
  }
}
```

---

### GET `/admin/stats`

**Auth required.** Aggregated statistics for a time period.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `hours` | int (>=1) | 24 | Time period to aggregate |
| `provider` | string | — | Filter: `"gemini"` or `"vertex"` |

**Response (200):**
```json
{
  "uptime_seconds": 86421.5,
  "period_hours": 24,
  "total_requests": 1520,
  "total_errors": 12,
  "error_rate": 0.79,
  "avg_latency_ms": 342.15,
  "total_prompt_tokens": 150000,
  "total_candidates_tokens": 320000,
  "total_tokens": 470000
}
```

---

### GET `/admin/stats/requests`

**Auth required.** Paginated log of individual requests.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int (1–500) | 50 | Page size |
| `offset` | int (>=0) | 0 | Skip N records |
| `model` | string | — | Filter by model name (e.g. `"gemini-2.0-flash"`) |
| `provider` | string | — | Filter: `"gemini"` or `"vertex"` |
| `errors_only` | bool | false | Only show failed requests |

**Response (200):**
```json
{
  "total": 1520,
  "limit": 50,
  "offset": 0,
  "requests": [
    {
      "id": 1520,
      "provider": "gemini",
      "api_key": "...aB1c",
      "model": "gemini-2.0-flash",
      "action": "generateContent",
      "http_method": "POST",
      "url_path": "v1beta/models/gemini-2.0-flash:generateContent",
      "client_ip": "10.0.0.5",
      "status_code": 200,
      "latency_ms": 450,
      "attempt_count": 1,
      "prompt_tokens": 100,
      "candidates_tokens": 250,
      "total_tokens": 350,
      "is_error": false,
      "error_detail": null,
      "request_size": 512,
      "response_size": 2048,
      "created_at": "2026-02-19T12:00:00+00:00"
    }
  ]
}
```

---

### GET `/admin/stats/models`

**Auth required.** Per-model breakdown.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `hours` | int (>=1) | 24 | Time period |

**Response (200):**
```json
{
  "period_hours": 24,
  "models": [
    {
      "name": "gemini-2.0-flash",
      "provider": "gemini",
      "total_requests": 800,
      "total_errors": 5,
      "avg_latency_ms": 310.25,
      "total_tokens": 250000
    }
  ]
}
```

---

### GET `/admin/stats/tokens`

**Auth required.** Token usage grouped by time period, model, or key.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `hours` | int (>=1) | 24 | Time period |
| `group_by` | string | `"hour"` | One of: `"hour"`, `"day"`, `"model"`, `"key"` |

**Response (200):**
```json
{
  "period_hours": 24,
  "group_by": "hour",
  "data": [
    {
      "group": "2026-02-19 12:00:00+00:00",
      "prompt_tokens": 5000,
      "candidates_tokens": 12000,
      "total_tokens": 17000,
      "request_count": 45
    }
  ]
}
```

`group` value depends on `group_by`:
- `hour` / `day` → ISO datetime string
- `model` → model name (e.g. `"gemini-2.0-flash"`)
- `key` → masked key ID (e.g. `"...aB1c"`) or project ID

---

### DELETE `/admin/stats/cleanup`

**Auth required.** Delete request records older than N days.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `days` | int (>=1) | 30 | Delete records older than this |

**Response (200):**
```json
{
  "deleted": 1200,
  "older_than_days": 30
}
```

---

## 2.3 Authentication errors

All protected endpoints return these errors when auth fails:

| Code | Body | Meaning |
|------|------|---------|
| 401 | `{"detail": "Authentication required"}` | No token / cookie provided |
| 401 | `{"detail": "Token expired"}` | JWT expired (>30 min) |
| 401 | `{"detail": "Invalid token"}` | Malformed or tampered JWT |
| 401 | `{"detail": "Token validation failed"}` | IP mismatch (token issued for different IP) |
| 403 | `{"detail": "Admin access required"}` | Token is valid but role is not `admin` |
| 503 | `{"detail": "Stats service not initialized"}` | Server starting up, not ready yet |

---

## 2.4 CORS configuration

CORS is configured via `SECURITY__CORS_ORIGINS` in `.env`.
Credentials (cookies) are allowed (`allow_credentials=true`).

Example for a frontend at `https://admin.example.com`:
```
SECURITY__CORS_ORIGINS=["https://admin.example.com"]
```

For development:
```
SECURITY__CORS_ORIGINS=["*"]
```

---
---

# Part 3: Configuration Reference

All settings are configured via environment variables or `.env` file.
Nested settings use `__` delimiter (e.g., `SECURITY__ADMIN_USERNAME`).

## General

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level |
| `ENABLE_DOCS` | `false` | Enable Swagger UI at `/docs` |

## Database

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICES__DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `SERVICES__STATS_RETENTION_DAYS` | `30` | Default cleanup age in days |
| `SERVICES__STORE_REQUEST_BODIES` | `false` | Store request/response JSON in DB |

## Services

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICES__GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com` | Gemini API base URL |
| `SERVICES__VERTEX_BASE_URL` | `https://us-central1-aiplatform.googleapis.com` | Vertex AI base URL |
| `SERVICES__MAX_RETRIES` | `10` | Max retry attempts on 429/403/503 |

## Security

| Variable | Default | Description |
|----------|---------|-------------|
| `SECURITY__ADMIN_SECRET` | — | Secret for internal operations (min 16 chars) |
| `SECURITY__ADMIN_USERNAME` | `admin` | Admin login username |
| `SECURITY__ADMIN_PASSWORD_HASH` | — | PBKDF2-SHA256 hash (see below) |
| `SECURITY__ALLOWED_CLIENT_IPS` | `["*"]` | JSON list of allowed IPs for proxy |
| `SECURITY__CORS_ORIGINS` | `["*"]` | JSON list of allowed CORS origins |
| `SECURITY__TRUST_PROXY_HEADERS` | `false` | Read IP from X-Forwarded-For |
| `SECURITY__COOKIE_SECURE` | `false` | Set Secure flag on auth cookie |

## Auth / JWT

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET_FILE` | `/app/secrets/jwt_secret.key` | Path to JWT signing key (auto-created) |
| `TOKEN_EXPIRE_MINUTES` | `30` | JWT token lifetime |
| `MAX_LOGIN_ATTEMPTS` | `5` | Failed attempts before lockout |
| `LOCKOUT_DURATION_MINUTES` | `15` | Lockout duration |

## Paths

| Variable | Default | Description |
|----------|---------|-------------|
| `PATHS__CREDS_ROOT` | `./credentials` | Root directory for credentials |

## Encryption

| Variable | Default | Description |
|----------|---------|-------------|
| `ENCRYPTION_KEY_FILE` | `/app/secrets/master.key` | Path to Fernet encryption key (auto-created) |

### Generate admin password hash

```bash
python -c "from app.security.auth import AuthManager; print(AuthManager().hash_password('your-password'))"
```

Copy the output into `SECURITY__ADMIN_PASSWORD_HASH`.

---

# Part 4: Credential Setup

## Gemini API keys

Place a JSON file at `credentials/gemini/api_keys.json`:

```json
["AIzaSyA...", "AIzaSyB...", "AIzaSyC..."]
```

Or in encrypted format (after running `python scripts/encrypt_keys.py`):

```json
{
  "encrypted": true,
  "keys": ["gAAAAABk...", "gAAAAABk...", "gAAAAABk..."]
}
```

## Vertex AI service accounts

Place Google Cloud service account JSON files in `credentials/vertex/`:

```
credentials/
  vertex/
    project-a-sa.json
    project-b-sa.json
  gemini/
    api_keys.json
```

Each `.json` file must have `"type": "service_account"`.
The orchestrator extracts the `project_id` and credentials automatically.

---

# Part 5: Docker

## Development (with hot reload)

```bash
docker compose up
```

This uses `docker-compose.yaml` + `docker-compose.override.yml` (auto-loaded).
Override mounts the project directory for hot reload and exposes PostgreSQL port 5432.

## Production

```bash
docker compose -f docker-compose.yaml up -d
```

This uses only the base config:
- Credentials and secrets mounted as read-only volumes
- PostgreSQL port not exposed externally
- No source code mounted
