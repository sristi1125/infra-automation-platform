# Infrastructure Automation Platform

A full-stack platform to automate firmware upgrades, resets, and lifecycle
management for switches, PDUs, and servers — built with a stateless
orchestrator API, a Redis-backed job queue, worker processes, and an
Electron dashboard.

This repo is built device-agnostic and hardware-free by design: a
simulator (`simulator/fake_server.py`) stands in for real devices during
development, using the same request patterns a real device driver would.

## Phase 0 (current): Local dev environment + simulator

### Prerequisites
- Docker Desktop (for Postgres + Redis, used starting Phase 1)
- Python 3.11+

### Setup

```bash
# from the project root
cd simulator
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### Run the simulator

```bash
python fake_server.py
```

Runs on http://localhost:5001. Try it:

```bash
curl http://localhost:5001/devices
curl http://localhost:5001/devices/switch-1/status
curl -X POST http://localhost:5001/devices/switch-1/power -H "Content-Type: application/json" -d "{\"power\": \"off\"}"
curl -X POST http://localhost:5001/devices/switch-1/firmware -H "Content-Type: application/json" -d "{\"target_version\": \"16.11.0001\"}"
```

Tune failure injection at runtime:
```bash
curl -X POST http://localhost:5001/chaos -H "Content-Type: application/json" -d "{\"fail_rate\": 0.3}"
```

### Run tests

```bash
# from the project root
pip install -r simulator/requirements.txt
pytest tests/ -v
```

### Start Postgres + Redis (used from Phase 1 onward)

```bash
docker-compose up -d
```

## Roadmap

See `roadmap.md` for the full phased build-out (orchestrator, job queue,
workers, caching, auth, dashboard).
