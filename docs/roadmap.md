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

## Triggers on items

- ✅ Triggers can attach to an **item** (not just a monitor): a `Trigger` references
  exactly one of `monitor_id` / `item_id` (DB-enforced). Item triggers evaluate the
  item's latest value or a window of its history, and alert through the **host's**
  notification channels (host↔channel attachment from earlier). Evaluated on every
  value write (ingest API, user push, SNMP poll). Private items are skipped.
- ✅ **Web UI**: an item detail page (linked from the host's items table) manages an
  item's triggers (add/list/delete with severity/state pills) and shows recent values.

## Phase 2 — Hosts, Items & history *(in progress)*

The foundational data-model shift (the core of ADR 0001), via expand → migrate → contract.

- ✅ **Expand**: additive `Host` → `Item` (key, value_type, units, interval) →
  append-only `metric_values` history, with CRUD + a value-ingestion/read API.
- ✅ **Migrate (bridge)**: each monitor gets a backing host with `latency_ms`,
  `status` (1=up/0=down) and `error` items (lazily provisioned); every probe mirrors
  status (and latency/error when present) into item history. Modelling status/error
  as items — not just latency — completes the migrate step and is the precondition
  for a future contract.
- ✅ **Retention**: hourly pruning of history/results past `HISTORY_RETENTION_DAYS`.
- ✅ **Web UI**: hosts list + host detail (items CRUD, latest/min/max, server-rendered
  history sparklines).
- ✅ **History-aware triggers**: triggers can aggregate (`avg`/`min`/`max`) over a
  look-back window of item history instead of only the last probe value.
- ✅ **Trends**: hourly min/avg/max rollups (`metric_trends`) downsample numeric
  history so long-range data survives raw-sample retention. The maintenance job rolls
  up before pruning (re-aggregating the last few hours so late data and missed runs
  are caught), with a separate, longer trend retention. Read API
  `GET /api/hosts/{h}/items/{i}/trends` and an "Hourly trends" table on the item page.
- *(deferred)* **Contract**: retire the monitor-specific tables. The data-model
  precondition is now met (status/error/latency all mirrored as items), but the
  destructive step is still held back — it would require porting probing to an
  item-source, rebuilding the dashboard/monitor UI on hosts/items, and a data
  migration. Deferred deliberately: it regresses a working feature for no user
  benefit yet. Revisit when the monitor model actively blocks something.

## Privacy (the differentiator vs Zabbix)

GhostMonitor's reason to exist over a plain Zabbix clone is privacy (ghost-suite ethos).

- ✅ **Secrets & targets encrypted at rest**: webhook signing secrets and SNMP
  communities are Fernet/AES-encrypted (key derived from `APP_SECRET_KEY`) and never
  returned in clear (write-only; redacted on read). The **alert targets** — webhook
  URLs and email recipients — are encrypted at rest too (a DB dump reveals neither
  where alerts go nor who is notified), but decrypted back for the owner who edits
  them. A DB dump leaks no monitoring credentials or destinations.
- ✅ **Zero-knowledge "private items"**: items flagged `is_private` store
  client-encrypted ciphertext (AES-256-GCM); the server never decrypts or evaluates
  them. Two key modes, matching ghostbit's e2e: a random key in the URL fragment
  (`#k=…`), or an **Argon2id passphrase** (same parameters as ghostbit, so tokens are
  interoperable across the CLI and the browser). In-browser decryption via Web Crypto
  + hash-wasm; reference CLI `ghostmon zk genkey|encrypt|decrypt [--key|--password]`.
  Verified end-to-end in a real browser.
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

## Phase 4 — Alerting escalation & dashboards *(in progress)*

- ✅ **Time-series graphs**: a server-rendered SVG line chart over an item's history
  on the item page (no JavaScript, no chart library — consistent with the inline
  sparklines). Geometry is a pure, unit-tested helper.
- ✅ **Host dashboard**: an at-a-glance grid (`/hosts/{id}/dashboard`) of a host's
  items, each card showing a mini-chart, current value and worst trigger state.
- ✅ **Problem timeline + acknowledge**: trigger OK↔PROBLEM transitions are persisted
  as problem events (opened on a flip, resolved on recovery), shown on a `/problems`
  timeline with severity, duration and one-click acknowledge. Read/ack REST API too.
- ✅ **Multi-step escalation**: an ordered policy notifies channels at increasing
  delays while a problem stays open and unacknowledged (ack/resolve stop it).
  Per-minute engine + REST CRUD + a web page to manage the ladder.
- ✅ **Hosts overview**: the host list shows each host's health (item count, ongoing
  problem count and worst severity), problem hosts sorted first — aggregated in two
  grouped queries (no N+1).
- ✅ **Auto-remediation actions**: an escalation step can carry an `action_command`,
  making it POST a structured remediation intent (command + problem context) to a
  **webhook** channel for an external runbook — the server never runs commands itself
  (webhook-only, validated on create and at fire time).
- *(next)* long-range charts backed by trends.

## Phase 5 — Discovery & scale

- Network and host auto-discovery with rule-based item provisioning.
- Distributed collection (proxy/agent fan-in) and history storage scaling
  (evaluate TimescaleDB or a dedicated TSDB — measure first).

---

*Phases are intentionally coarse. Each is broken into atomic PRs as it is started;
the rule of three applies before introducing new abstractions.*
