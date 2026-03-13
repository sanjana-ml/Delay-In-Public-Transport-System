"""
2_process_logic.py
------------------
Rule-based heuristic engine. Classifies every row into exactly one delay cause.
Also derives Root_Cause_Detail — one level deeper explanation per row.
Libraries: pandas only. No iterrows(), no ML.

Rule priority (first match wins):
  1. Vehicle Turnaround Delay
  2. Excessive Stop Dwell Time
  3. Unrealistic Timetable
  4. Route Congestion Pattern
  5. On Time
"""

import sys
import pandas as pd

# ── Files ─────────────────────────────────────────────────────────────────────
INPUT_FILE  = "transport_data.csv"
OUTPUT_FILE = "transport_data_processed.csv"

# ── Thresholds ────────────────────────────────────────────────────────────────
TURNAROUND_DEP_DELAY_MIN    = 5.0
TURNAROUND_SEVERE_MIN       = 10.0   # above this → "late inbound vehicle"
EXCESS_DWELL_MIN            = 3.0
EXCESS_DWELL_SEVERE_MIN     = 5.0    # above this → boarding surge
MAX_URBAN_SPEED_KMH         = 65.0
IMPOSSIBLE_SPEED_KMH        = 80.0   # above this → "physically impossible"
CONGESTION_ARR_DELAY_MIN    = 10.0
CONGESTION_CORRIDOR_STOPS   = 3      # consecutive late stops → corridor congestion

# ── Labels ────────────────────────────────────────────────────────────────────
LBL_TURNAROUND = "Vehicle Turnaround Delay"
LBL_DWELL      = "Excessive Stop Dwell Time"
LBL_TIMETABLE  = "Unrealistic Timetable"
LBL_CONGESTION = "Route Congestion Pattern"
LBL_ON_TIME    = "On Time"

REQUIRED = [
    "Route_ID", "Trip_ID", "Stop_ID", "Stop_Sequence",
    "Distance_to_Next_Stop_km",
    "Scheduled_Arrival", "Actual_Arrival",
    "Scheduled_Departure", "Actual_Departure",
]
DT_COLS = ["Scheduled_Arrival", "Actual_Arrival",
           "Scheduled_Departure", "Actual_Departure"]


# ══════════════════════════════════════════════════════════════════════════════
# Load & validate
# ══════════════════════════════════════════════════════════════════════════════

def load(path):
    try:
        df = pd.read_csv(path, encoding="utf-8")
    except FileNotFoundError:
        print("ERROR: '{}' not found. Run 1_generate_data.py first.".format(path))
        sys.exit(1)
    except Exception as e:
        print("ERROR reading '{}': {}".format(path, e))
        sys.exit(1)

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        print("ERROR: Missing required columns:")
        for c in missing:
            print("  - {}".format(c))
        sys.exit(1)

    for col in DT_COLS:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    print("[INFO] Loaded {} rows from '{}'.".format(len(df), path))
    return df


# ══════════════════════════════════════════════════════════════════════════════
# Derive metrics
# ══════════════════════════════════════════════════════════════════════════════

