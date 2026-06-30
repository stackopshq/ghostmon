# GhostMonitor

Self-hosted infrastructure monitoring — a free alternative to Zabbix.

> **Project status:** GhostMonitor is on its way there. Today it is a capable
> agentless **uptime monitor**; the model is being grown toward full
> Zabbix-style monitoring (hosts, metric items, history, triggers, templates,
> agent/SNMP collection). See the [roadmap](docs/roadmap.md) and
> [ADR 0001](docs/adr/0001-target-architecture-zabbix-alternative.md) for the
> target architecture.

Today, GhostMonitor probes your endpoints on a schedule (HTTP, TCP, SSL
certificate expiry, ICMP ping), records latency/availability history, and
notifies you over email or webhooks when a monitor flips **UP ↔ DOWN**. It
exposes both a JSON API and a server-rendered web UI, plus Prometheus metrics.

## Screenshots

**Zero-knowledge private items** — values are encrypted client-side; the server only
ever holds ciphertext, and the browser decrypts them with either a key kept in the
URL fragment (`#k=…`) or a **passphrase** (key derived in-browser via Argon2id),
neither of which ever reaches the server:

![Zero-knowledge private item decrypted in-browser](docs/assets/zk-private-item.png)

**Host detail** — items (metrics) with min/max and server-rendered history sparklines:

| Dark | Light |
| --- | --- |
| ![Host detail with metric sparklines, dark theme](docs/assets/host-detail-dark.png) | ![Host detail with metric sparklines, light theme](docs/assets/host-detail-light.png) |

**Item detail** — threshold triggers on a metric item (alerting through the host's
channels) with severity/state pills, plus recent values:

![Item detail with triggers](docs/assets/item-detail-triggers.png)

**Monitor detail** — settings, notification channels, and threshold triggers with severities:

| Dark | Light |
| --- | --- |
| ![Monitor detail with triggers, dark theme](docs/assets/monitor-detail-dark.png) | ![Monitor detail with triggers, light theme](docs/assets/monitor-detail-light.png) |

**Sign-in:**

| Dark | Light |
| --- | --- |
| ![GhostMonitor sign-in, dark theme](docs/assets/login-dark.png) | ![GhostMonitor sign-in, light theme](docs/assets/login-light.png) |

## What (today)

- **Monitor types**: HTTP(S), TCP connect, SSL/TLS certificate expiry, ICMP ping,
  and SNMP reachability (SNMPv2c GET).
- **Scheduling**: per-monitor interval with configurable retries and retry interval.
  A reconciling scheduler keeps live probe jobs in sync with the database.
- **Triggers & severities**: threshold rules on collected metrics (e.g. latency)
  with `info`→`disaster` severities and a problem/OK state machine.
- **Hosts, items & history**: collect arbitrary metrics as items with append-only
  time-series history (bounded by retention), browsable with inline sparklines;
  each monitor's latency is mirrored into this model automatically. Hourly **trend
  rollups** (min/avg/max) downsample numeric history so long-range data survives
  raw-sample retention.
- **Agent ingestion**: per-owner ingest tokens and a token-authenticated
  `POST /api/ingest` (auto-creating "trapper" items) so external agents and scripts
  push metrics without a user login.
- **Server-side polling**: items can have a `source` (trapper / SNMP) and config;
  the scheduler polls due SNMP items (any OID) from the host's `address` into history.
- **Maintenance windows**: one-shot (`once`) or recurring (`cron`) silencing of alerts.
- **Notifications**: email (SMTP) and webhooks, attached per-monitor; fire-and-forget
  so a slow SMTP server never stalls probing, and **severity-routed** (each channel
  has a minimum severity). Alerting stays fully self-hosted — no third-party calls.
- **Auth**: local accounts (argon2 password hashing, JWT) and optional OIDC.
- **Interfaces**: REST API (`/api`, OpenAPI at `/docs`), web UI, a `ghostmon` CLI,
  and a dependency-free metric agent (`ghostmon agent run`).
- **Observability**: Prometheus metrics at `/metrics`, liveness at `/healthz`,
  readiness at `/readyz`.
