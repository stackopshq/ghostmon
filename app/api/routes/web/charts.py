"""Server-rendered time-series chart geometry.

Pure functions that turn a series of (timestamp, value) points into SVG
coordinates — no JavaScript, no chart library, consistent with the inline
sparklines. The template draws the polyline, area and tick labels from a
`ChartView`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ChartView:
    width: int
    height: int
    empty: bool = True
    line: str = ""
    area: str = ""
    # (pixel, label) pairs for the axes.
    y_ticks: list[tuple[float, str]] = field(default_factory=list)
    x_ticks: list[tuple[float, str]] = field(default_factory=list)
    plot_left: float = 0.0
    plot_right: float = 0.0
    plot_top: float = 0.0
    plot_bottom: float = 0.0


def _fmt_value(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"


def _fmt_time(moment: datetime, span_seconds: float) -> str:
    # Short labels: time-of-day for sub-day spans, otherwise the date.
    if span_seconds <= 86_400:
        return moment.strftime("%H:%M")
    return moment.strftime("%m-%d")


def line_chart(
    series: list[tuple[datetime, float]],
    *,
    width: int = 720,
    height: int = 240,
    pad_left: int = 48,
    pad_right: int = 12,
    pad_top: int = 12,
    pad_bottom: int = 24,
) -> ChartView:
    """Build chart geometry from chronological (timestamp, value) points.

    Fewer than two points → an empty view (the caller renders a placeholder).
    X is scaled by time; if every point shares a timestamp it falls back to an
    even index spread. Y spans the value range with a small headroom.
    """
    view = ChartView(width=width, height=height)
    if len(series) < 2:
        return view

    left, right = float(pad_left), float(width - pad_right)
    top, bottom = float(pad_top), float(height - pad_bottom)
    view.plot_left, view.plot_right, view.plot_top, view.plot_bottom = left, right, top, bottom

    times = [t for t, _ in series]
    values = [v for _, v in series]
    t0, t1 = times[0], times[-1]
    span = (t1 - t0).total_seconds()
    lo, hi = min(values), max(values)
    if hi == lo:  # flat series → center the line with a unit range
        lo, hi = lo - 1.0, hi + 1.0
    vrange = hi - lo
    last_index = len(series) - 1

    def _x(i: int, t: datetime) -> float:
        frac = ((t - t0).total_seconds() / span) if span > 0 else (i / last_index)
        return left + (right - left) * frac

    def _y(v: float) -> float:
        return top + (bottom - top) * (1 - (v - lo) / vrange)

    pts = [(_x(i, t), _y(v)) for i, (t, v) in enumerate(series)]
    view.line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    view.area = f"{pts[0][0]:.1f},{bottom:.1f} " + view.line + f" {pts[-1][0]:.1f},{bottom:.1f}"

    # Three horizontal value ticks: lo, mid, hi.
    view.y_ticks = [
        (_y(lo), _fmt_value(lo)),
        (_y((lo + hi) / 2), _fmt_value((lo + hi) / 2)),
        (_y(hi), _fmt_value(hi)),
    ]
    # Three time ticks: start, middle, end.
    mid = series[len(series) // 2]
    view.x_ticks = [
        (left, _fmt_time(t0, span)),
        (_x(len(series) // 2, mid[0]), _fmt_time(mid[0], span)),
        (right, _fmt_time(t1, span)),
    ]
    view.empty = False
    return view
