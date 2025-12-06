# Access Control Log Analysis - Implementation Plan & Progress

## Project Overview

Transform 8 Excel files from `UserData/` containing access control logs for cleaning staff into:
- Normalized event data
- Presence interval models
- Multiple aggregations
- Re-entry analysis
- Visualizations (heatmaps, bar charts)

All outputs saved to `UserData/results/`

---

## Progress Summary

### ✅ Completed Tasks

1. **Dependencies Added** - `pandas`, `openpyxl`, `matplotlib` added to `pyproject.toml`
2. **Core Analysis Module** - `backend/access_control_analysis.py` (635 lines)
3. **CLI Orchestration Script** - `scripts/analyze_access_logs.py` (204 lines)
4. **Unit Tests** - `tests/unit/test_access_control_analysis.py` (414 lines, 20 tests - all passing ✅)
5. **Integration Tests** - `tests/integration/test_access_log_pipeline.py` (217 lines)
6. **Integration Tests Executed** - `tests/integration/test_access_log_pipeline.py` passing (2025-12-06)

### ⏳ In Progress

7. **Execute on Real Data** - Run on actual 8 Excel files in UserData/

---

## Architecture Details

### 1. Data Model

#### Column Mapping (Excel → Processing)
- **Column A (index 0)**: Timestamp
- **Column C (index 2)**: Event type (granted/denied/alarm)
- **Column H (index 7)**: Door name (contains floor/wing info)
- **Column AL (index 37)**: Person name

#### Data Rules
- **Valid events**: Column C is non-empty
- **System entries to exclude**: Rows containing `TURVAPC`, `Järvis Leonhard`
- **Logical event**: Consecutive rows with same timestamp = 1 event (grouped)
- **Floor extraction**: Parse `<number> korrus` from door name
- **Wing extraction**: Parse `[A-Z]-tiib` or `[A-Z] tiib` from door name

---

### 2. Core Functions (backend/access_control_analysis.py)

#### 2.1 Data Loading & Parsing

**`load_excel_files(folder_path: Path) -> dict[str, pd.DataFrame]`**
- Reads all `.xlsx` files from specified folder
- Returns: `{filename_stem: raw_dataframe}`
- Status: ✅ Implemented & Tested

**`normalize_events(raw_df, cleaner_team, source_file) -> pd.DataFrame`**
- Filters column C non-empty
- Excludes system entries (TURVAPC, etc.)
- Groups by timestamp
- Extracts & parses all fields
- Returns normalized DataFrame with columns:
  - `timestamp`, `date`, `time`
  - `cleaner_team`, `person_name_raw`
  - `door_name_raw`, `floor`, `wing`
  - `event_type`, `source_file`
- Status: ✅ Implemented & Tested (7 unit tests)

#### 2.2 Presence Model

**`build_presence_intervals(events_df) -> pd.DataFrame`**
- For each cleaner_team, sorts events by timestamp
- Creates presence interval: `[event_time, next_event_time)`
- Attributes interval to event's floor+wing
- Caps at calendar day boundaries (00:00–23:59:59)
- Handles multi-day intervals (splits across days)
- Returns: `cleaner_team`, `date`, `start_time`, `end_time`, `duration_minutes`, `floor`, `wing`
- Status: ✅ Implemented & Tested (4 unit tests)

#### 2.3 Aggregations

**`aggregate_hourly_floor_wing(presence_df) -> pd.DataFrame`**
- Groups by: `date`, `hour`, `floor`, `wing`, `cleaner_team`
- Expands intervals to hourly bins
- Returns: `minutes_present` per group
- Status: ✅ Implemented & Tested

**`aggregate_daily_floor_wing(presence_df) -> pd.DataFrame`**
- Groups by: `date`, `floor`, `wing`
- Returns: `total_minutes_present`, `unique_cleaners_count`
- Status: ✅ Implemented & Tested

**`aggregate_per_team_floor_wing(presence_df) -> pd.DataFrame`**
- Groups by: `date`, `cleaner_team`, `floor`, `wing`
- Returns: `total_minutes_present`
- Status: ✅ Implemented & Tested

