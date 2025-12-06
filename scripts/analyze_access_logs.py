#!/usr/bin/env python3
"""Command-line tool to analyze access control logs.

This script processes Excel files containing access control logs, normalizes events,
builds presence models, generates aggregations, and creates visualizations.

Usage:
    .venv/bin/python scripts/analyze_access_logs.py [--input UserData] [--output UserData/results]
"""

from __future__ import annotations

import argparse
from datetime import datetime
import logging
import os
import sys
from pathlib import Path

import pandas as pd

# Import analysis functions from backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.access_control_overview_report import generate_access_control_overview
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
from backend.config import configure_logging

logger = logging.getLogger(__name__)


def save_dataframe(df: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Save DataFrame as Excel (.xlsx).

    Args:
        df: DataFrame to save
        output_dir: Output directory
        base_name: Base filename (without extension)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    xlsx_path = output_dir / f"{base_name}.xlsx"

    df.to_excel(xlsx_path, index=False, engine="openpyxl")

    logger.info("Saved %s (%d rows) to Excel (.xlsx)", base_name, len(df))


def update_latest_symlink(output_base: Path, run_dir: Path) -> None:
    """Point UserData/Latest to the newest run directory."""
    latest_link = output_base.parent / "Latest"
    target_rel = Path(os.path.relpath(run_dir, latest_link.parent))

    if latest_link.exists() or latest_link.is_symlink():
        if latest_link.is_symlink() or latest_link.is_file():
            latest_link.unlink()
        elif latest_link.is_dir():
            logger.warning("Latest path exists as a directory; leaving untouched: %s", latest_link)
            return

    latest_link.symlink_to(target_rel)
    logger.info("Updated Latest symlink: %s -> %s", latest_link, target_rel)


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
    configure_logging(level=log_level)

    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir = args.output / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 80)
    logger.info("Access Control Log Analysis Pipeline")
    logger.info("=" * 80)
    logger.info("Input folder: %s", args.input)
    logger.info("Output base: %s", args.output)
    logger.info("Run folder: %s", run_dir)
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

        save_dataframe(normalized_events_df, run_dir, "normalized_events")
        logger.info("")

        # Step 3: Build presence intervals
        logger.info("Step 3: Building presence intervals...")
        presence_intervals_df = build_presence_intervals(normalized_events_df)
        logger.info("Total presence intervals: %d", len(presence_intervals_df))

        if presence_intervals_df.empty:
            logger.error("No presence intervals generated. Exiting.")
            return 1

        save_dataframe(presence_intervals_df, run_dir, "presence_intervals")
        logger.info("")

        # Step 4: Generate aggregations
        logger.info("Step 4: Generating aggregations...")

        logger.info("  Hourly by floor/wing/team...")
        hourly_agg = aggregate_hourly_floor_wing(presence_intervals_df)
        save_dataframe(hourly_agg, run_dir, "hourly_floor_wing")

        logger.info("  Daily by floor/wing...")
        daily_agg = aggregate_daily_floor_wing(presence_intervals_df)
        save_dataframe(daily_agg, run_dir, "daily_floor_wing")

        logger.info("  Per team/floor/wing...")
        team_agg = aggregate_per_team_floor_wing(presence_intervals_df)
        save_dataframe(team_agg, run_dir, "team_floor_wing")

        logger.info("  Calculating re-entries...")
        reentries_df = calculate_reentries(presence_intervals_df)
        save_dataframe(reentries_df, run_dir, "reentries")
        logger.info("")

        # Step 5: Generate visualizations
        logger.info("Step 5: Generating visualizations...")
        plots_dir = run_dir

        if not hourly_agg.empty:
            logger.info("  Creating heatmap...")
            create_heatmap(hourly_agg, plots_dir / "heatmap_hourly.png")

        if not presence_intervals_df.empty:
            logger.info("  Creating team comparison charts...")
            create_team_comparison_charts(presence_intervals_df, plots_dir)

            logger.info("  Creating floor stacked charts...")
            create_floor_stacked_charts(presence_intervals_df, plots_dir)

        logger.info("")

        # Step 6: Build Ops Snapshot (HTML + PDF)
        logger.info("Step 6: Building Ops Snapshot (HTML + PDF)...")
        reports_dir = run_dir
        generate_access_control_overview(
            normalized_events_df=normalized_events_df,
            presence_intervals_df=presence_intervals_df,
            hourly_agg=hourly_agg,
            daily_agg=daily_agg,
            reentries_df=reentries_df,
            plots_dir=plots_dir,
            reports_dir=reports_dir,
            input_dir=args.input,
            output_dir=run_dir,
        )
        logger.info("")

        # Step 7: Summary statistics
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
        logger.info("All outputs saved to: %s", run_dir)
        logger.info("=" * 80)

        update_latest_symlink(args.output, run_dir)

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
