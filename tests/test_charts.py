"""Server-rendered time-series chart geometry + the item-page render."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.api.routes.web.charts import line_chart
from app.core.models.host import Host, Item, ItemValueType
from app.core.models.metric_value import MetricValue

BASE = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def test_chart_empty_for_too_few_points() -> None:
    assert line_chart([]).empty
    assert line_chart([(BASE, 1.0)]).empty


def test_chart_geometry_spans_axes_and_orients_values() -> None:
    series = [(BASE + timedelta(minutes=10 * i), float(v)) for i, v in enumerate([10, 20, 30, 25])]
    cv = line_chart(series, width=720, height=240)
    assert not cv.empty

    pts = cv.line.split()
    assert len(pts) == 4
    first_x = float(pts[0].split(",")[0])
    last_x = float(pts[-1].split(",")[0])
    assert abs(first_x - cv.plot_left) < 0.5
    assert abs(last_x - cv.plot_right) < 0.5

    # Value ticks are min / mid / max; the max value sits higher (smaller y).
    assert [label for _, label in cv.y_ticks] == ["10", "20", "30"]
    y_of_min = float(pts[0].split(",")[1])  # value 10
    y_of_max = float(pts[2].split(",")[1])  # value 30
    assert y_of_max < y_of_min


def test_chart_flat_series_does_not_divide_by_zero() -> None:
    series = [(BASE + timedelta(minutes=i), 5.0) for i in range(3)]
    cv = line_chart(series)
    assert not cv.empty
    assert len(cv.line.split()) == 3


async def test_item_detail_page_renders_chart(
    web_client: httpx.AsyncClient, session: Any, user: Any
) -> None:
    host = Host(name="srv", owner_id=user.id)
    session.add(host)
    await session.flush()
    item = Item(host_id=host.id, key="cpu", name="CPU", value_type=ItemValueType.FLOAT, interval=60)
    session.add(item)
    await session.flush()
    for i, v in enumerate([12.0, 34.0, 28.0, 41.0]):
        session.add(
            MetricValue(item_id=item.id, value_num=v, collected_at=BASE + timedelta(minutes=10 * i))
        )
    await session.commit()

    page = await web_client.get(f"/hosts/{host.id}/items/{item.id}")
    assert page.status_code == 200
    assert "<h2>History</h2>" in page.text
    assert 'class="chart"' in page.text
    assert "chart-line" in page.text


def test_band_chart_empty_and_geometry() -> None:
    from app.api.routes.web.charts import band_chart

    assert band_chart([]).empty
    series = [(BASE + timedelta(hours=i), float(i), float(i) + 1, float(i) + 2) for i in range(4)]
    cv = band_chart(series)
    assert not cv.empty
    assert len(cv.line.split()) == 4  # avg polyline
    assert len(cv.band.split()) == 8  # max edge (4) + min edge (4)
    assert [label for _, label in cv.y_ticks] == ["0", "2.50", "5"]  # band spans min(0)..max(5)