#### 2.4 Re-entry Analysis

**`calculate_reentries(presence_df) -> pd.DataFrame`**
- Groups by: `date`, `cleaner_team`, `floor`, `wing`
- Counts separate intervals = `visits`
- Computes: `re_entries = max(visits - 1, 0)`
- Returns: `date`, `cleaner_team`, `floor`, `wing`, `visits`, `re_entries`, `total_minutes_present`
- Status: ✅ Implemented & Tested (2 unit tests)

#### 2.5 Visualizations

**`create_heatmap(hourly_agg, output_path)`**
- X-axis: Hours 0–23
- Y-axis: Floor+wing combinations (e.g., "9B", "10A")
- Cell value: Total minutes present (all cleaners)
- Saves: PNG file
- Status: ✅ Implemented

**`create_team_comparison_charts(presence_df, output_dir)`**
- Chart 1: Total minutes per floor (grouped by team)
- Chart 2: Total minutes per day (grouped by team)
- Saves: 2 PNG files
- Status: ✅ Implemented

**`create_floor_stacked_charts(presence_df, output_dir)`**
- One stacked bar chart per floor
- Shows team presence over time
- Saves: Multiple PNGs (one per floor)
- Status: ✅ Implemented

---

### 3. CLI Tool (scripts/analyze_access_logs.py)

**Command:**
```bash
.venv/bin/python scripts/analyze_access_logs.py [--input UserData] [--output UserData/results] [-v]
```

**Pipeline Steps:**
1. Load all Excel files from input folder
2. Normalize events → save `normalized_events.xlsx`
3. Build presence intervals → save `presence_intervals.xlsx`
4. Generate aggregations → save:
   - `hourly_floor_wing.xlsx`
   - `daily_floor_wing.xlsx`
   - `team_floor_wing.xlsx`
   - `reentries.xlsx`
5. Generate visualizations → save to `plots/`:
   - `heatmap_hourly.png`
   - `team_comparison_floor.png`
   - `team_comparison_daily.png`
   - `floor_*_stacked.png` (one per floor)
6. Log summary statistics

**Status:** ✅ Implemented

---

### 4. Testing

#### Unit Tests (tests/unit/test_access_control_analysis.py)

**Test Classes & Results:**
- `TestParseFloorWing`: 7 tests ✅
  - Valid patterns, floor only, wing only
  - No pattern, None input
  - Case insensitive, space handling
  
- `TestNormalizeEvents`: 4 tests ✅
  - Empty dataframe handling
  - System entry filtering
  - Timestamp grouping
  - Floor/wing parsing
  
- `TestBuildPresenceIntervals`: 4 tests ✅
  - Empty events, single event
  - Multiple events, day boundary capping
  
- `TestCalculateReentries`: 2 tests ✅
  - No re-entries, with re-entries
  
- `TestAggregations`: 3 tests ✅
  - Hourly, daily, per-team aggregations

**Total: 20/20 tests passing ✅**

**Coverage:** 51% of `backend/access_control_analysis.py`
- Core logic: ✅ Covered
- Visualization functions: ⚠️ Not unit-tested (covered by integration tests)

#### Integration Tests (tests/integration/test_access_log_pipeline.py)

**Tests:**
- `test_full_pipeline`: End-to-end test with synthetic Excel data
  - Creates 2 test teams with realistic data
  - Verifies all pipeline steps
  - Checks output files exist
  - Validates re-entry calculations
  
- `test_load_excel_files_nonexistent_folder`: Error handling
- `test_load_excel_files_empty_folder`: Error handling

**Status:** ✅ Implemented, ⏳ Awaiting execution

---

### 5. Expected Output Structure

```
UserData/results/
├── normalized_events.xlsx         # All events from 8 files
├── presence_intervals.xlsx        # Computed presence intervals
├── hourly_floor_wing.xlsx         # Aggregation: hour × floor × wing × team
├── daily_floor_wing.xlsx          # Aggregation: date × floor × wing
├── team_floor_wing.xlsx           # Aggregation: date × team × floor × wing
├── reentries.xlsx                 # Re-entry analysis
└── plots/
    ├── heatmap_hourly.png         # Heatmap: hours vs floors/wings
    ├── team_comparison_floor.png  # Bar chart: teams × floors
    ├── team_comparison_daily.png  # Bar chart: teams × dates
    ├── floor_9_stacked.png        # Stacked chart for floor 9
    ├── floor_10_stacked.png       # Stacked chart for floor 10
    └── ... (one per floor found in data)
```

