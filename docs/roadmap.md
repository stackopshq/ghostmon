# Roadmap — toward a self-hosted Zabbix alternative

This roadmap sequences the work from today's uptime monitor toward the target
architecture in [ADR 0001](adr/0001-target-architecture-zabbix-alternative.md).
Each phase ships independently and keeps the app usable.

## Where we are (v0.1)

Agentless uptime monitoring: `Monitor` checks (HTTP / TCP / SSL / PING) on a
per-monitor interval, binary UP/DOWN status with latency, maintenance windows, and
email/webhook notifications on status transitions. Auth (local + OIDC), web UI,
REST API, CLI, Prometheus metrics, liveness/readiness probes.

## Phase 1 — Triggers & severities *(next)*

Introduce a real problem-detection layer on top of the metrics already collected.

- `Trigger(host/item, expression, severity)` with `info|warning|average|high|disaster`.
- Evaluate thresholds on existing signals (latency, TLS days-to-expiry, HTTP status).
- Problem/OK state machine replacing the hardcoded UP↔DOWN transition.
- Severity-routed alerting (notification channels gain a minimum severity).

## Phase 2 — Hosts, Items & history

The foundational data-model shift (the core of ADR 0001).

- `Host` (groups, tags) → `Item` (key, type, interval) → time-series `history`.
- Reframe the current monitor as a `Host` with one agentless availability `Item`;
  migrate `MonitorResult` into item history (expand → migrate → contract, reversible).
- Retention for raw history + hourly `trends` (min/avg/max) for long-range graphs.

## Phase 3 — Templates & richer collection

- `Template` = reusable items + triggers, applied to many hosts.
- **ghostmon-agent**: a lightweight agent (push or pull) reporting system metrics
  (CPU, memory, disk, load) to an ingestion endpoint.
- SNMP polling for network devices.

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
