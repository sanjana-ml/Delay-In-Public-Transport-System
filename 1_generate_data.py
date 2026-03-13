"""
1_generate_data.py
------------------
Generates 500 rows of realistic synthetic transit data.
All delays are practical urban bus delays: 0-15 min max.
Propagation is capped so delays cannot snowball beyond reality.
No fixed seed — every run produces a different delay profile.
Libraries: pandas, random, datetime only.
"""

import random
import pandas as pd
from datetime import datetime, timedelta

random.seed()

OUTPUT_FILE   = "transport_data.csv"
OPERATING_DAY = "2024-03-15"
DAY_END_HOUR  = 22
TARGET_ROWS   = 500
DATETIME_FMT  = "%Y-%m-%d %H:%M:%S"

ROUTES = {
    "R-101": "06:05",
    "R-102": "06:15",
    "R-103": "06:00",
    "R-104": "06:30",
    "R-105": "06:10",
}
ROUTE_QUOTA = 100   # exactly 100 rows per route

# ── Realistic delay caps (minutes) ───────────────────────────────────────────
MAX_TURNAROUND_DELAY  = 8.0    # depot/crew late — max 8 min
MAX_CONGESTION_ADD    = 5.0    # each congestion event adds at most 5 min
MAX_PROPAGATED_DELAY  = 15.0   # total carried delay never exceeds 15 min
MAX_DWELL_EXTRA       = 6.0    # max extra dwell time — 6 min
MAX_BASE_NOISE        = 1.5    # random noise ± 1.5 min
RECOVERY_PER_STOP     = 2.0    # bus can recover up to 2 min per stop


def make_profile():
    return {
        "turnaround_prob":   round(random.uniform(0.05, 0.25), 2),
        "congestion_prob":   round(random.uniform(0.08, 0.35), 2),
        "dwell_spike_prob":  round(random.uniform(0.05, 0.25), 2),
        "unrealistic_ratio": round(random.uniform(0.02, 0.12), 2),
        "base_noise_min":    round(random.uniform(0.0,  MAX_BASE_NOISE), 1),
    }


def print_profile(p):
    print("\n=== Run Profile (randomized) ===")
    print("Turnaround delay chance : {}%".format(int(p["turnaround_prob"]   * 100)))
    print("Congestion delay chance : {}%".format(int(p["congestion_prob"]   * 100)))
    print("Dwell spike chance      : {}%".format(int(p["dwell_spike_prob"]  * 100)))
    print("Unrealistic schedule    : {}%".format(int(p["unrealistic_ratio"] * 100)))
    print("Base noise              : +-{} min".format(p["base_noise_min"]))
    print("================================\n")


def parse_dt(time_str):
    return datetime.strptime(OPERATING_DAY + " " + time_str + ":00", DATETIME_FMT)


def fmt(dt):
    return dt.strftime(DATETIME_FMT)


def day_end():
    return datetime.strptime(
        OPERATING_DAY + " {:02d}:00:00".format(DAY_END_HOUR), DATETIME_FMT)


def clamp(dt):
    return min(dt, day_end())


def dwell_sched(seq, n):
    """Terminus stops: 2-4 min. Mid stops: 30-90 sec."""
    if seq == 1 or seq == n:
        return random.randint(120, 240)
    return random.randint(30, 90)


def travel_min(dist, unrealistic):
    """
    Realistic: urban bus at 15-25 km/h implies 2.4-4 min/km.
    Unrealistic: short schedule forces >65 km/h implied speed.
    """
    if unrealistic:
        return dist * random.uniform(0.5, 0.85)   # forces impossible speed
    return dist * random.uniform(2.4, 4.0)         # realistic urban pace