---

## Implementation Checklist

- [x] **Step 1:** Add dependencies to `pyproject.toml`
  - [x] pandas>=2.2.0,<3.0.0
  - [x] openpyxl>=3.1.0,<4.0.0
  - [x] matplotlib>=3.8.0,<4.0.0

- [x] **Step 2:** Create `backend/access_control_analysis.py`
  - [x] Data loading functions
  - [x] Normalization with regex parsing
  - [x] Presence interval builder
  - [x] All aggregation functions
  - [x] Re-entry calculator
  - [x] All visualization functions

- [x] **Step 3:** Create `scripts/analyze_access_logs.py`
  - [x] CLI argument parsing
  - [x] Pipeline orchestration
  - [x] Output saving (CSV + Excel)
  - [x] Summary statistics logging

- [x] **Step 4:** Create `tests/unit/test_access_control_analysis.py`
  - [x] Parser tests (7 tests)
  - [x] Normalization tests (4 tests)
  - [x] Presence interval tests (4 tests)
  - [x] Re-entry tests (2 tests)
  - [x] Aggregation tests (3 tests)

- [x] **Step 5:** Create `tests/integration/test_access_log_pipeline.py`
  - [x] Full pipeline test with fixtures
  - [x] Error handling tests

- [x] **Step 6:** Run integration tests
  ```bash
  .venv/bin/python -m pytest tests/integration/test_access_log_pipeline.py -v
  ```

- [ ] **Step 7:** Execute on real data
  ```bash
  .venv/bin/python scripts/analyze_access_logs.py --input UserData --output UserData/results -v
  ```

- [ ] **Step 8:** Validate outputs
  - [ ] Verify CSV/Excel files created
  - [ ] Check plots generated
  - [ ] Review data quality
  - [ ] Verify re-entry calculations

---

## Next Steps

1. **Run integration tests** to verify the full pipeline works with test data
2. **Execute on real Excel files** in `UserData/` (8 files: bereznaja, grisina, Iryna, safonova, skreba, tsesar, vedesina, volkova)
3. **Review outputs** for data quality and correctness
4. **Iterate if needed** based on real data characteristics

---

## Known Limitations & Assumptions

1. **Timestamp grouping**: Assumes consecutive rows with identical timestamps belong to the same logical event (takes first row)
2. **Presence model**: Assumes continuous presence from event to next event (no gaps detection)
3. **Day boundaries**: Intervals are strictly capped at 23:59:59 each day
4. **System entries**: Filters based on known patterns (TURVAPC, Järvis Leonhard) - may need expansion
5. **Column indices**: Hardcoded to A=0, C=2, H=7, AL=37 - assumes consistent Excel structure across all files

---

## Dependencies

```toml
[project.dependencies]
pandas = ">=2.2.0,<3.0.0"
openpyxl = ">=3.1.0,<4.0.0"
matplotlib = ">=3.8.0,<4.0.0"
python-dotenv = ">=1.1.1,<2.0.0"
rich = ">=14.1.0,<15.0.0"
```

**Installation:**
```bash
uv sync  # Installs all dependencies
uv sync --group test  # Also installs pytest and test tools
```

---

## Testing Commands

```bash
# Unit tests only
.venv/bin/python -m pytest tests/unit/test_access_control_analysis.py -v

# Integration tests only
.venv/bin/python -m pytest tests/integration/test_access_log_pipeline.py -v

# All tests
.venv/bin/python -m pytest tests/ -v

# With coverage
.venv/bin/python -m pytest tests/unit/test_access_control_analysis.py -v --cov=backend/access_control_analysis
```

---

**Last Updated:** 2025-12-06  
**Status:** Implementation complete, ready for real data execution
