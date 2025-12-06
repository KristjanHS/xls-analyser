# pyright: basic

from __future__ import annotations

import logging
import re
import os
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable, cast

import pandas as pd
from weasyprint import HTML  # type: ignore[reportMissingTypeStubs]

logger = logging.getLogger(__name__)


def generate_access_control_overview(
    *,
    normalized_events_df: pd.DataFrame,
    presence_intervals_df: pd.DataFrame,
    hourly_agg: pd.DataFrame,
    daily_agg: pd.DataFrame,
    reentries_df: pd.DataFrame,
    plots_dir: Path,
    reports_dir: Path,
    input_dir: Path,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Build the Ops Snapshot HTML and PDF (Iteration 2)."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    run_timestamp = datetime.now()

    context = _build_context(
        normalized_events_df=normalized_events_df,
        presence_intervals_df=presence_intervals_df,
        hourly_agg=hourly_agg,
        daily_agg=daily_agg,
        reentries_df=reentries_df,
        plots_dir=plots_dir,
        run_timestamp=run_timestamp,
        input_dir=input_dir,
        output_dir=output_dir,
    )

    html_content = _render_html(context)
    html_path = reports_dir / "access_control_overview.html"
    pdf_path = reports_dir / "access_control_overview.pdf"

    html_path.write_text(html_content, encoding="utf-8")
    logger.info("Saved HTML snapshot to %s", html_path)

    original_cwd = os.getcwd()
    try:
        os.chdir(reports_dir)
        HTML(string=html_content, base_url=".").write_pdf(pdf_path.name)
        logger.info("Exported PDF snapshot to %s", pdf_path)
    finally:
        os.chdir(original_cwd)

    return html_path, pdf_path


def _build_context(
    *,
    normalized_events_df: pd.DataFrame,
    presence_intervals_df: pd.DataFrame,
    hourly_agg: pd.DataFrame,
    daily_agg: pd.DataFrame,
    reentries_df: pd.DataFrame,
    plots_dir: Path,
    run_timestamp: datetime,
    input_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    events_count = int(len(normalized_events_df))
    intervals_count = int(len(presence_intervals_df))
    total_minutes = float(presence_intervals_df["duration_minutes"].sum()) if not presence_intervals_df.empty else 0.0
    teams = sorted(t for t in normalized_events_df["cleaner_team"].dropna().unique()) if events_count else []
    floors = (
        sorted(int(floor) for floor in presence_intervals_df["floor"].dropna().unique() if pd.notna(floor))
        if intervals_count
        else []
    )

    date_range = _date_range(normalized_events_df["date"]) if events_count else None

    highlights = {
        "top_floors": _top_floors(presence_intervals_df),
        "peak_hours": _peak_hours(hourly_agg),
        "busiest_days": _busiest_days(presence_intervals_df),
        "reentry_hotspots": _reentry_hotspots(reentries_df),
    }

    core_plots: list[tuple[str, Path]] = [
        ("Hourly heatmap", plots_dir / "heatmap_hourly.png"),
        ("Team vs floor", plots_dir / "team_comparison_floor.png"),
        ("Team vs day", plots_dir / "team_comparison_daily.png"),
    ]

    per_floor_plots = _discover_floor_plots(plots_dir)

    plot_commentary = {
        "Hourly heatmap": _commentary_heatmap(hourly_agg),
        "Team vs floor": _commentary_team_floor(presence_intervals_df),
        "Team vs day": _commentary_team_day(presence_intervals_df),
    }

    floor_commentary = {floor: _commentary_floor(presence_intervals_df, floor) for floor, _ in per_floor_plots}

    return {
        "run_timestamp": run_timestamp,
        "input_dir": input_dir,
        "output_dir": output_dir,
        "events_count": events_count,
        "intervals_count": intervals_count,
        "total_minutes": total_minutes,
        "teams": teams,
        "floors": floors,
        "date_range": date_range,
        "highlights": highlights,
        "plots": core_plots,
        "per_floor_plots": per_floor_plots,
        "plot_commentary": plot_commentary,
        "floor_commentary": floor_commentary,
        "csv_links": _csv_links(output_dir),
    }


def _render_html(context: dict[str, object]) -> str:
    run_timestamp: datetime = context["run_timestamp"]  # type: ignore[assignment]
    input_dir: Path = context["input_dir"]  # type: ignore[assignment]
    output_dir: Path = context["output_dir"]  # type: ignore[assignment]
    events_count: int = context["events_count"]  # type: ignore[assignment]
    intervals_count: int = context["intervals_count"]  # type: ignore[assignment]
    total_minutes: float = context["total_minutes"]  # type: ignore[assignment]
    teams: list[str] = context["teams"]  # type: ignore[assignment]
    floors: list[int] = context["floors"]  # type: ignore[assignment]
    date_range: tuple[str, str] | None = context["date_range"]  # type: ignore[assignment]
    highlights: dict[str, list[str]] = context["highlights"]  # type: ignore[assignment]
    plots: list[tuple[str, Path]] = context["plots"]  # type: ignore[assignment]
    per_floor_plots: list[tuple[int, Path]] = context["per_floor_plots"]  # type: ignore[assignment]
    plot_commentary: dict[str, list[str]] = context["plot_commentary"]  # type: ignore[assignment]
    floor_commentary: dict[int, list[str]] = context["floor_commentary"]  # type: ignore[assignment]
    csv_links: list[tuple[str, Path, bool]] = context["csv_links"]  # type: ignore[assignment]

    date_range_text = f"{date_range[0]} to {date_range[1]}" if date_range else "N/A"
    teams_text = f"{len(teams)} ({', '.join(teams)})" if teams else "0"
    floors_text = f"{len(floors)} ({', '.join(str(f) for f in floors)})" if floors else "0"

    quick_highlights = "".join(
        _render_list_block(title, items)
        for title, items in [
            ("Top floors", highlights.get("top_floors", [])),
            ("Peak hours", highlights.get("peak_hours", [])),
            ("Busiest days", highlights.get("busiest_days", [])),
            ("Re-entry hotspots", highlights.get("reentry_hotspots", [])),
        ]
    )

    plots_html = "".join(
        _render_plot_block(title, path, plot_commentary.get(title, _default_commentary())) for title, path in plots
    )

    floor_list_text = ", ".join(str(floor) for floor, _ in per_floor_plots) if per_floor_plots else "None"

    floor_plots_html = (
        "".join(
            _render_plot_block(
                f"Floor {floor} — stacked team minutes",
                path,
                floor_commentary.get(floor, _default_commentary()),
            )
            for floor, path in per_floor_plots
        )
        if per_floor_plots
        else '<p class="missing">No per-floor stacked charts found.</p>'
    )

    csv_links_html = _render_links(csv_links)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Access Control Overview</title>
  <style>
    body {{
      font-family: "Helvetica Neue", Arial, sans-serif;
      color: #1f2a32;
      margin: 32px;
      line-height: 1.6;
    }}
    h1 {{
      margin-bottom: 8px;
      font-size: 28px;
      letter-spacing: -0.5px;
    }}
    h2 {{
      margin-top: 24px;
      margin-bottom: 8px;
      font-size: 20px;
      border-bottom: 2px solid #e2e8f0;
      padding-bottom: 4px;
    }}
    h3 {{
      margin-top: 12px;
      margin-bottom: 6px;
      font-size: 16px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }}
    .card {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 14px 16px;
    }}
    .meta-list, .kpi-list {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}
    .meta-list li, .kpi-list li {{
      margin-bottom: 6px;
    }}
    .list-block ul {{
      margin: 6px 0 0 20px;
    }}
    figure {{
      margin: 18px 0;
      padding: 12px;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      background: #fff;
    }}
    figure img {{
      max-width: 100%;
      display: block;
      margin-bottom: 6px;
      border-radius: 4px;
    }}
    figure figcaption {{
      font-size: 14px;
      color: #4a5568;
    }}
    .plot-block {{
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 24px;
    }}
    .plot-notes {{
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 12px;
    }}
    .plot-notes h3 {{
      margin-top: 0;
      margin-bottom: 8px;
    }}
    .commentary {{
      margin: 0;
      padding-left: 18px;
    }}
    .commentary li {{
      margin-bottom: 6px;
    }}
    .missing {{
      color: #b45309;
      font-style: italic;
    }}
    .data-quality {{
      border-left: 4px solid #0f766e;
      padding-left: 12px;
      margin-top: 8px;
      background: #ecfeff;
    }}
    .link-list {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}
    .link-list li {{
      margin-bottom: 6px;
    }}
    @media print {{
      body {{
        margin: 24px;
      }}
      .plot-block {{
        display: block;
      }}
    }}
  </style>
</head>
<body>
  <h1>Ops Snapshot — Access Control Overview</h1>
  <p>Run timestamp: {escape(run_timestamp.isoformat(sep=" ", timespec="seconds"))}</p>

  <div class="grid">
    <div class="card">
      <h2>Run metadata</h2>
      <ul class="meta-list">
        <li><strong>Input folder:</strong> {escape(str(input_dir))}</li>
        <li><strong>Output folder:</strong> {escape(str(output_dir))}</li>
      </ul>
    </div>
    <div class="card">
      <h2>KPIs</h2>
      <ul class="kpi-list">
        <li><strong>Events:</strong> {events_count:,}</li>
        <li><strong>Presence intervals:</strong> {intervals_count:,}</li>
        <li><strong>Total minutes tracked:</strong> {_format_number(total_minutes)}</li>
        <li><strong>Teams:</strong> {escape(teams_text)}</li>
        <li><strong>Floors:</strong> {escape(floors_text)}</li>
        <li><strong>Date range:</strong> {escape(date_range_text)}</li>
      </ul>
    </div>
  </div>

  <h2>Quick highlights</h2>
  <div class="grid">
    {quick_highlights}
  </div>

  <h2>Visuals</h2>
  {plots_html}

  <h2>Per-floor stacked charts</h2>
  <p><strong>Floors present:</strong> {escape(floor_list_text)}</p>
  {floor_plots_html}

  <h2>Key CSV outputs</h2>
  {csv_links_html}

  <h2>Data quality note</h2>
  <p class="data-quality">
    Thresholds per access_control_confidence_plan.md: missing wings are expected (no warning). Warn if missing names
    reach 10+ per run or if timestamp parse failures reach 10+. Update warnings in the confidence plan log when these
    thresholds are crossed.
  </p>
</body>
</html>
"""


def _render_list_block(title: str, items: Iterable[str]) -> str:
    safe_title = escape(title)
    item_list = list(items)
    if not item_list:
        return f"""
    <div class="card list-block">
      <h3>{safe_title}</h3>
      <p class="missing">No data available.</p>
    </div>
    """

    list_items = "\n".join(f"<li>{escape(item)}</li>" for item in item_list)
    return f"""
    <div class="card list-block">
      <h3>{safe_title}</h3>
      <ul>{list_items}</ul>
    </div>
    """


def _render_plot(title: str, path: Path) -> str:
    safe_title = escape(title)
    if not path.exists():
        return f"""
    <div class="plot-media">
      <p class="missing">{safe_title}: plot not found at {escape(str(path))}</p>
    </div>
    """

    return f"""
    <div class="plot-media">
      <figure>
        <img src="{escape(path.name)}" alt="{safe_title}" />
        <figcaption>{safe_title}</figcaption>
      </figure>
    </div>
    """


def _render_plot_block(title: str, path: Path, commentary: list[str]) -> str:
    commentary_html = _render_commentary(title, commentary)
    plot_html = _render_plot(title, path)
    return f"""
  <section class="plot-block">
    {plot_html}
    {commentary_html}
  </section>
    """


def _render_commentary(title: str, commentary: list[str]) -> str:
    safe_title = escape(title)
    bullets = commentary if commentary else _default_commentary()
    bullet_items = "".join(f"<li>{escape(item)}</li>" for item in bullets)
    return f"""
    <div class="plot-notes">
      <h3>{safe_title} commentary</h3>
      <ul class="commentary">
        {bullet_items}
      </ul>
    </div>
    """


def _render_links(links: list[tuple[str, Path, bool]]) -> str:
    if not links:
        return '<p class="missing">No CSV outputs detected.</p>'

    items = []
    for label, path, exists in links:
        safe_label = escape(label)
        if exists:
            items.append(f'<li><a href="{escape(path.name)}">{safe_label}</a></li>')
        else:
            items.append(f'<li class="missing">{safe_label}: missing at {escape(str(path))}</li>')
    items_html = "\n".join(items)
    return f"""
  <ul class="link-list">
    {items_html}
  </ul>
    """


def _date_range(date_series: pd.Series) -> tuple[str, str] | None:
    if date_series.empty:
        return None
    valid_dates = date_series.dropna()
    if valid_dates.empty:
        return None
    start_date = valid_dates.min()
    end_date = valid_dates.max()
    return str(start_date), str(end_date)


def _top_floors(presence_intervals_df: pd.DataFrame, limit: int = 3) -> list[str]:
    if presence_intervals_df.empty:
        return []
    grouped: pd.DataFrame = (
        presence_intervals_df[presence_intervals_df["floor"].notna()]
        .groupby("floor", as_index=False)
        .agg(duration_minutes=("duration_minutes", "sum"))
        .sort_values(by="duration_minutes", ascending=False)
        .head(limit)
    )
    results: list[str] = []
    for _, row in grouped.iterrows():
        results.append(f"Floor {int(row['floor'])}: {_format_number(row['duration_minutes'])} minutes")
    return results


def _peak_hours(hourly_agg: pd.DataFrame, limit: int = 3) -> list[str]:
    if hourly_agg.empty:
        return []
    grouped: pd.DataFrame = (
        hourly_agg.groupby("hour", as_index=False)
        .agg(minutes_present=("minutes_present", "sum"))
        .sort_values(by="minutes_present", ascending=False)
        .head(limit)
    )
    results: list[str] = []
    for _, row in grouped.iterrows():
        hour = int(row["hour"])
        label = f"{hour:02d}:00"
        results.append(f"{label} — {_format_number(row['minutes_present'])} minutes")
    return results


def _busiest_days(presence_intervals_df: pd.DataFrame, limit: int = 3) -> list[str]:
    if presence_intervals_df.empty:
        return []
    grouped: pd.DataFrame = (
        presence_intervals_df.groupby("date", as_index=False)
        .agg(duration_minutes=("duration_minutes", "sum"))
        .sort_values(by="duration_minutes", ascending=False)
        .head(limit)
    )
    return [f"{row['date']}: {_format_number(row['duration_minutes'])} minutes" for _, row in grouped.iterrows()]


def _reentry_hotspots(reentries_df: pd.DataFrame, limit: int = 3) -> list[str]:
    if reentries_df.empty:
        return []
    df = reentries_df.copy()
    df = df[df["re_entries"] > 0]
    if df.empty:
        return []

    df["location"] = df.apply(
        lambda row: _format_floor_wing(
            cast(float | int | str | None, row.get("floor")),
            cast(float | int | str | None, row.get("wing")),
        ),
        axis=1,
    )

    grouped = df.sort_values(["re_entries", "total_minutes_present"], ascending=[False, False]).head(limit)

    results: list[str] = []
    for _, row in grouped.iterrows():
        reentries = int(row["re_entries"])
        minutes = _format_number(row.get("total_minutes_present", 0))
        team = row.get("cleaner_team", "Unknown")
        results.append(f"{row['location']} — {reentries} re-entries ({team}, {minutes} minutes)")
    return results


def _format_floor_wing(floor: float | int | str | None, wing: float | int | str | None) -> str:
    floor_label = "Unknown floor" if pd.isna(floor) else f"Floor {int(floor)}"
    wing_label = "" if wing is None or pd.isna(wing) else str(wing)
    suffix = f"{wing_label}" if wing_label else ""
    return f"{floor_label}{suffix}"


def _format_number(value: float | int) -> str:
    return f"{value:,.0f}"


def _discover_floor_plots(plots_dir: Path) -> list[tuple[int, Path]]:
    """Find per-floor stacked charts generated by the pipeline."""
    if not plots_dir.exists():
        return []

    pattern = re.compile(r"^floor_(\d+)_stacked\.png$")
    found: list[tuple[int, Path]] = []
    for entry in plots_dir.iterdir():
        if not entry.is_file():
            continue
        match = pattern.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry))

    return sorted(found, key=lambda item: item[0])


def _default_commentary() -> list[str]:
    return [
        "Summary — data not available yet for this plot.",
        "Reflection — rerun the pipeline or refresh the inputs to populate this view.",
        "Data quality — ensure source CSVs parsed and plots are written alongside the report.",
    ]


def _commentary_heatmap(hourly_agg: pd.DataFrame, limit: int = 3) -> list[str]:
    if hourly_agg.empty:
        return _default_commentary()

    hour_totals = (
        hourly_agg.groupby("hour", as_index=False)["minutes_present"]
        .sum()
        .reset_index()
        .sort_values(by="minutes_present", ascending=False)
    )
    top_hours = hour_totals.head(limit)
    top_hours_text = ", ".join(
        f"{int(row['hour']):02d}:00 ({_format_number(row['minutes_present'])} min)" for _, row in top_hours.iterrows()
    )

    floor_totals = (
        hourly_agg.groupby("floor", as_index=False)["minutes_present"]
        .sum()
        .reset_index()
        .sort_values(by="minutes_present", ascending=False)
    )
    top_floor = floor_totals.iloc[0] if not floor_totals.empty else None
    top_floor_text = (
        f"Floor {int(top_floor['floor'])} leading with {_format_number(top_floor['minutes_present'])} minutes"
        if top_floor is not None
        else "No floor activity logged"
    )

    missing_floors = int(hourly_agg["floor"].isna().sum())

    return [
        f"Summary — peak activity hours: {top_hours_text}; {top_floor_text}.",
        "Reflection — use peaks to align staffing; confirm off-peak coverage is intentional.",
        f"Data quality — {missing_floors} rows missing floor labels; wings may be blank by design.",
    ]


def _commentary_team_floor(presence_intervals_df: pd.DataFrame, limit: int = 3) -> list[str]:
    if presence_intervals_df.empty:
        return _default_commentary()

    grouped = (
        presence_intervals_df.groupby(["floor", "cleaner_team"], as_index=False)["duration_minutes"]
        .sum()
        .reset_index()
        .sort_values(by="duration_minutes", ascending=False)
    )
    top_pairs = grouped.head(limit)
    top_pairs_text = ", ".join(
        f"Floor {int(row['floor'])} — {row['cleaner_team']} ({_format_number(row['duration_minutes'])} min)"
        for _, row in top_pairs.iterrows()
    )

    floor_spread = presence_intervals_df.groupby("floor")["cleaner_team"].nunique()
    multi_team_floors = int((floor_spread > 1).sum())

    return [
        f"Summary — top team/floor combinations: {top_pairs_text}.",
        "Reflection — rebalance if one team dominates multiple floors or a floor lacks backups.",
        f"Data quality — {multi_team_floors} floors have multiple teams; verify floor labels are consistent.",
    ]


def _commentary_team_day(presence_intervals_df: pd.DataFrame, limit: int = 3) -> list[str]:
    if presence_intervals_df.empty:
        return _default_commentary()

    daily_totals = (
        presence_intervals_df.groupby("date", as_index=False)["duration_minutes"]
        .sum()
        .reset_index()
        .sort_values(by="duration_minutes", ascending=False)
    )
    top_days = daily_totals.head(limit)
    top_days_text = ", ".join(
        f"{row['date']} ({_format_number(row['duration_minutes'])} min)" for _, row in top_days.iterrows()
    )

    team_days = presence_intervals_df.groupby("date")["cleaner_team"].nunique()
    single_team_days = int((team_days == 1).sum())

    return [
        f"Summary — busiest days: {top_days_text}.",
        "Reflection — align supplies/coverage to match busiest days; spot-check quieter days for missed scans.",
        f"Data quality — {single_team_days} days show only one team; confirm logging across teams is complete.",
    ]


def _commentary_floor(presence_intervals_df: pd.DataFrame, floor: int, limit: int = 2) -> list[str]:
    floor_df = presence_intervals_df[presence_intervals_df["floor"] == floor]
    if floor_df.empty:
        return _default_commentary()

    team_totals = (
        floor_df.groupby("cleaner_team", as_index=False)["duration_minutes"]
        .sum()
        .reset_index()
        .sort_values(by="duration_minutes", ascending=False)
    )
    top_teams = team_totals.head(limit)
    teams_text = ", ".join(
        f"{row['cleaner_team']} ({_format_number(row['duration_minutes'])} min)" for _, row in top_teams.iterrows()
    )

    day_span = floor_df["date"].nunique()
    missing_wings = int(floor_df["wing"].isna().sum())

    return [
        f"Summary — top teams on floor {floor}: {teams_text}.",
        f"Reflection — coverage spans {day_span} days; consider rotation if one team is over-weighted.",
        f"Data quality — {missing_wings} intervals missing wing; blanks are expected when wings are not specified.",
    ]


def _csv_links(output_dir: Path) -> list[tuple[str, Path, bool]]:
    candidates = [
        ("Hourly by floor/wing/team", output_dir / "hourly_floor_wing.csv"),
        ("Daily by floor/wing", output_dir / "daily_floor_wing.csv"),
        ("Per-team by floor/wing", output_dir / "team_floor_wing.csv"),
        ("Re-entries", output_dir / "reentries.csv"),
    ]
    return [(label, path, path.exists()) for label, path in candidates]
