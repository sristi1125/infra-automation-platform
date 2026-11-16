# Infrastructure Automation Platform

A full-stack platform for automating firmware upgrades, power control, and
resets across a fleet of network devices (switches, PDUs), built like a
real distributed system: a stateless orchestrator API, a Redis-backed job
queue, independently scalable workers, and a React dashboard.

It's hardware-free by design. A simulator (`simulator/fake_server.py`)
stands in for real devices, including slow multi-stage firmware upgrades
and injectable failures, so everything can be developed and tested
locally. Swapping in a real device driver means writing a new
`DeviceClient` implementation; the orchestrator doesn't change.

## Architecture

```
  Dashboard (React) ──▶ Orchestrator API (Flask, stateless) ──▶ Redis queue (RQ)
       :5173                  :5000                                  │
                                │                                    ▼
                                │                               Worker(s)
                                ▼                                    │
                     Postgres: jobs, audit log                      ▼
                     Redis: queue, sessions,                  DeviceClient
                            status cache,                  (retries, rate limit,
                            rate-limit buckets              circuit breaker)
                                                                    │
                                                                    ▼
                                                     Simulator :5001 → real devices later
```

| Component | Path | What it does |
|---|---|---|
| Orchestrator API | `orchestrator/app.py` | Validates requests, records jobs and audit entries, enqueues long-running work. Never blocks on a firmware upgrade. |
| Worker | `orchestrator/worker.py`, `tasks.py` | Pulls jobs off the queue and tracks the upgrade on the device until it finishes. Run as many as you like. |
| Device client | `orchestrator/device_client.py` | The only code that talks to devices. Handles retries, per-device rate limiting (`rate_limiter.py`), circuit breaking (`circuit_breaker.py`), and 5s status caching (`cache.py`). |
| Jobs | `orchestrator/jobs.py` | Job records in Postgres (`pending → running → succeeded / failed`). |
| Auth | `orchestrator/auth.py` | API keys and session tokens, with `viewer` (read-only) and `operator` roles. |
| Audit log | `orchestrator/audit.py` | Who did what, to which device, with what result. |
| Dashboard | `dashboard/` | React + Vite: fleet overview, device detail, audit log, login. |
| Simulator | `simulator/fake_server.py` | Fake switches and PDUs with realistic upgrade timing and chaos injection. |

### How job safety works

- **One active job per device.** A partial unique index in Postgres
  (`jobs_one_active_per_device`) allows only one `pending`/`running` job
  per device. The API claims the device by inserting the job *before*
  touching it, so even simultaneous requests across multiple API instances
  can't both start an upgrade. The loser gets `409`.
- **Abandoned jobs don't block devices.** If a worker crashes mid-job, or
  a job never reaches a worker, it's marked `failed` with the reason once
  it's been `running` longer than `STALE_RUNNING_SECONDS` (default 120) or
  `pending` longer than `STALE_PENDING_SECONDS` (default 600). This happens
  before every new-job check and whenever a worker starts.
- **No orphaned jobs.** If the device rejects the command, the claim is
  released. If the queue is unreachable, the job is marked `failed` and
  the API returns `503`.

## Running locally

### Prerequisites
- Python 3.11+
- Node.js 20+ (dashboard only)
- Docker Desktop (for Postgres + Redis)

### 1. Start Postgres and Redis

```bash
docker compose up -d
```

### 2. Install Python dependencies

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r orchestrator/requirements.txt
```

### 3. Start the services (one terminal each)

```bash
cd simulator && python fake_server.py      # devices on :5001
cd orchestrator && python app.py           # API on :5000
cd orchestrator && python worker.py        # start a second one to see jobs spread out
cd dashboard && npm install && npm run dev # dashboard on :5173
```

On Windows, `start-all.ps1` opens the backend services in separate windows
(edit `$root` at the top to point at your checkout first).

### 4. Try it

Log in to the dashboard at http://localhost:5173 with `operator` /
`operator123` (can act) or `viewer` / `viewer123` (read-only).

Or call the API directly with a dev API key:

```bash
curl -H "X-API-Key: dev-operator-key" http://localhost:5000/devices/summary
curl -X POST -H "X-API-Key: dev-operator-key" -H "Content-Type: application/json" -d "{\"target_version\": \"16.11.0001\"}" http://localhost:5000/devices/switch-1/firmware
curl -H "X-API-Key: dev-operator-key" http://localhost:5000/jobs/<job_id>
```

Make devices flaky to watch retries and the circuit breaker kick in:

```bash
curl -X POST -H "Content-Type: application/json" -d "{\"fail_rate\": 0.3}" http://localhost:5001/chaos
```

These are development credentials. Override them with `OPERATOR_API_KEY`,
`VIEWER_API_KEY`, `OPERATOR_PASSWORD`, and `VIEWER_PASSWORD`.

## API

All endpoints except `/health` and `/login` need an `X-API-Key` header or
an `X-Session-Token` header holding a token from `/login`.

| Method | Endpoint | Role | Description |
|---|---|---|---|
| GET | `/health` | none | Liveness check |
| POST | `/login` | none | Exchange username/password for a session token |
| GET | `/devices` | viewer | List devices |
| GET | `/devices/summary` | viewer | Every device's status plus its latest job |
| GET | `/devices/<id>/status` | viewer | One device's status (cached 5s) |
| POST | `/devices/<id>/power` | operator | `{"power": "on" \| "off"}` |
| POST | `/devices/batch/power` | operator | `{"device_ids": [...], "power": ...}`, reports per-device results |
| POST | `/devices/<id>/reset` | operator | Reset a device |
| POST | `/devices/<id>/firmware` | operator | `{"target_version": ...}`, returns `202` with a job |
| GET | `/jobs/<job_id>` | viewer | Job status |
| GET | `/audit-log` | viewer | Audit trail, filter with `?device_id=` |

## Tests

Postgres and Redis must be running (`docker compose up -d`).

```bash
pytest tests/ -v
```

Tests never touch your dev data. They use a separate database,
`infra_automation_test` (created automatically), and Redis DB 15, both
wiped before each test. The orchestrator tests run against the real
simulator over HTTP, not mocks.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_HOST` / `POSTGRES_PORT` | `localhost` / `5432` | Postgres connection |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `infra_automation` / `infra` / `infra_dev_password` | Matches `docker-compose.yml` |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` | `localhost` / `6379` / `0` | Redis connection |
| `SIMULATOR_URL` | `http://localhost:5001` | Where the device client sends requests |
| `STALE_RUNNING_SECONDS` | `120` | When a `running` job counts as abandoned |
| `STALE_PENDING_SECONDS` | `600` | When a `pending` job counts as abandoned |

## Roadmap

See `roadmap.md` for the phased plan and the system-design questions this
project is built to answer.
