"""Unit tests for access control analysis module."""

from __future__ import annotations

import logging
from datetime import date, time

import pandas as pd

from backend.access_control_analysis import (
    _parse_floor_wing,
    aggregate_daily_floor_wing,
    aggregate_hourly_floor_wing,
    aggregate_per_team_floor_wing,
    build_presence_intervals,
    calculate_reentries,
    normalize_events,
)

logger = logging.getLogger(__name__)


class TestParseFloorWing:
    """Test floor and wing parsing from door names."""

    def test_parse_valid_floor_wing(self) -> None:
        """Test parsing valid floor and wing patterns."""
        floor, wing = _parse_floor_wing("9 korrus B-tiib Main Door")
        assert floor == 9
        assert wing == "B"

    def test_parse_floor_only(self) -> None:
        """Test parsing when only floor is present."""
        floor, wing = _parse_floor_wing("10 korrus Main Entrance")
        assert floor == 10
        assert wing is None

    def test_parse_wing_only(self) -> None:
        """Test parsing when only wing is present."""
        floor, wing = _parse_floor_wing("A-tiib Side Door")
        assert floor is None
        assert wing == "A"

    def test_parse_no_pattern(self) -> None:
        """Test parsing when no patterns match."""
        floor, wing = _parse_floor_wing("Random Door Name")
        assert floor is None
        assert wing is None

    def test_parse_none_input(self) -> None:
        """Test parsing with None input."""
        floor, wing = _parse_floor_wing(None)
        assert floor is None
        assert wing is None

    def test_parse_case_insensitive(self) -> None:
        """Test parsing is case-insensitive."""
        floor, wing = _parse_floor_wing("8 KORRUS C-TIIB")
        assert floor == 8
        assert wing == "C"

    def test_parse_wing_with_space(self) -> None:
        """Test parsing wing with space instead of hyphen."""
        floor, wing = _parse_floor_wing("9 korrus A tiib")
        assert floor == 9
        assert wing == "A"


