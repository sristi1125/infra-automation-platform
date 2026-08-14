# Infrastructure Automation Platform — Project Roadmap

**Pace:** 1–2 hrs/day
**Target:** Portfolio-grade / "FAANG-worthy" — real distributed-systems + system-design thinking, built in from day one (not retrofitted)

---

## Architecture (decided up front — this is what we build toward from Phase 1)

```
                     ┌─────────────┐
   Dashboard  ──────▶│ Orchestrator │──────▶  enqueue job
   (Electron)         │   API (stateless)     │
                     └─────────────┘             │
                                                  ▼
                                          ┌───────────────┐
                                          │  Job Queue     │  (Redis / RQ or Celery+Redis)
                                          └───────────────┘
                                                  │
                                pulled by          ▼
                                          ┌───────────────┐
                                          │   Worker(s)    │  (can run N of these)
                                          └───────────────┘
                                                  │
                                per-device lock     ▼
                                          ┌───────────────┐
                                          │ Device Client  │  (abstraction layer)
                                          │  (async I/O)   │
                                          └───────────────┘
                                                  │
                                                  ▼
                              fake_server.py (sim) ──▶ real devices later

        Postgres: jobs, devices, audit log, users
        Redis: job queue + per-device locks + status cache
```

**Why this shape, from the start:**
- **Orchestrator API is stateless** → can run multiple instances behind a load balancer immediately, not "later"
- **Queue decouples "accept request" from "do the work"** → this is the core scalability lever, and retrofitting it after building synchronous endpoints is genuinely painful. Building it first avoids a rewrite.
- **Workers scale independently of the API** → you can demo this literally by running 2 worker processes locally
- **Per-device Redis lock** → prevents two workers from touching the same device at once — the concurrency-safety story
- **Async device I/O** → device calls are network-bound, async lets one worker handle many in flight

We're front-loading Postgres + Redis instead of "SQLite for now, migrate later" — it's a bit more setup cost in week 1, but it means every phase after this is built on the real architecture, so nothing needs to be redone.

---

## Guiding Principle

The thing that makes this project impressive isn't the UI — it's whether the **orchestration engine** behaves like a real distributed system: stateless API, async job execution via queue/workers, safe concurrency, retries, failure isolation, and an audit trail. Build that core deeply. The dashboard is the last phase.

---

## Phase 0 — Foundations + Real Infra From Day One (Week 1–2)
**Goal:** Environment set up with the *actual* architecture pieces running locally — not stubs you'll swap later.

- [ ] Repo, virtualenv, `.gitignore`, README skeleton
- [ ] Docker Compose for local dev: Postgres + Redis running alongside your app from the start
- [ ] Harden `fake_server.py`:
  - [ ] Input validation on all endpoints
  - [ ] Turn off `debug=True` for a "prod-like" run mode
  - [ ] Second device type (PDU vs switch) with different fields/behavior
  - [ ] Firmware upgrade takes *simulated time* (`idle → updating → verifying → done`), not instant
  - [ ] Failure injection (`?fail_rate=0.2` or `/chaos` endpoint) — devices can randomly time out or reject commands
- [ ] Tests for the simulator's behavior, including bad input and injected failures

**Milestone:** `docker-compose up` gives you Postgres + Redis + simulator(s) running together. This is your permanent dev environment for the rest of the project.

---

## Phase 1 — Orchestrator API + Device Abstraction (Weeks 3–4)
**Goal:** Stateless API layer, built async, built against Postgres — not a prototype you'll rewrite.

- [ ] Choose FastAPI (async-native, fits this architecture far better than sync Flask for the orchestrator)
- [ ] **Device abstraction layer**: `DeviceClient` interface (`get_status()`, `set_power()`, `reset()`, `upgrade_firmware()`) — implemented for the simulator now, swappable for a real Aruba/iLO driver later without touching orchestrator logic
- [ ] Device registry in **Postgres** (not SQLite) — devices table with type, address, capabilities
- [ ] Orchestrator API endpoints are **stateless**: they validate the request, write to Postgres/enqueue to Redis, return immediately — they never block on a device call
- [ ] Integration tests: orchestrator + simulator running together via docker-compose, hit the API, assert correct proxying

**Milestone:** A stateless orchestrator API, backed by Postgres, that never talks to a device directly — it only ever enqueues work.

---

## Phase 2 — Job Queue + Workers (Weeks 5–7)
**Goal:** This phase *is* the system design story. Get it right.

