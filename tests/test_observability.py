"""Storage/ingestion metrics — the data behind a future scaling decision."""

from __future__ import annotations

from typing import Any

from prometheus_client import REGISTRY
from sqlalchemy import text

from app.core.models.host import Host, Item, ItemValueType
from app.core.observability import update_storage_metrics
from app.core.services.host_service import ItemService


def _ingested() -> float:
    return REGISTRY.get_sample_value("ghostmon_values_ingested_total") or 0.0


async def _item(session: Any, owner_id: Any) -> Item:
    host = Host(name="srv", owner_id=owner_id)
    session.add(host)
    await session.flush()
    item = Item(host_id=host.id, key="cpu", name="CPU", value_type=ItemValueType.FLOAT, interval=60)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def test_record_value_increments_ingestion_counter(session: Any, user: Any) -> None:
    item = await _item(session, user.id)
    before = _ingested()
    await ItemService(session).record_value(item, 42.0)
    await ItemService(session).record_value(item, 43.0)
    assert _ingested() == before + 2


async def test_storage_metrics_estimate_table_rows(session: Any, user: Any) -> None:
    item = await _item(session, user.id)
    for v in range(5):
        await ItemService(session).record_value(item, float(v))
    # reltuples is maintained by ANALYZE — refresh it so the estimate is meaningful.
    await session.execute(text("ANALYZE metric_values"))
    await session.commit()

    await update_storage_metrics(session)
    rows = REGISTRY.get_sample_value("ghostmon_table_rows_estimate", {"table": "metric_values"})
    assert rows is not None
    assert rows >= 5
