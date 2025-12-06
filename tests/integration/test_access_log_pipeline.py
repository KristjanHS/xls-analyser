"""Integration tests for the access log analysis pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from backend.access_control_analysis import (
    aggregate_daily_floor_wing,
    aggregate_hourly_floor_wing,
    aggregate_per_team_floor_wing,
    build_presence_intervals,
    calculate_reentries,
    create_floor_stacked_charts,
    create_heatmap,
    create_team_comparison_charts,
    load_excel_files,
    normalize_events,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def temp_excel_files(tmp_path: Path) -> Path:
    """Create temporary Excel files with sample access log data.

    Args:
        tmp_path: Pytest temporary directory fixture

    Returns:
        Path to directory containing test Excel files
    """
    test_dir = tmp_path / "test_data"
    test_dir.mkdir()

    # Create sample data for two teams
    sample_data = {
        "team_alpha": [
            # Row with timestamp, event_type, door_name, person_name
            # Columns: A(0), C(2), H(7), AL(37)
            {
                0: "2024-01-01 09:00:00",
                2: "Granted",
                7: "9 korrus B-tiib Main Entry",
                37: "Anna Smith",
            },
            {
                0: "2024-01-01 10:30:00",
                2: "Granted",
                7: "10 korrus A-tiib Side Door",
                37: "Anna Smith",
            },
            {
                0: "2024-01-01 14:00:00",
                2: "Granted",
                7: "9 korrus B-tiib Main Entry",
                37: "Anna Smith",
            },
            # System entry to filter out
            {
                0: "2024-01-01 15:00:00",
                2: "System",
                7: "System Door",
                37: "TURVAPC6K2",
            },
        ],
        "team_beta": [
            {
                0: "2024-01-01 08:00:00",
                2: "Granted",
                7: "9 korrus C-tiib Rear Entry",
                37: "Bob Jones",
            },
            {
                0: "2024-01-01 11:00:00",
                2: "Denied",
                7: "10 korrus B-tiib Front Door",
                37: "Bob Jones",
            },
        ],
    }

    for team_name, rows in sample_data.items():
        wb = Workbook()
        ws = wb.active
        if ws is None:  # type: ignore[unnecessary-compare]
            msg = "Failed to get active worksheet"
            raise RuntimeError(msg)

        # Write data rows
        for row_idx, row_data in enumerate(rows, start=1):
            for col_idx, value in row_data.items():
                ws.cell(row=row_idx, column=col_idx + 1, value=value)

        file_path = test_dir / f"{team_name}.xlsx"
        wb.save(file_path)
        logger.info("Created test file: %s", file_path)

    return test_dir


def test_full_pipeline(temp_excel_files: Path, tmp_path: Path) -> None:
    """Test the complete analysis pipeline from Excel to outputs.

    Args:
        temp_excel_files: Fixture providing test Excel files
        tmp_path: Pytest temporary directory
    """
    output_dir = tmp_path / "results"

    # Step 1: Load Excel files
    excel_data = load_excel_files(temp_excel_files)
    assert len(excel_data) == 2
    assert "team_alpha" in excel_data
    assert "team_beta" in excel_data

    # Step 2: Normalize events
    all_events = []
    for filename, raw_df in excel_data.items():
        normalized = normalize_events(raw_df, cleaner_team=filename, source_file=f"{filename}.xlsx")
        all_events.append(normalized)

    normalized_events_df = pd.concat(all_events, ignore_index=True)

    # Should have 5 valid events (1 system entry filtered out)
    assert len(normalized_events_df) == 5
    assert "team_alpha" in normalized_events_df["cleaner_team"].values
    assert "team_beta" in normalized_events_df["cleaner_team"].values

    # Verify floor/wing parsing
    assert 9 in normalized_events_df["floor"].values
    assert 10 in normalized_events_df["floor"].values
    assert "B" in normalized_events_df["wing"].values

    # Step 3: Build presence intervals
    presence_intervals_df = build_presence_intervals(normalized_events_df)
    assert len(presence_intervals_df) > 0
    assert "duration_minutes" in presence_intervals_df.columns

    # Step 4: Aggregations
    hourly_agg = aggregate_hourly_floor_wing(presence_intervals_df)
    assert len(hourly_agg) > 0
    assert "minutes_present" in hourly_agg.columns

    daily_agg = aggregate_daily_floor_wing(presence_intervals_df)
    assert len(daily_agg) > 0
    assert "total_minutes_present" in daily_agg.columns
    assert "unique_cleaners_count" in daily_agg.columns

    team_agg = aggregate_per_team_floor_wing(presence_intervals_df)
    assert len(team_agg) > 0

    # Step 5: Re-entries
    reentries_df = calculate_reentries(presence_intervals_df)
    assert len(reentries_df) > 0
    assert "visits" in reentries_df.columns
    assert "re_entries" in reentries_df.columns

    # Verify team_alpha has re-entry to floor 9, wing B
    alpha_reentries = reentries_df[
        (reentries_df["cleaner_team"] == "team_alpha") & (reentries_df["floor"] == 9) & (reentries_df["wing"] == "B")
    ]
    assert len(alpha_reentries) > 0
    assert alpha_reentries.iloc[0]["visits"] >= 2
    assert alpha_reentries.iloc[0]["re_entries"] >= 1

    # Step 6: Save outputs
    output_dir.mkdir(parents=True, exist_ok=True)

    normalized_events_df.to_csv(output_dir / "normalized_events.csv", index=False)
    presence_intervals_df.to_csv(output_dir / "presence_intervals.csv", index=False)
    hourly_agg.to_csv(output_dir / "hourly_floor_wing.csv", index=False)
    daily_agg.to_csv(output_dir / "daily_floor_wing.csv", index=False)
    team_agg.to_csv(output_dir / "team_floor_wing.csv", index=False)
    reentries_df.to_csv(output_dir / "reentries.csv", index=False)

    # Verify files exist
    assert (output_dir / "normalized_events.csv").exists()
    assert (output_dir / "presence_intervals.csv").exists()
    assert (output_dir / "hourly_floor_wing.csv").exists()

    # Step 7: Create visualizations
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    create_heatmap(hourly_agg, plots_dir / "heatmap_hourly.png")
    assert (plots_dir / "heatmap_hourly.png").exists()

    create_team_comparison_charts(presence_intervals_df, plots_dir)
    assert (plots_dir / "team_comparison_floor.png").exists()
    assert (plots_dir / "team_comparison_daily.png").exists()

    create_floor_stacked_charts(presence_intervals_df, plots_dir)
    # Should have stacked charts for floors 9 and 10
    assert (plots_dir / "floor_9_stacked.png").exists()
    assert (plots_dir / "floor_10_stacked.png").exists()


def test_load_excel_files_nonexistent_folder() -> None:
    """Test loading from a non-existent folder raises error."""
    with pytest.raises(FileNotFoundError):
        load_excel_files(Path("/nonexistent/folder"))


def test_load_excel_files_empty_folder(tmp_path: Path) -> None:
    """Test loading from an empty folder raises error."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with pytest.raises(ValueError, match="No Excel files found"):
        load_excel_files(empty_dir)
