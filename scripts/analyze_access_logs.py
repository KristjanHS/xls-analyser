#!/usr/bin/env python3
"""Command-line tool to analyze access control logs.

This script processes Excel files containing access control logs, normalizes events,
builds presence models, generates aggregations, and creates visualizations.

Usage:
    .venv/bin/python scripts/analyze_access_logs.py [--input UserData] [--output UserData/results]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

# Import analysis functions from backend
sys.path.insert(0, str(Path(__file__).parent.parent))

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
from backend.config import setup_logging

logger = logging.getLogger(__name__)


def save_dataframe(df: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Save DataFrame as both CSV and Excel.

    Args:
        df: DataFrame to save
        output_dir: Output directory
        base_name: Base filename (without extension)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / f"{base_name}.csv"
    xlsx_path = output_dir / f"{base_name}.xlsx"

    df.to_csv(csv_path, index=False)
    df.to_excel(xlsx_path, index=False, engine="openpyxl")

    logger.info("Saved %s (%d rows) to CSV and Excel", base_name, len(df))


def main() -> int:
    """Main entry point for the access log analysis pipeline.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    parser = argparse.ArgumentParser(
        description="Analyze access control logs from Excel files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("UserData"),
        help="Input folder containing Excel files (default: UserData)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("UserData/results"),
        help="Output folder for results (default: UserData/results)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=log_level)

    logger.info("=" * 80)
    logger.info("Access Control Log Analysis Pipeline")
    logger.info("=" * 80)
    logger.info("Input folder: %s", args.input)
    logger.info("Output folder: %s", args.output)
    logger.info("")

    try:
        # Step 1: Load Excel files
        logger.info("Step 1: Loading Excel files...")
        excel_data = load_excel_files(args.input)
        logger.info("Loaded %d file(s)", len(excel_data))
        logger.info("")

        # Step 2: Normalize events
        logger.info("Step 2: Normalizing events...")
        all_events = []
        for filename, raw_df in excel_data.items():
            logger.info("  Processing %s...", filename)
            normalized = normalize_events(raw_df, cleaner_team=filename, source_file=f"{filename}.xlsx")
            all_events.append(normalized)

        normalized_events_df = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()
        logger.info("Total normalized events: %d", len(normalized_events_df))

        if normalized_events_df.empty:
            logger.error("No events to process. Exiting.")
            return 1

        save_dataframe(normalized_events_df, args.output, "normalized_events")
        logger.info("")

        # Step 3: Build presence intervals
        logger.info("Step 3: Building presence intervals...")
        presence_intervals_df = build_presence_intervals(normalized_events_df)
        logger.info("Total presence intervals: %d", len(presence_intervals_df))

        if presence_intervals_df.empty:
            logger.error("No presence intervals generated. Exiting.")
            return 1

        save_dataframe(presence_intervals_df, args.output, "presence_intervals")
        logger.info("")

        # Step 4: Generate aggregations
        logger.info("Step 4: Generating aggregations...")

        logger.info("  Hourly by floor/wing/team...")
        hourly_agg = aggregate_hourly_floor_wing(presence_intervals_df)
        save_dataframe(hourly_agg, args.output, "hourly_floor_wing")

        logger.info("  Daily by floor/wing...")
        daily_agg = aggregate_daily_floor_wing(presence_intervals_df)
        save_dataframe(daily_agg, args.output, "daily_floor_wing")

        logger.info("  Per team/floor/wing...")
        team_agg = aggregate_per_team_floor_wing(presence_intervals_df)
        save_dataframe(team_agg, args.output, "team_floor_wing")

        logger.info("  Calculating re-entries...")
        reentries_df = calculate_reentries(presence_intervals_df)
        save_dataframe(reentries_df, args.output, "reentries")
        logger.info("")

        # Step 5: Generate visualizations
        logger.info("Step 5: Generating visualizations...")
        plots_dir = args.output / "plots"

        if not hourly_agg.empty:
            logger.info("  Creating heatmap...")
            create_heatmap(hourly_agg, plots_dir / "heatmap_hourly.png")

        if not presence_intervals_df.empty:
            logger.info("  Creating team comparison charts...")
            create_team_comparison_charts(presence_intervals_df, plots_dir)

            logger.info("  Creating floor stacked charts...")
            create_floor_stacked_charts(presence_intervals_df, plots_dir)

        logger.info("")

        # Step 6: Summary statistics
        logger.info("=" * 80)
        logger.info("Summary Statistics")
        logger.info("=" * 80)
        logger.info("Total events: %d", len(normalized_events_df))
        logger.info("Total presence intervals: %d", len(presence_intervals_df))
        logger.info("Date range: %s to %s", normalized_events_df["date"].min(), normalized_events_df["date"].max())
        logger.info("Cleaner teams: %s", ", ".join(sorted(normalized_events_df["cleaner_team"].unique())))
        logger.info("Floors: %s", ", ".join(map(str, sorted(normalized_events_df["floor"].dropna().unique()))))
        logger.info("Total minutes tracked: %.2f", presence_intervals_df["duration_minutes"].sum())
        logger.info("")
        logger.info("All outputs saved to: %s", args.output)
        logger.info("=" * 80)

        return 0

    except FileNotFoundError as e:
        logger.error("File not found: %s", e)
        return 1
    except ValueError as e:
        logger.error("Value error: %s", e)
        return 1
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