class TestNormalizeEvents:
    """Test event normalization."""

    def test_normalize_empty_dataframe(self) -> None:
        """Test normalizing an empty DataFrame."""
        df = pd.DataFrame()
        result = normalize_events(df, "test_team", "test.xlsx")
        assert result.empty
        expected_columns = [
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
        assert list(result.columns) == expected_columns

    def test_normalize_filters_system_entries(self) -> None:
        """Test that system entries are filtered out."""
        # Create a DataFrame with system entries (need 38 columns for AL)
        # Create sparse data with only the columns we need
        data = {}
        for i in range(38):
            if i == 0:  # Column A (timestamp)
                data[i] = ["2024-01-01 10:00:00", "2024-01-01 11:00:00"]
            elif i == 2:  # Column C (event_type)
                data[i] = ["Granted", "Granted"]
            elif i == 7:  # Column H (door_name)
                data[i] = ["9 korrus B-tiib", "10 korrus A-tiib"]
            elif i == 37:  # Column AL (person_name)
                data[i] = ["TURVAPC6K2 System", "John Doe"]
            else:
                data[i] = [None, None]

        df = pd.DataFrame(data)

        result = normalize_events(df, "test_team", "test.xlsx")

        # Should filter out the TURVAPC entry
        assert len(result) == 1
        assert result.iloc[0]["person_name_raw"] == "John Doe"

    def test_normalize_groups_by_timestamp(self) -> None:
        """Test that consecutive rows with same timestamp are grouped."""
        # Create sparse data with 38 columns
        data = {}
        for i in range(38):
            if i == 0:  # Column A (timestamp)
                data[i] = ["2024-01-01 10:00:00", "2024-01-01 10:00:00", "2024-01-01 11:00:00"]
            elif i == 2:  # Column C (event_type)
                data[i] = ["Granted", "Granted", "Denied"]
            elif i == 7:  # Column H (door_name)
                data[i] = ["9 korrus B-tiib", "9 korrus B-tiib", "10 korrus A-tiib"]
            elif i == 37:  # Column AL (person_name)
                data[i] = ["Person A", "Person B", "Person C"]
            else:
                data[i] = [None, None, None]

        df = pd.DataFrame(data)

        result = normalize_events(df, "test_team", "test.xlsx")

        # Should have 2 events (grouped by timestamp)
        assert len(result) == 2

    def test_normalize_parses_floor_wing(self) -> None:
        """Test that floor and wing are correctly parsed."""
        # Create sparse data with 38 columns
        data = {}
        for i in range(38):
            if i == 0:  # Column A (timestamp)
                data[i] = ["2024-01-01 10:00:00"]
            elif i == 2:  # Column C (event_type)
                data[i] = ["Granted"]
            elif i == 7:  # Column H (door_name)
                data[i] = ["9 korrus B-tiib Main Door"]
            elif i == 37:  # Column AL (person_name)
                data[i] = ["Person A"]
            else:
                data[i] = [None]

        df = pd.DataFrame(data)

        result = normalize_events(df, "test_team", "test.xlsx")

        assert len(result) == 1
        assert result.iloc[0]["floor"] == 9
        assert result.iloc[0]["wing"] == "B"
        assert result.iloc[0]["cleaner_team"] == "test_team"
        assert result.iloc[0]["source_file"] == "test.xlsx"


class TestBuildPresenceIntervals:
    """Test presence interval building."""

    def test_build_empty_events(self) -> None:
        """Test building intervals from empty events."""
        # Create empty DataFrame with expected schema
        empty_data: dict[str, list[str]] = {
            "timestamp": [],
            "date": [],
            "time": [],
            "cleaner_team": [],
            "person_name_raw": [],
            "door_name_raw": [],
            "floor": [],
            "wing": [],
            "event_type": [],
            "source_file": [],
        }
        df = pd.DataFrame(empty_data)
        result = build_presence_intervals(df)
        assert result.empty

    def test_build_single_event(self) -> None:
        """Test building interval from a single event."""
        events = pd.DataFrame([
            {
                "timestamp": pd.Timestamp("2024-01-01 10:00:00"),
                "date": date(2024, 1, 1),
                "time": time(10, 0, 0),
                "cleaner_team": "team_a",
                "floor": 9,
                "wing": "B",
            }
        ])

        result = build_presence_intervals(events)

        assert len(result) == 1
        assert result.iloc[0]["cleaner_team"] == "team_a"
        assert result.iloc[0]["floor"] == 9
        assert result.iloc[0]["wing"] == "B"
        # Should extend to end of day
        assert result.iloc[0]["duration_minutes"] > 0

    def test_build_multiple_events_same_team(self) -> None:
        """Test building intervals from multiple events for same team."""
        events = pd.DataFrame([
            {
                "timestamp": pd.Timestamp("2024-01-01 10:00:00"),
                "date": date(2024, 1, 1),
                "time": time(10, 0, 0),
                "cleaner_team": "team_a",
                "floor": 9,
                "wing": "B",
            },
            {
                "timestamp": pd.Timestamp("2024-01-01 11:00:00"),
                "date": date(2024, 1, 1),
                "time": time(11, 0, 0),
                "cleaner_team": "team_a",
                "floor": 10,
                "wing": "A",
            },
        ])

        result = build_presence_intervals(events)

        assert len(result) == 2
        # First interval: 10:00 to 11:00 (60 minutes)
        assert result.iloc[0]["duration_minutes"] == 60
        assert result.iloc[0]["floor"] == 9
        # Second interval: 11:00 to end of day
        assert result.iloc[1]["floor"] == 10

    def test_build_caps_at_day_boundary(self) -> None:
        """Test that intervals are capped at day boundaries."""
        events = pd.DataFrame([
            {
                "timestamp": pd.Timestamp("2024-01-01 23:00:00"),
                "date": date(2024, 1, 1),
                "time": time(23, 0, 0),
                "cleaner_team": "team_a",
                "floor": 9,
                "wing": "B",
            }
        ])

        result = build_presence_intervals(events)

        # Should cap at 23:59:59
        assert len(result) == 1
        # 23:00 to 23:59:59 is approximately 60 minutes
        assert 59 < result.iloc[0]["duration_minutes"] <= 60


class TestCalculateReentries:
    """Test re-entry calculation."""

    def test_calculate_no_reentries(self) -> None:
        """Test when there are no re-entries (single visit per location)."""
        presence = pd.DataFrame([
            {
                "cleaner_team": "team_a",
                "date": date(2024, 1, 1),
                "start_time": time(10, 0),
                "end_time": time(11, 0),
                "duration_minutes": 60,
                "floor": 9,
                "wing": "B",
            }
        ])

        result = calculate_reentries(presence)

        assert len(result) == 1
        assert result.iloc[0]["visits"] == 1
        assert result.iloc[0]["re_entries"] == 0
        assert result.iloc[0]["total_minutes_present"] == 60

    def test_calculate_with_reentries(self) -> None:
        """Test when there are multiple visits (re-entries) to same location."""
        presence = pd.DataFrame([
            {
                "cleaner_team": "team_a",
                "date": date(2024, 1, 1),
                "start_time": time(10, 0),
                "end_time": time(11, 0),
                "duration_minutes": 60,
                "floor": 9,
                "wing": "B",
            },
            {
                "cleaner_team": "team_a",
                "date": date(2024, 1, 1),
                "start_time": time(14, 0),
                "end_time": time(15, 0),
                "duration_minutes": 60,
                "floor": 9,
                "wing": "B",
            },
        ])

        result = calculate_reentries(presence)

        assert len(result) == 1
        assert result.iloc[0]["visits"] == 2
        assert result.iloc[0]["re_entries"] == 1
        assert result.iloc[0]["total_minutes_present"] == 120


class TestAggregations:
    """Test aggregation functions."""

    def test_aggregate_hourly(self) -> None:
        """Test hourly aggregation."""
        presence = pd.DataFrame([
            {
                "cleaner_team": "team_a",
                "date": date(2024, 1, 1),
                "start_time": time(10, 0),
                "end_time": time(11, 30),
                "duration_minutes": 90,
                "floor": 9,
                "wing": "B",
            }
        ])

        result = aggregate_hourly_floor_wing(presence)

        # Should have entries for hours 10 and 11
        assert len(result) >= 2
        hour_values = result["hour"].values.tolist()  # type: ignore[union-attr]
        assert 10 in hour_values
        assert 11 in hour_values

    def test_aggregate_daily(self) -> None:
        """Test daily aggregation."""
        presence = pd.DataFrame([
            {
                "cleaner_team": "team_a",
                "date": date(2024, 1, 1),
                "start_time": time(10, 0),
                "end_time": time(11, 0),
                "duration_minutes": 60,
                "floor": 9,
                "wing": "B",
            },
            {
                "cleaner_team": "team_b",
                "date": date(2024, 1, 1),
                "start_time": time(14, 0),
                "end_time": time(15, 0),
                "duration_minutes": 60,
                "floor": 9,
                "wing": "B",
            },
        ])

        result = aggregate_daily_floor_wing(presence)

        assert len(result) == 1
        assert result.iloc[0]["total_minutes_present"] == 120
        assert result.iloc[0]["unique_cleaners_count"] == 2

    def test_aggregate_per_team(self) -> None:
        """Test per-team aggregation."""
        presence = pd.DataFrame([
            {
                "cleaner_team": "team_a",
                "date": date(2024, 1, 1),
                "start_time": time(10, 0),
                "end_time": time(11, 0),
                "duration_minutes": 60,
                "floor": 9,
                "wing": "B",
            },
            {
                "cleaner_team": "team_a",
                "date": date(2024, 1, 1),
                "start_time": time(14, 0),
                "end_time": time(15, 0),
                "duration_minutes": 60,
                "floor": 9,
                "wing": "B",
            },
        ])

        result = aggregate_per_team_floor_wing(presence)

        assert len(result) == 1
        assert result.iloc[0]["cleaner_team"] == "team_a"
        assert result.iloc[0]["total_minutes_present"] == 120
