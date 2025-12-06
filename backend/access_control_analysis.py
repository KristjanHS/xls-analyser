# pyright: basic

"""Access control log analysis module.

This module processes Excel files containing access control logs for cleaning staff,
normalizes events, builds presence models, and generates aggregations and visualizations.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, cast

import matplotlib.pyplot as plt
import pandas as pd

DataFrame = pd.DataFrame

logger = logging.getLogger(__name__)


def load_excel_files(folder_path: Path) -> dict[str, pd.DataFrame]:
    """Load all Excel files from the specified folder.

    Args:
        folder_path: Path to folder containing .xlsx files

    Returns:
        Dictionary mapping filename (stem) to raw DataFrame
    """
    folder = Path(folder_path)
    if not folder.exists():
        msg = f"Folder not found: {folder}"
        raise FileNotFoundError(msg)

    excel_files = list(folder.glob("*.xlsx"))
    if not excel_files:
        msg = f"No Excel files found in {folder}"
        raise ValueError(msg)

    logger.info("Found %d Excel file(s) in %s", len(excel_files), folder)

    result: dict[str, DataFrame] = {}
    for file_path in excel_files:
        logger.info("Loading %s", file_path.name)
        # Read all columns; pandas will auto-assign column names if header is missing
        df = cast(DataFrame, pd.read_excel(file_path, engine="openpyxl", header=None))
        result[file_path.stem] = df

    return result


def normalize_events(raw_df: DataFrame, cleaner_team: str, source_file: str) -> DataFrame:
    """Normalize raw Excel data into structured events.

    Args:
        raw_df: Raw DataFrame from Excel file
        cleaner_team: Name of the cleaning team (from filename)
        source_file: Source filename

    Returns:
        Normalized DataFrame with columns: timestamp, date, time, cleaner_team,
        person_name_raw, door_name_raw, floor, wing, event_type, source_file
    """
    # Column mapping based on user specification:
    # A = timestamp, C = event_type, H = door_name, AL = person_name (primary)
    # Additional person name fallbacks: AJ, AG, AB, AF
    # Excel columns: A=0, C=2, H=7, AB=27, AF=31, AG=32, AJ=35, AL=37
    col_timestamp = 0  # Column A
    col_event_type = 2  # Column C
    col_door_name = 7  # Column H
    col_person_name = 37  # Column AL
    col_person_name_fallbacks = [35, 32, 27, 31]  # AJ, AG, AB, AF

    # Get actual column names from DataFrame
    cols: list[Any] = raw_df.columns.tolist()
    # Use actual column names/indices
    timestamp_col = cols[col_timestamp] if col_timestamp < len(cols) else None
    event_type_col = cols[col_event_type] if col_event_type < len(cols) else None
    door_name_col = cols[col_door_name] if col_door_name < len(cols) else None
    person_name_col = cols[col_person_name] if col_person_name < len(cols) else None
    person_name_fallback_cols = [cols[i] for i in col_person_name_fallbacks if i < len(cols)]

    # Filter: column C (event_type) non-empty
    if event_type_col is None:
        logger.warning("Event type column (C) not found; returning empty DataFrame")
        return _create_empty_normalized_df()

    df = raw_df.loc[raw_df[event_type_col].notna()].copy()

    if df.empty:
        logger.warning("No rows with non-empty event_type column for %s", cleaner_team)
        return _create_empty_normalized_df()

    # Exclude system entries (TURVAPC, Järvis Leonhard, etc.)
    # Check in multiple columns for system patterns
    system_patterns: list[str] = [r"TURVAPC", r"Järvis\s+Leonhard"]
    for pattern in system_patterns:
        # Check in all string columns
        for col in df.select_dtypes(include=["object"]).columns.tolist():
            mask = df[col].astype(str).str.contains(pattern, case=False, na=False, regex=True)
            df = df.loc[~mask]

    if df.empty:
        logger.warning("All rows filtered out as system entries for %s", cleaner_team)
        return _create_empty_normalized_df()

    # Parse timestamp
    if timestamp_col is not None:
        # Timestamps are provided as dd/mm/YYYY HH:MM:SS in the source files.
        df["timestamp"] = pd.to_datetime(
            df[timestamp_col],
            format="%d/%m/%Y %H:%M:%S",
            dayfirst=True,
            errors="coerce",
        )
        # Fallback for any rows that do not match the expected format
        needs_fallback = df["timestamp"].isna()
        if needs_fallback.any():
            df.loc[needs_fallback, "timestamp"] = pd.to_datetime(
                df.loc[needs_fallback, timestamp_col],
                errors="coerce",
            )
    else:
        df["timestamp"] = pd.NaT

    # Drop rows with invalid timestamps
    df = df[df["timestamp"].notna()].copy()

    if df.empty:
        logger.warning("No valid timestamps found for %s", cleaner_team)
        return _create_empty_normalized_df()

    # Sort by timestamp
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Group consecutive rows with the same timestamp into logical events
    # For each group, take the first row (or aggregate if needed)
    grouped = df.groupby("timestamp", as_index=False).first()

    # Extract fields
    events: list[dict[str, Any]] = []
    for _, row in grouped.iterrows():
        event: dict[str, Any] = {
            "timestamp": row["timestamp"],
            "date": row["timestamp"].date(),
            "time": row["timestamp"].time(),
            "cleaner_team": cleaner_team,
            "source_file": source_file,
        }

        # Person name (column AL) with fallbacks (AJ, AG, AB, AF)
        event["person_name_raw"] = None
        if person_name_col is not None and person_name_col in row.index and pd.notna(row[person_name_col]):
            event["person_name_raw"] = row[person_name_col]
        else:
            for col in person_name_fallback_cols:
                if col in row.index and pd.notna(row[col]):
                    event["person_name_raw"] = row[col]
                    break

        # Door name (column H)
        if door_name_col is not None and door_name_col in row.index:
            event["door_name_raw"] = row[door_name_col] if pd.notna(row[door_name_col]) else None
        else:
            event["door_name_raw"] = None

        # Event type (column C)
        if event_type_col is not None and event_type_col in row.index:
            event["event_type"] = row[event_type_col] if pd.notna(row[event_type_col]) else None
        else:
            event["event_type"] = None

        # Fallback: extract person name from event text if explicit columns are missing/empty
        if event["person_name_raw"] in (None, "") and event["event_type"]:
            event["person_name_raw"] = _extract_person_name_from_event_text(str(event["event_type"]))

        # Parse floor and wing from door_name_raw
        floor, wing = _parse_floor_wing(event["door_name_raw"])
        event["floor"] = floor
        event["wing"] = wing

        events.append(event)

    result_df = pd.DataFrame(events)
    logger.info("Normalized %d events for %s", len(result_df), cleaner_team)
    return result_df


def _create_empty_normalized_df() -> pd.DataFrame:
    """Create an empty DataFrame with the expected normalized schema."""
    return pd.DataFrame(
        columns=[
            "timestamp",
            "date",
            "time",
            "cleaner_team",
            "person_name_raw",
            "door_name_raw",
            "floor",
            "wing",
            "event_type",
            "source_file",
        ]
    )


def _parse_floor_wing(door_name: str | None) -> tuple[int | None, str | None]:
    """Parse floor and wing from door name.

    Expected patterns:
    - Floor: "<number> korrus" (e.g., "9 korrus")
    - Wing: "<letter>-tiib" or "<letter> tiib" (e.g., "B-tiib", "A tiib")

    Args:
        door_name: Raw door name string

    Returns:
        Tuple of (floor, wing) where floor is int or None, wing is str or None
    """
    if not door_name or not isinstance(door_name, str):
        return None, None

    floor = None
    wing = None

    # Extract floor: \d+ korrus
    floor_match = re.search(r"(\d+)\s*korrus", door_name, re.IGNORECASE)
    if floor_match:
        try:
            floor = int(floor_match.group(1))
        except ValueError:
            pass

    # Extract wing: [A-Z]-tiib or [A-Z] tiib
    wing_match = re.search(r"([A-Z])[\s-]?tiib", door_name, re.IGNORECASE)
    if wing_match:
        wing = wing_match.group(1).upper()

    return floor, wing


def _extract_person_name_from_event_text(event_text: str | None) -> str | None:
    """Extract a person name from the event description text.

    Looks for the first single-quoted substring, matching formats like
    "Access granted to 'Name' at ..." or "'Door' opened by 'Name'".
    """
    if not event_text:
        return None

    match = re.search(r"'([^']+)'", event_text)
    if match:
        return match.group(1).strip()

    return None


def build_presence_intervals(events_df: pd.DataFrame) -> pd.DataFrame:
    """Build presence intervals from normalized events.

    For each cleaner_team, sort events by timestamp. Each event creates a presence
    interval from its timestamp to the next event's timestamp, attributed to the
    event's floor+wing. Intervals are capped at calendar day boundaries.

    Args:
        events_df: Normalized events DataFrame

    Returns:
        DataFrame with columns: cleaner_team, date, start_time, end_time,
        duration_minutes, floor, wing
    """
    if events_df.empty:
        return pd.DataFrame(
            columns=["cleaner_team", "date", "start_time", "end_time", "duration_minutes", "floor", "wing"]
        )

    # Allow floor-only events. If a floor has known wings, map missing wings to the first wing seen for that floor.
    # This keeps "turnikee/garage/etc." events by assigning them to a floor's primary wing when available.
    wing_lookup = (
        events_df[events_df["wing"].notna()][["floor", "wing"]]
        .drop_duplicates()
        .sort_values(["floor", "wing"])
        .groupby("floor")["wing"]
        .first()
        .to_dict()
    )

    df = events_df[events_df["floor"].notna()].copy()
    if df.empty:
        logger.warning("No events with valid floor found")
        return pd.DataFrame(
            columns=["cleaner_team", "date", "start_time", "end_time", "duration_minutes", "floor", "wing"]
        )

    # Fill missing wings using the first wing observed for the same floor, if any.
    df["wing"] = df["wing"].fillna(df["floor"].map(wing_lookup))
    # If a floor never has a wing, keep it as empty string for clean labels.
    df["wing"] = df["wing"].fillna("")

    intervals = []

    # Process each cleaner_team separately
    for team in df["cleaner_team"].unique():
        team_events = df[df["cleaner_team"] == team].sort_values("timestamp").reset_index(drop=True)

        for i, row in team_events.iterrows():
            start_ts = row["timestamp"]
            current_date = start_ts.date()

            # End of interval: next event or end of day
            if i < len(team_events) - 1:
                end_ts = team_events.iloc[i + 1]["timestamp"]
            else:
                # Last event: extend to end of current day
                end_ts = pd.Timestamp(current_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

            # Cap at day boundary
            day_end = pd.Timestamp(current_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            end_ts = min(end_ts, day_end)

            # Handle intervals spanning midnight (split into multiple days if needed)
            current_start = start_ts
            while current_start <= end_ts:
                current_day = current_start.date()
                current_day_end = pd.Timestamp(current_day) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

                interval_end = min(end_ts, current_day_end)
                duration_minutes = (interval_end - current_start).total_seconds() / 60

                if duration_minutes > 0:
                    intervals.append({
                        "cleaner_team": team,
                        "date": current_day,
                        "start_time": current_start.time(),
                        "end_time": interval_end.time(),
                        "duration_minutes": duration_minutes,
                        "floor": row["floor"],
                        "wing": row["wing"],
                    })

                # Move to next day
                current_start = current_day_end + pd.Timedelta(seconds=1)

    result_df = pd.DataFrame(intervals)
    logger.info("Built %d presence intervals", len(result_df))
    return result_df


def aggregate_hourly_floor_wing(presence_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate presence by hour, floor, wing, and cleaner team.

    Args:
        presence_df: Presence intervals DataFrame

    Returns:
        DataFrame grouped by date, hour, floor, wing, cleaner_team with minutes_present
    """
    if presence_df.empty:
        return pd.DataFrame(columns=["date", "hour", "floor", "wing", "cleaner_team", "minutes_present"])

    # Expand intervals to hourly bins
    hourly_records = []

    for _, row in presence_df.iterrows():
        date = row["date"]
        start_time = row["start_time"]
        end_time = row["end_time"]

        # Convert times to datetime for easier manipulation
        start_dt = pd.Timestamp.combine(date, start_time)
        end_dt = pd.Timestamp.combine(date, end_time)

        # Handle end_time = 23:59:59 (end of day)
        if end_dt < start_dt:
            end_dt += pd.Timedelta(days=1)

        # Iterate over hours covered by this interval
        current_hour_start = start_dt.floor("h")
        while current_hour_start <= end_dt:
            hour_end = current_hour_start + pd.Timedelta(hours=1)

            # Calculate overlap with this hour
            overlap_start = max(start_dt, current_hour_start)
            overlap_end = min(end_dt, hour_end)

            if overlap_end > overlap_start:
                minutes_in_hour = (overlap_end - overlap_start).total_seconds() / 60

                hourly_records.append({
                    "date": date,
                    "hour": current_hour_start.hour,
                    "floor": row["floor"],
                    "wing": row["wing"],
                    "cleaner_team": row["cleaner_team"],
                    "minutes_present": minutes_in_hour,
                })

            current_hour_start = hour_end

    if not hourly_records:
        return pd.DataFrame(columns=["date", "hour", "floor", "wing", "cleaner_team", "minutes_present"])

    hourly_df = pd.DataFrame(hourly_records)
    # Group and sum in case there are overlaps (shouldn't be, but for safety)
    result = (
        hourly_df.groupby(["date", "hour", "floor", "wing", "cleaner_team"], as_index=False)
        .agg(minutes_present=("minutes_present", "sum"))
        .sort_values(by=["date", "hour", "floor", "wing", "cleaner_team"])
    )

    logger.info("Aggregated to %d hourly records", len(result))
    return result