- **Privacy-first** (the differentiator vs Zabbix): monitoring secrets — webhook
  signing secrets and SNMP communities — are **encrypted at rest** (Fernet/AES, key
  derived from `APP_SECRET_KEY`) and **never returned in clear**, so a database dump
  leaks nothing usable. **Zero-knowledge private items** go further: their values are
  end-to-end encrypted client-side (AES-256-GCM, key from a URL fragment or an
  Argon2id passphrase) and the server only ever sees ciphertext. Fully self-hosted,
  no telemetry, no third-party calls, minimal alert payloads, hashed ingest tokens,
  bounded retention.

Stack: Python 3.12, FastAPI, SQLAlchemy 2 (async) + asyncpg, PostgreSQL, APScheduler,
Typer, Jinja2. Dependencies are managed with [`uv`](https://docs.astral.sh/uv/).

## Run

Prerequisites: `uv`, and a PostgreSQL instance. The repo ships a compose file
(use **Podman**: `podman compose`) bringing up Postgres, the API, and Prometheus.

```bash
cp .env.example .env            # then edit APP_SECRET_KEY (>=16 chars) and DB/SMTP/OIDC
uv sync --extra dev             # install dependencies into .venv
uv run alembic upgrade head     # apply database migrations
uv run ghostmon user create -e you@example.com -s   # create a superuser (prompts for password)
uv run uvicorn app.api.main:app --reload            # API + scheduler on http://localhost:8000
```

Or the full stack with containers:

```bash
APP_SECRET_KEY=$(openssl rand -hex 32) podman compose up --build
```

Useful endpoints: `/` (web UI), `/docs` (API docs), `/healthz` (liveness),
`/readyz` (readiness — 503 when the database is unreachable), `/metrics`.

Collect system metrics from a host with the bundled agent (create a host in the UI,
mint an ingest token via `POST /api/ingest-tokens`, then):

```bash
GHOSTMON_INGEST_TOKEN=gmi_… uv run ghostmon agent run --host web-01 --url http://localhost:8000
```

## Test

Tests run against a **real PostgreSQL** database (the schema uses Postgres-specific
types), not SQLite. Bring one up first:

```bash
podman run --rm -d --name ghostmon-test-pg \
  -e POSTGRES_USER=ghostmon -e POSTGRES_PASSWORD=ghostmon -e POSTGRES_DB=ghostmon_test \
  -p 5432:5432 docker.io/library/postgres:16-alpine

uv run pytest                                   # full suite
uv run pytest tests/test_probes.py -q           # one module
uv run pytest tests/test_probes.py::test_name   # one test
```

Quality gate (all enforced in CI):

```bash
uv run ruff format --check .    # formatting
uv run ruff check .             # lint
uv run mypy app                 # strict type-checking
```

## Deploy

Build an OCI image and run it against a managed Postgres:

```bash
podman build -t ghostmon:latest .
podman run -d --name ghostmon -p 8000:8000 \
  -e APP_ENV=production \
  -e APP_SECRET_KEY=... \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/ghostmon \
  ghostmon:latest
```

Run `uv run alembic upgrade head` against the target database before starting a new
release. Configuration is 12-factor (environment variables only); see `.env.example`
for the full list. `APP_SECRET_KEY` is required and validated at startup.

## Architecture

Layered, with dependencies pointing inward toward `app/core`:

| Layer | Path | Responsibility |
| --- | --- | --- |
| Domain & infra | `app/core/` | ORM models, Pydantic schemas, service classes, security, DB session |
| HTTP | `app/api/` | FastAPI app factory, REST routes (`/api`), server-rendered web UI |
| Background | `app/tasks/` | Probe scheduler, probe implementations, notification dispatch |
| CLI | `app/cli/` | Typer admin commands (`ghostmon user …`, `ghostmon monitor …`) |

The scheduler runs **in-process** with the API. A reconcile job (every 15s) diffs the
monitors in the database against the live APScheduler jobs and converges them — the
database is the single source of truth; you change a monitor's `interval`/`status`
rather than scheduling probe jobs directly. Probe results are persisted as
`MonitorResult` rows, and alerts fire only on genuine UP↔DOWN transitions.

See `CLAUDE.md` for a deeper architecture walkthrough.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 StackOps HQ.
