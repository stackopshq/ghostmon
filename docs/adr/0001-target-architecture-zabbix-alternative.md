# 1. Target architecture — a self-hosted Zabbix alternative

- Status: Accepted
- Date: 2026-06-30

## Context

GhostMonitor today is an uptime monitor: a `Monitor` is a single agentless check
(HTTP / TCP / SSL / PING) that produces a binary `UP`/`DOWN` status plus a latency
sample, and notifications fire on status transitions.

The product goal, however, is to be a **free, self-hosted alternative to Zabbix** —
general infrastructure and application monitoring, not just endpoint uptime. That is
a fundamentally larger model than what exists. This ADR records the target
architecture so subsequent work is deliberate rather than accreted.

## Decision

Adopt Zabbix's core data model, generalised and simplified, built around four
concepts:

1. **Host** — a monitored entity (server, device, service, URL). Hosts carry
   metadata (groups, tags) and own items.
2. **Item** — a single metric collected from a host on a schedule, identified by a
   *key* and typed (numeric float/unsigned, text, log). The current `Monitor` checks
   become one item *type* (agentless checks producing an availability/latency metric)
   rather than the central abstraction.
3. **History & trends** — every item collection appends a timestamped value to a
   time-series store, with configurable retention (raw history) and downsampled
   trends (hourly min/avg/max) for long-range graphs.
4. **Trigger** — a named expression over item history with a severity
   (`info` / `warning` / `average` / `high` / `disaster`). A trigger evaluates to a
   `PROBLEM` or `OK` state; problems drive alerting. This replaces the hardcoded
   `UP`/`DOWN` transition logic with a general threshold/expression engine.

Supporting concepts, layered on top:

- **Templates** — reusable sets of items + triggers applied to many hosts.
- **Collection methods** — agentless (current probes) first; then a lightweight
  **ghostmon-agent** (push or pull) for system metrics; SNMP later.
- **Alerting & escalation** — severity-routed, multi-step escalation actions
  (the current per-transition notify is the degenerate single-step case).
- **Discovery** — network/host auto-discovery (later phase).

### Architectural principles (carried over)

- Keep the layered structure (`core` domain/services ← `api`/`tasks`/`cli`).
- The database stays the source of truth; the scheduler reconciles collection jobs
  from item definitions (as it already does for monitors).
- History is write-heavy and time-series shaped: design it for append + range-scan,
  with retention/partitioning in mind (PostgreSQL native first; keep the door open
  to TimescaleDB / a dedicated TSDB if volume demands it — measure before adding).
- Trigger evaluation is a separate, testable stage fed by item history — no business
  logic in collectors.

## Consequences

- The current `Monitor` / `MonitorResult` / `MonitorStatus` model is reframed: a
  monitor becomes a host with one agentless availability item; its results become
  item history; its up/down becomes a built-in trigger. A migration path (expand →
  migrate → contract) is required and must be reversible.
- This is a multi-phase effort. The sequencing lives in `docs/roadmap.md`. Each phase
  ships independently and keeps the app usable.
- Until the model lands, positioning is "an uptime monitor on its way to a Zabbix
  alternative" — the README states current capabilities honestly and links the roadmap.
- Scope discipline: build toward this model, but apply the rule of three before
  abstracting, and confirm large data-model moves before executing them.