- [ ] Job model in Postgres: `id, device_id, action, status, created_at, updated_at, result, error, attempt_count`
- [ ] States: `pending → running → succeeded / failed → retrying`
- [ ] Redis-backed queue (RQ, or Celery+Redis — RQ is simpler to reason about and explain in an interview if you're newer to this)
- [ ] **Worker process** (separate from the API process): pulls jobs off the queue, executes against the device via the abstraction layer, updates job status in Postgres
- [ ] Run **2+ worker processes locally** and prove jobs get distributed across them
- [ ] **Per-device Redis lock**: worker acquires a lock on `device_id` before executing, releases after — prevents two workers from racing on the same device
- [ ] Idempotency: duplicate job submission for a device already mid-job is rejected/deduped
- [ ] Tests: concurrent jobs on the same device serialize correctly; concurrent jobs on different devices run in parallel

**Milestone:** You can submit 10 jobs across 3 devices, watch multiple workers pick them up concurrently, and prove no two jobs ever touch the same device simultaneously. This is your best interview demo.

---

## Phase 3 — Resilience: Retries, Timeouts, Failure Isolation (Weeks 8–9)
**Goal:** Prove the system degrades gracefully instead of falling over.

- [ ] Retry with exponential backoff on transient device failures (use your simulator's chaos injection to trigger this in tests)
- [ ] Timeouts on device calls — a hung device can't hang a worker indefinitely
- [ ] Batch operations (e.g., "upgrade firmware on 10 devices") report **per-device** success/failure — no all-or-nothing
- [ ] Circuit breaker: after N consecutive failures on a device, stop retrying for a cooldown window
- [ ] Tests: flaky/slow simulated devices, assert workers recover and the system stays healthy

**Milestone:** Kill a worker mid-job, restart it — the job resumes/retries correctly instead of getting stuck or duplicated.

---

## Phase 4 — Caching, Rate Limiting, Observability (Weeks 10–11)
**Goal:** The pieces that make this "scalable" in a way you can talk about concretely.

- [ ] Redis cache for device status (short TTL) — dashboard reads hit cache, not live device calls, on every poll
- [ ] Rate limiting per device (e.g., token bucket in Redis) — protects both your devices and your system from overload during large batch operations
- [ ] Structured logging (JSON logs) across API and workers
- [ ] Basic metrics endpoint (job success/failure rate, queue depth, per-device latency) — Prometheus-style if you want the extra signal
- [ ] Tests + a short load test (even a simple script hammering the API with concurrent batch jobs) to show the system holds up

**Milestone:** You can point at real numbers — queue depth, latency, cache hit rate — not just say "it's scalable."

---

## Phase 5 — Audit Log & Access Control (Week 12)
**Goal:** The "IAM-like interface" piece — who did what, and who's allowed to.

- [ ] Audit log table in Postgres: every action recorded (who, what, when, target device, result)
- [ ] Token-based auth (JWT is fine) on the API
- [ ] Basic roles: `viewer` (read-only) vs `operator` (can trigger actions)
- [ ] Audit trail endpoint

**Milestone:** Every action is attributable and access is gated.

---

## Phase 6 — Dashboard (Electron UI) (Weeks 13–15)
**Goal:** Make it demoable.

- [ ] Device list: health, firmware version, power state (reading from cache, not live device calls)
- [ ] Device detail: job history for that device
- [ ] Trigger actions from UI → hits orchestrator API → enqueues job → UI polls/streams job status
- [ ] Audit log view
- [ ] Login matching backend auth
- [ ] Visual polish — intentional, not default component styling

**Milestone:** A working demo you could screen-record and show in an interview.

---

## Phase 7 — Polish, Docs, Portfolio-Readiness (Week 16)
**Goal:** Make the system-design story easy for someone else to follow fast.

- [ ] Architecture diagram (the one at the top of this doc, refined with what you actually built)
- [ ] README: what it does, why it exists, how to run it locally (docker-compose up), key design decisions
- [ ] A short **design doc**: why stateless API + queue, why per-device locking, why Redis cache, why circuit breaker, how you'd shard/scale further (e.g., consistent hashing across workers, read replicas for Postgres at higher scale)
- [ ] Demo video/gif — ideally showing the multi-worker concurrent job demo from Phase 2
- [ ] Full test suite green end-to-end
- [ ] Tag v1.0

**Milestone:** A project you can walk an interviewer through for 20 minutes, covering real distributed-systems tradeoffs you actually implemented.

---

## What You Should Be Able to Answer By the End

- "Why is your orchestrator API stateless, and what does that buy you?"
- "Walk me through what happens when a device call fails mid-job."
- "How do you prevent two workers from operating on the same device at once?"
- "How would you scale this to 10,000 devices?" (queue partitioning, more workers, Postgres read replicas, consistent hashing for device sharding, cache tuning)
- "How would you swap the simulator for a real Aruba API without touching the orchestrator?"
- "What's your retry and circuit-breaker strategy, and why?"

---

## Timeline Summary

| Phase | Weeks | Focus |
|---|---|---|
| 0 | 1–2 | Docker Compose (Postgres+Redis) + simulator hardening |
| 1 | 3–4 | Stateless orchestrator API + device abstraction |
| 2 | 5–7 | Job queue + workers + per-device locking |
| 3 | 8–9 | Retries, timeouts, circuit breaker, failure isolation |
| 4 | 10–11 | Caching, rate limiting, observability |
| 5 | 12 | Audit log + auth |
| 6 | 13–15 | Dashboard (Electron) |
| 7 | 16 | Polish + docs |

**Total: ~16 weeks at 1–2 hrs/day**, with buffer for life happening. The extra weeks versus the earlier plan go entirely into building the queue/worker/caching architecture properly from the start instead of retrofitting it — that's the tradeoff for having the system design story be true from day one.
