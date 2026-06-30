# Roadmap — toward a self-hosted Zabbix alternative

This roadmap sequences the work from today's uptime monitor toward the target
architecture in [ADR 0001](adr/0001-target-architecture-zabbix-alternative.md).
Each phase ships independently and keeps the app usable.

## Where we are (v0.1)

Agentless uptime monitoring: `Monitor` checks (HTTP / TCP / SSL / PING) on a
per-monitor interval, binary UP/DOWN status with latency, maintenance windows, and
email/webhook notifications on status transitions. Auth (local + OIDC), web UI,
REST API, CLI, Prometheus metrics, liveness/readiness probes.

## Phase 1 — Triggers & severities ✅ *(shipped)*

A problem-detection layer on top of the metrics already collected.

- ✅ `Trigger(monitor, metric, operator, threshold, severity)` with
  `info|warning|average|high|disaster`; threshold rules on the `latency_ms` metric
  (the `metric` enum is the extension point for TLS days-to-expiry, HTTP status, …).
- ✅ Problem/OK state machine evaluated each probe, alerting on state changes
  (alongside the existing availability UP↔DOWN alerts).
- ✅ Severity-routed alerting — notification channels gained a `min_severity`.
- Follow-ups: aggregate expressions over history (`avg(metric, 5m) > x`), more
  metrics, and a web UI for managing triggers.

## Phase 2 — Hosts, Items & history *(in progress)*

The foundational data-model shift (the core of ADR 0001), via expand → migrate → contract.

- ✅ **Expand**: additive `Host` → `Item` (key, value_type, units, interval) →
  append-only `metric_values` history, with CRUD + a value-ingestion/read API.
- ✅ **Migrate (bridge)**: each monitor gets a backing host + `latency_ms` item
  (lazily provisioned); probes mirror latency into item history.
- ✅ **Retention**: hourly pruning of history/results past `HISTORY_RETENTION_DAYS`.
- ✅ **Web UI**: hosts list + host detail (items CRUD, latest/min/max, server-rendered
  history sparklines).
- ✅ **History-aware triggers**: triggers can aggregate (`avg`/`min`/`max`) over a
  look-back window of item history instead of only the last probe value.
- *(deferred)* **Contract**: retire the monitor-specific tables — held back until
  status/error are modelled as items, so it doesn't regress the uptime feature.
- *(deferred)* Hourly `trends` (min/avg/max) — speculative until a long-range graph
  consumes them; the UI reads raw history for now.

## Privacy (the differentiator vs Zabbix)

GhostMonitor's reason to exist over a plain Zabbix clone is privacy (ghost-suite ethos).

- ✅ **Secrets encrypted at rest**: webhook signing secrets and SNMP communities are
  Fernet/AES-encrypted (key derived from `APP_SECRET_KEY`) and never returned in clear
  (write-only; redacted on read). A DB dump leaks no monitoring credentials.
- ✅ **Zero-knowledge "private items"**: items flagged `is_private` store
  client-encrypted ciphertext (AES-256-GCM); the server never decrypts or evaluates
  them. Reference CLI `ghostmon zk genkey|encrypt|decrypt`, and **in-browser
  decryption** on the host page via a key in the URL fragment (`#k=…`) that never
  reaches the server (Web Crypto, interoperable with the CLI). Verified end-to-end.
- Baseline: no telemetry, no third-party calls, minimal alert payloads, hashed ingest
  tokens, bounded retention.

## Phase 3 — Templates & richer collection *(in progress)*

- ✅ **Ingestion tokens**: long-lived per-owner tokens (SHA-256 stored, shown once)
  + a token-authenticated `POST /api/ingest` that auto-creates "trapper" items —
  so agents/scripts can push metrics without a user login.
- ✅ **ghostmon-agent**: a dependency-free agent (`ghostmon agent run`) reporting
  system metrics (load, memory %, disk %) from `/proc` to `/api/ingest`.
- ✅ **Item templates**: reusable `Template` → `TemplateItem` sets, applied to a host
  to provision its items (idempotent re-apply). Trigger templates wait for triggers
  to move onto items (the contract step).
- ✅ **CPU utilisation** in the agent via `/proc/stat` delta sampling.
- ✅ **SNMP** reachability monitor type (SNMPv2c GET via `pysnmp`).
- ✅ **Server-side item poller**: items gain a `source` (trapper | snmp) + `config`;
  hosts gain an `address`. A scheduler cycle polls due SNMP items (any OID) and
  appends to history — arbitrary metrics collected server-side, the full Zabbix shape.

## Phase 4 — Alerting escalation & dashboards

- Multi-step escalation actions (notify → wait → escalate → auto-remediate hooks).
- Dashboards and time-series graphs over item history/trends.
- Acknowledge / problem timeline.

## Phase 5 — Discovery & scale

- Network and host auto-discovery with rule-based item provisioning.
- Distributed collection (proxy/agent fan-in) and history storage scaling
  (evaluate TimescaleDB or a dedicated TSDB — measure first).

---

*Phases are intentionally coarse. Each is broken into atomic PRs as it is started;
the rule of three applies before introducing new abstractions.*