def build_trip(route_id, trip_num, num_stops, sched_start, unreal_seqs, profile):
    rows         = []
    sched_arr    = sched_start
    prev_act_dep = sched_start
    run_delay    = 0.0          # carried delay in minutes — CAPPED at MAX_PROPAGATED_DELAY
    turnaround   = random.random() < profile["turnaround_prob"]

    for seq in range(1, num_stops + 1):
        trip_id  = "{}-T-{:03d}".format(route_id, trip_num)
        stop_id  = "S-{:02d}".format(seq)
        is_last  = (seq == num_stops)
        is_unreal = (not is_last) and (seq in unreal_seqs)

        # Distance: short 0.5-3 km urban hops; unrealistic gets 4-7 km
        dist = 0.0 if is_last else (
            round(random.uniform(4.0, 7.0), 1) if is_unreal
            else round(random.uniform(0.5, 3.0), 1)
        )

        dwell_s   = dwell_sched(seq, num_stops)
        sched_dep = sched_arr + timedelta(seconds=dwell_s)
        noise     = random.uniform(-profile["base_noise_min"], profile["base_noise_min"])

        # ── Scenario selection ───────────────────────────────────────────────
        if seq == 1 and turnaround:
            # Bus departs first stop late (depot/crew issue)
            # Arrival is fine; only departure is late
            act_arr   = sched_arr
            extra     = random.uniform(5.0, MAX_TURNAROUND_DELAY)
            act_dep   = sched_dep + timedelta(minutes=extra)
            run_delay = min(extra, MAX_PROPAGATED_DELAY)

        elif seq != 1 and random.random() < profile["congestion_prob"]:
            # Congestion: arrival delayed; propagated delay + small new increment
            # New congestion increment is small (1-5 min) — not 25 min!
            extra   = random.uniform(1.0, MAX_CONGESTION_ADD)
            d_arr   = min(run_delay + extra + noise, MAX_PROPAGATED_DELAY)
            d_arr   = max(0.0, d_arr)
            act_arr = max(sched_arr + timedelta(minutes=d_arr), prev_act_dep)

            if random.random() < profile["dwell_spike_prob"]:
                # Congestion + dwell spike together
                dwell_extra = random.uniform(3.0, min(6.0, MAX_DWELL_EXTRA))
                act_dep     = act_arr + timedelta(seconds=dwell_s, minutes=dwell_extra)
                run_delay   = min((act_dep - sched_dep).total_seconds() / 60.0,
                                  MAX_PROPAGATED_DELAY)
            else:
                act_dep   = act_arr + timedelta(seconds=dwell_s)
                run_delay = min((act_arr - sched_arr).total_seconds() / 60.0,
                                MAX_PROPAGATED_DELAY)

        elif random.random() < profile["dwell_spike_prob"]:
            # Excessive dwell only — bus arrives roughly on time, lingers
            d_arr   = max(0.0, run_delay + noise)
            act_arr = max(sched_arr + timedelta(minutes=d_arr), prev_act_dep)
            dwell_extra = random.uniform(3.0, MAX_DWELL_EXTRA)
            act_dep = act_arr + timedelta(seconds=dwell_s, minutes=dwell_extra)
            run_delay = min((act_dep - sched_dep).total_seconds() / 60.0,
                            MAX_PROPAGATED_DELAY)

        else:
            # Normal: recover up to RECOVERY_PER_STOP minutes of carried delay
            recovery  = random.uniform(0.0, RECOVERY_PER_STOP)
            run_delay = max(0.0, run_delay - recovery)
            d_arr     = max(0.0, run_delay + noise)
            act_arr   = max(sched_arr + timedelta(minutes=d_arr), prev_act_dep)
            act_dep   = act_arr + timedelta(seconds=dwell_s)

        # ── Hard constraints ─────────────────────────────────────────────────
        if act_dep < act_arr:
            act_dep = act_arr + timedelta(seconds=30)
        act_arr = clamp(act_arr)
        act_dep = clamp(act_dep)

        rows.append({
            "Route_ID":                 route_id,
            "Trip_ID":                  trip_id,
            "Stop_ID":                  stop_id,
            "Stop_Sequence":            seq,
            "Distance_to_Next_Stop_km": dist,
            "Scheduled_Arrival":        fmt(sched_arr),
            "Actual_Arrival":           fmt(act_arr),
            "Scheduled_Departure":      fmt(sched_dep),
            "Actual_Departure":         fmt(act_dep),
        })

        prev_act_dep = act_dep
        if not is_last:
            sched_arr = sched_dep + timedelta(minutes=travel_min(dist, is_unreal))

    return rows


def generate(profile):
    all_rows = []
    for route_id, first_dep in ROUTES.items():
        num_stops   = random.randint(8, 12)
        non_last    = list(range(1, num_stops))
        n_unreal    = max(1, int(len(non_last) * profile["unrealistic_ratio"]))
        unreal_seqs = set(random.sample(non_last, n_unreal))

        num_trips   = -(-ROUTE_QUOTA // num_stops)
        trip_start  = parse_dt(first_dep)
        route_rows  = []

        for t in range(1, num_trips + 1):
            route_rows.extend(
                build_trip(route_id, t, num_stops, trip_start, unreal_seqs, profile)
            )
            if len(route_rows) >= ROUTE_QUOTA:
                break
            trip_start += timedelta(minutes=random.randint(10, 20))

        all_rows.extend(route_rows[:ROUTE_QUOTA])

    return all_rows[:TARGET_ROWS]


def main():
    profile = make_profile()
    print_profile(profile)
    print("Generating {} rows ...".format(TARGET_ROWS))
    rows = generate(profile)

    cols = [
        "Route_ID", "Trip_ID", "Stop_ID", "Stop_Sequence",
        "Distance_to_Next_Stop_km",
        "Scheduled_Arrival", "Actual_Arrival",
        "Scheduled_Departure", "Actual_Departure",
    ]
    df = pd.DataFrame(rows)[cols]
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    sa  = pd.to_datetime(df["Scheduled_Arrival"])
    aa  = pd.to_datetime(df["Actual_Arrival"])
    ad  = pd.to_datetime(df["Actual_Departure"])
    delay_min = (aa - sa).dt.total_seconds() / 60

    print("=" * 48)
    print("  GENERATION SUMMARY")
    print("=" * 48)
    print("Total rows           : {}".format(len(df)))
    print("Rows by Route_ID:")
    print(df["Route_ID"].value_counts().sort_index().to_string())
    print()
    print("Delay stats (minutes):")
    print("  Mean  : {:.1f} min".format(delay_min.mean()))
    print("  Median: {:.1f} min".format(delay_min.median()))
    print("  Max   : {:.1f} min".format(delay_min.max()))
    print("  >5min : {} stops".format(int((delay_min > 5).sum())))
    print("  >10min: {} stops".format(int((delay_min > 10).sum())))
    print("=" * 48)
    print("Saved: {}".format(OUTPUT_FILE))


if __name__ == "__main__":
    main()