def derive(df):
    df["_arr_delay_min"] = (
        (df["Actual_Arrival"] - df["Scheduled_Arrival"]).dt.total_seconds() / 60.0
    )
    df["_dep_delay_min"] = (
        (df["Actual_Departure"] - df["Scheduled_Departure"]).dt.total_seconds() / 60.0
    )
    df["_act_dwell_s"] = (df["Actual_Departure"] - df["Actual_Arrival"]).dt.total_seconds()
    df["_sch_dwell_s"] = (df["Scheduled_Departure"] - df["Scheduled_Arrival"]).dt.total_seconds()
    df["_excess_dwell_min"] = (df["_act_dwell_s"] - df["_sch_dwell_s"]) / 60.0

    df["_next_sched_arr"] = df.groupby("Trip_ID")["Scheduled_Arrival"].shift(-1)
    df["_sched_travel_hr"] = (
        (df["_next_sched_arr"] - df["Scheduled_Departure"]).dt.total_seconds() / 3600.0
    )
    valid = (
        (df["Distance_to_Next_Stop_km"] > 0) &
        (df["_sched_travel_hr"] > 0) &
        df["_next_sched_arr"].notna()
    )
    df["_implied_kmh"] = float("nan")
    df.loc[valid, "_implied_kmh"] = (
        df.loc[valid, "Distance_to_Next_Stop_km"] / df.loc[valid, "_sched_travel_hr"]
    )

    # Consecutive late-stop counter per trip (for corridor congestion detection)
    late = (df["_arr_delay_min"] >= CONGESTION_ARR_DELAY_MIN).astype(int)
    # Rolling sum of 3 consecutive stops within same trip
    df["_consec_late"] = (
        df.groupby("Trip_ID")["_arr_delay_min"]
        .transform(lambda s: s.ge(CONGESTION_ARR_DELAY_MIN)
                              .rolling(CONGESTION_CORRIDOR_STOPS, min_periods=CONGESTION_CORRIDOR_STOPS)
                              .sum())
        .fillna(0)
    )
    return df


# ══════════════════════════════════════════════════════════════════════════════
# Build masks
# ══════════════════════════════════════════════════════════════════════════════

def masks(df):
    m = {}
    m[LBL_TURNAROUND] = (
        (df["Stop_Sequence"] == 1) &
        (df["_dep_delay_min"] >= TURNAROUND_DEP_DELAY_MIN)
    )
    m[LBL_DWELL] = (df["_excess_dwell_min"] >= EXCESS_DWELL_MIN)
    m[LBL_TIMETABLE] = (
        df["_implied_kmh"].notna() &
        (df["_implied_kmh"] > MAX_URBAN_SPEED_KMH)
    )
    m[LBL_CONGESTION] = (
        (df["Stop_Sequence"] != 1) &
        (df["_excess_dwell_min"] < EXCESS_DWELL_MIN) &
        (df["_arr_delay_min"] >= CONGESTION_ARR_DELAY_MIN)
    )
    m[LBL_ON_TIME] = ~(
        m[LBL_TURNAROUND] | m[LBL_DWELL] | m[LBL_TIMETABLE] | m[LBL_CONGESTION]
    )
    return m


# ══════════════════════════════════════════════════════════════════════════════
# Apply classification
# ══════════════════════════════════════════════════════════════════════════════

def apply_rules(df, m):
    df["Attributed_Cause"] = LBL_ON_TIME
    for label in [LBL_ON_TIME, LBL_CONGESTION, LBL_TIMETABLE, LBL_DWELL, LBL_TURNAROUND]:
        df.loc[m[label], "Attributed_Cause"] = label
    return df


# ══════════════════════════════════════════════════════════════════════════════
# Root Cause Detail — one deeper level per row
# ══════════════════════════════════════════════════════════════════════════════

