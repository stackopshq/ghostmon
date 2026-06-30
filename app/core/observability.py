"""Storage/ingestion observability — the data needed to decide *when* the
time-series store must scale (partitioning, a TSDB), rather than guessing now.

Exposed on `/metrics` (default Prometheus registry):
- `ghostmon_values_ingested_total` — counter of metric values written to history;
  `rate()` of it is the ingestion throughput.
- `ghostmon_table_rows_estimate{table=...}` — approximate row counts for the
  time-series tables, sampled periodically from `pg_class.reltuples` (instant; no
  expensive `count(*)`), so growth is visible over time.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

VALUES_INGESTED = Counter(
    "ghostmon_values_ingested_total", "Metric values appended to time-series history"
)
TABLE_ROWS = Gauge(
    "ghostmon_table_rows_estimate", "Estimated row count of a time-series table", ["table"]
)

_TRACKED_TABLES = ("metric_values", "metric_trends", "monitor_results")


def count_ingested(n: int = 1) -> None:
    if n > 0:
        VALUES_INGESTED.inc(n)


async def update_storage_metrics(session: AsyncSession) -> None:
    """Refresh the table-size gauges from Postgres' planner statistics."""
    stmt = text(
        "SELECT relname, reltuples::bigint FROM pg_class WHERE relkind = 'r' AND relname IN :tables"
    ).bindparams(bindparam("tables", expanding=True))
    rows = (await session.execute(stmt, {"tables": list(_TRACKED_TABLES)})).all()
    seen = {relname: estimate for relname, estimate in rows}
    for table in _TRACKED_TABLES:
        TABLE_ROWS.labels(table=table).set(max(seen.get(table, 0), 0))