def aggregate_daily_floor_wing(presence_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate presence by date, floor, and wing.

    Args:
        presence_df: Presence intervals DataFrame

    Returns:
        DataFrame with total_minutes_present and unique_cleaners_count per date/floor/wing
    """
    if presence_df.empty:
        return pd.DataFrame(columns=["date", "floor", "wing", "total_minutes_present", "unique_cleaners_count"])

    grouped = presence_df.groupby(["date", "floor", "wing"], as_index=False).agg(
        total_minutes_present=("duration_minutes", "sum"),
        unique_cleaners_count=("cleaner_team", "nunique"),
    )

    logger.info("Aggregated to %d daily floor/wing records", len(grouped))
    return grouped


def aggregate_per_team_floor_wing(presence_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate presence by date, cleaner_team, floor, and wing.

    Args:
        presence_df: Presence intervals DataFrame

    Returns:
        DataFrame with total_minutes_present per date/team/floor/wing
    """
    if presence_df.empty:
        return pd.DataFrame(columns=["date", "cleaner_team", "floor", "wing", "total_minutes_present"])

    grouped = presence_df.groupby(["date", "cleaner_team", "floor", "wing"], as_index=False).agg(
        total_minutes_present=("duration_minutes", "sum")
    )

    logger.info("Aggregated to %d team/floor/wing records", len(grouped))
    return grouped


def calculate_reentries(presence_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate re-entries for each date, cleaner_team, floor, and wing.

    Args:
        presence_df: Presence intervals DataFrame

    Returns:
        DataFrame with visits, re_entries, and total_minutes_present
    """
    if presence_df.empty:
        return pd.DataFrame(
            columns=["date", "cleaner_team", "floor", "wing", "visits", "re_entries", "total_minutes_present"]
        )

    # Sort by team, date, floor, wing, then start_time to identify separate visits
    df = presence_df.sort_values(["cleaner_team", "date", "floor", "wing", "start_time"]).copy()

    # Group by date, team, floor, wing and count separate intervals
    grouped = df.groupby(["date", "cleaner_team", "floor", "wing"], as_index=False).agg(
        visits=("start_time", "count"),  # Number of separate intervals
        total_minutes_present=("duration_minutes", "sum"),
    )

    # Calculate re-entries
    grouped["re_entries"] = grouped["visits"].apply(lambda x: max(x - 1, 0))

    logger.info("Calculated re-entries for %d date/team/floor/wing combinations", len(grouped))
    return grouped


def create_heatmap(hourly_agg: pd.DataFrame, output_path: Path) -> None:
    """Create a heatmap of presence by hour and floor/wing.

    Args:
        hourly_agg: Hourly aggregated DataFrame
        output_path: Path to save the PNG file
    """
    if hourly_agg.empty:
        logger.warning("No data to create heatmap")
        return

    # Sum across all teams and dates to get total minutes per hour/floor/wing
    pivot_data = hourly_agg.groupby(["hour", "floor", "wing"], as_index=False)["minutes_present"].sum().copy()

    # Create floor+wing label
    pivot_data["floor_wing"] = pivot_data["floor"].astype(str) + pivot_data["wing"].fillna("")

    # Pivot to create matrix: rows=floor_wing, cols=hour
    heatmap_matrix = pivot_data.pivot_table(
        index="floor_wing",
        columns="hour",
        values="minutes_present",
        fill_value=0,
        aggfunc="sum",
    )

    # Ensure all hours 0-23 are present
    for hour in range(24):
        if hour not in heatmap_matrix.columns:
            heatmap_matrix[hour] = 0

    heatmap_matrix = heatmap_matrix.sort_index(axis=1)

    # Create heatmap
    fig, ax = plt.subplots(figsize=(14, max(6, len(heatmap_matrix) * 0.4)))
    im = ax.imshow(heatmap_matrix.values, cmap="YlOrRd", aspect="auto")

    # Set ticks and labels
    ax.set_xticks(range(24))
    ax.set_xticklabels([str(hour) for hour in range(24)])
    ax.set_yticks(range(len(heatmap_matrix)))
    ax.set_yticklabels(heatmap_matrix.index)

    ax.set_xlabel("Hour of Day")
    ax.set_ylabel("Floor + Wing")
    ax.set_title("Total Minutes Present by Hour and Floor/Wing")

    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("Minutes Present")

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved heatmap to %s", output_path)


def create_team_comparison_charts(presence_df: pd.DataFrame, output_dir: Path) -> None:
    """Create bar charts comparing teams by floor and by day.

    Args:
        presence_df: Presence intervals DataFrame
        output_dir: Directory to save PNG files
    """
    if presence_df.empty:
        logger.warning("No data to create team comparison charts")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # Chart 1: Total minutes per floor (grouped by team)
    floor_team_data = presence_df.groupby(["floor", "cleaner_team"], as_index=False).agg(
        total_minutes=("duration_minutes", "sum")
    )

    floors = sorted(floor_team_data["floor"].unique())
    teams = sorted(floor_team_data["cleaner_team"].unique())

    fig, ax = plt.subplots(figsize=(12, 6))
    x = range(len(floors))
    width = 0.8 / len(teams)

    for i, team in enumerate(teams):
        team_data = floor_team_data[floor_team_data["cleaner_team"] == team]
        values = [
            team_data[team_data["floor"] == floor]["total_minutes"].sum() if floor in team_data["floor"].values else 0
            for floor in floors
        ]
        ax.bar([pos + i * width for pos in x], values, width, label=team)

    ax.set_xlabel("Floor")
    ax.set_ylabel("Total Minutes")
    ax.set_title("Total Minutes Present per Floor by Cleaner Team")
    ax.set_xticks([pos + width * len(teams) / 2 for pos in x])
    ax.set_xticklabels(floors)
    ax.legend()
    plt.tight_layout()

    output_path = output_dir / "team_comparison_floor.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved team comparison by floor to %s", output_path)

    # Chart 2: Total minutes per day (grouped by team)
    daily_team_data = presence_df.groupby(["date", "cleaner_team"], as_index=False).agg(
        total_minutes=("duration_minutes", "sum")
    )

    dates = sorted(daily_team_data["date"].unique())

    fig, ax = plt.subplots(figsize=(14, 6))
    x = range(len(dates))
    width = 0.8 / len(teams)

    for i, team in enumerate(teams):
        team_data = daily_team_data[daily_team_data["cleaner_team"] == team]
        values = [
            team_data[team_data["date"] == date]["total_minutes"].sum() if date in team_data["date"].values else 0
            for date in dates
        ]
        ax.bar([pos + i * width for pos in x], values, width, label=team)

    ax.set_xlabel("Date")
    ax.set_ylabel("Total Minutes")
    ax.set_title("Total Minutes Present per Day by Cleaner Team")
    ax.set_xticks([pos + width * len(teams) / 2 for pos in x])
    ax.set_xticklabels([str(d) for d in dates], rotation=45, ha="right", fontsize=8)
    ax.tick_params(axis="x", labelsize=8)
    ax.legend()
    plt.tight_layout()

    output_path = output_dir / "team_comparison_daily.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved team comparison by day to %s", output_path)


def create_floor_stacked_charts(presence_df: pd.DataFrame, output_dir: Path) -> None:
    """Create stacked bar charts for each floor showing team presence over time.

    Args:
        presence_df: Presence intervals DataFrame
        output_dir: Directory to save PNG files
    """
    if presence_df.empty:
        logger.warning("No data to create floor stacked charts")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    floors = sorted(presence_df["floor"].unique())
    teams = sorted(presence_df["cleaner_team"].unique())

    for floor in floors:
        floor_data = presence_df[presence_df["floor"] == floor]

        daily_floor_data = floor_data.groupby(["date", "cleaner_team"], as_index=False).agg(
            total_minutes=("duration_minutes", "sum")
        )

        dates = sorted(daily_floor_data["date"].unique())

        fig, ax = plt.subplots(figsize=(12, 6))

        # Create stacked bar chart
        bottom = [0] * len(dates)
        for team in teams:
            team_data = daily_floor_data[daily_floor_data["cleaner_team"] == team]
            values = [
                team_data[team_data["date"] == date]["total_minutes"].sum() if date in team_data["date"].values else 0
                for date in dates
            ]
            ax.bar(range(len(dates)), values, bottom=bottom, label=team)
            bottom = [b + v for b, v in zip(bottom, values)]

        ax.set_xlabel("Date")
        ax.set_ylabel("Total Minutes")
        ax.set_title(f"Floor {floor}: Stacked Minutes Present by Cleaner Team")
        ax.set_xticks(range(len(dates)))
        ax.set_xticklabels([str(d) for d in dates], rotation=45, ha="right")
        ax.legend()
        plt.tight_layout()

        output_path = output_dir / f"floor_{floor}_stacked.png"
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved floor %s stacked chart to %s", floor, output_path)