def build_root_cause_detail(row):
    cause  = row["Attributed_Cause"]
    excess = row.get("_excess_dwell_min", 0) or 0
    dep_d  = row.get("_dep_delay_min", 0) or 0
    arr_d  = row.get("_arr_delay_min", 0) or 0
    speed  = row.get("_implied_kmh", 0) or 0
    consec = row.get("_consec_late", 0) or 0
    sid    = row.get("Stop_ID", "")
    rid    = row.get("Route_ID", "")
    variance = round(abs(arr_d), 1)

    if cause == LBL_DWELL:
        if excess >= EXCESS_DWELL_SEVERE_MIN:
            return (
                "Boarding surge — dwell exceeded schedule by {:.0f}m at {}"
                " (likely high-volume stop or accessibility ramp)".format(excess, sid)
            )
        else:
            return (
                "Minor hold at {} — dwell over by {:.0f}m"
                " (possible fare dispute or door fault)".format(sid, excess)
            )

    elif cause == LBL_TURNAROUND:
        if dep_d >= TURNAROUND_SEVERE_MIN:
            return (
                "Late inbound vehicle on {} — turnaround gap of {:.0f}m"
                " suggests previous run overran or crew changeover delay".format(rid, dep_d)
            )
        else:
            return (
                "Depot dispatch delay on {} — {:.0f}m late departure"
                " from first stop".format(rid, dep_d)
            )

    elif cause == LBL_TIMETABLE:
        if speed >= IMPOSSIBLE_SPEED_KMH:
            return (
                "Schedule physically impossible — requires {:.0f} km/h between"
                " {} and next stop (urban bus max ~50 km/h)".format(speed, sid)
            )
        else:
            return (
                "Schedule assumes no traffic — requires {:.0f} km/h from {}"
                "; needs revision to allow for signals and stops".format(speed, sid)
            )

    elif cause == LBL_CONGESTION:
        if consec >= CONGESTION_CORRIDOR_STOPS:
            return (
                "Sustained corridor congestion on {} — {} consecutive stops"
                " showing 10m+ delays including {}".format(rid, int(consec), sid)
            )
        else:
            return (
                "Localised bottleneck near {} on {} — isolated"
                " arrival delay of {:.0f}m, dwell normal".format(sid, rid, arr_d)
            )

    else:  # On Time
        return "Within tolerance — {:.1f}m arrival variance".format(variance)


def add_root_cause(df):
    df["Root_Cause_Detail"] = df.apply(build_root_cause_detail, axis=1)
    return df


# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════

def print_summary(df):
    total  = len(df)
    counts = df["Attributed_Cause"].value_counts()
    order  = [LBL_TURNAROUND, LBL_DWELL, LBL_TIMETABLE, LBL_CONGESTION, LBL_ON_TIME]

    print("\n=== Delay Attribution Summary " + "=" * 18)
    print("Total records: {:>22,}".format(total))
    print("-" * 50)
    for lbl in order:
        n   = counts.get(lbl, 0)
        pct = n / total * 100 if total else 0
        print("  {:<32} {:>4}  ({:>5.1f}%)".format(lbl + ":", n, pct))
    print("=" * 50)

    non_ok = df[df["Attributed_Cause"] != LBL_ON_TIME]
    if not non_ok.empty:
        worst = non_ok.groupby("Stop_ID").size().sort_values(ascending=False).head(5)
        print("\nTop 5 problem stops:")
        for sid, cnt in worst.items():
            print("  {:<10}  {} flagged".format(sid, cnt))
    print()


# ══════════════════════════════════════════════════════════════════════════════
# Save
# ══════════════════════════════════════════════════════════════════════════════

def save(df, path):
    drop = [c for c in df.columns if c.startswith("_")]
    out  = df.drop(columns=drop)
    for col in DT_COLS:
        if col in out.columns:
            out[col] = out[col].dt.strftime("%Y-%m-%d %H:%M:%S")
    out.to_csv(path, index=False, encoding="utf-8")
    print("Saved: {}  ({} columns)".format(path, len(out.columns)))


# ══════════════════════════════════════════════════════════════════════════════
# Public API — importable by 5_manual_analysis.py
# ══════════════════════════════════════════════════════════════════════════════

def classify_dataframe(df):
    """
    Takes a DataFrame with the 9 required columns (datetimes already parsed).
    Returns the same DataFrame with Attributed_Cause and Root_Cause_Detail added.
    Used by 5_manual_analysis.py so rules stay in one place.
    """
    df = derive(df)
    m  = masks(df)
    df = apply_rules(df, m)
    df = add_root_cause(df)
    return df


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n[START] 2_process_logic.py\n")
    df = load(INPUT_FILE)
    df = classify_dataframe(df)
    print_summary(df)
    save(df, OUTPUT_FILE)
    print("[DONE]\n")


if __name__ == "__main__":
    main()