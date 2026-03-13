"""
5_manual_analysis.py
--------------------
Zero-dataset mode. No CSV required.
Prompts the user for route/stop timings, applies the same rule-based
heuristics as 2_process_logic.py, prints a full console report, and
optionally generates manual_analysis_report.html (offline, no internet).

Usage:
    python 5_manual_analysis.py
    python upload_and_run.py --manual
"""

import sys
import os
from datetime import datetime, timedelta

# ── Optional imports (graceful fallback if missing) ───────────────────────────
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import io, base64
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ── Thresholds (must match 2_process_logic.py) ───────────────────────────────
TURNAROUND_DEP_DELAY_MIN  = 5.0
TURNAROUND_SEVERE_MIN     = 10.0
EXCESS_DWELL_MIN          = 3.0
EXCESS_DWELL_SEVERE_MIN   = 5.0
MAX_URBAN_SPEED_KMH       = 65.0
IMPOSSIBLE_SPEED_KMH      = 80.0
CONGESTION_ARR_DELAY_MIN  = 10.0
CONGESTION_CORRIDOR_STOPS = 3

LBL_TURNAROUND = "Vehicle Turnaround Delay"
LBL_DWELL      = "Excessive Stop Dwell Time"
LBL_TIMETABLE  = "Unrealistic Timetable"
LBL_CONGESTION = "Route Congestion Pattern"
LBL_ON_TIME    = "On Time"

# ── Design tokens (for HTML report) ──────────────────────────────────────────
BG      = "#0f1117"
BG_CARD = "#1a1d27"
BG_TH   = "#252836"
C_TEXT  = "#e6e6e6"
C_MUTED = "#8b8fa3"
SHADOW  = "0 4px 20px rgba(0,0,0,0.4)"
FONT    = "'Segoe UI', system-ui, -apple-system, sans-serif"

CAUSE_COLORS = {
    LBL_DWELL:      "#ff6b6b",
    LBL_TURNAROUND: "#ffd93d",
    LBL_CONGESTION: "#6bcb77",
    LBL_TIMETABLE:  "#4d96ff",
    LBL_ON_TIME:    "#888888",
}

def delay_color(d):
    if d <= 2:  return "#6bcb77"
    if d <= 5:  return "#ffd93d"
    if d <= 10: return "#ff9f43"
    return "#ff6b6b"

def delay_label_short(d):
    if d <= 2:  return "On Time"
    if d <= 5:  return "Minor"
    if d <= 10: return "Moderate"
    return "Severe"

def node_size(d):
    if d <= 2:  return 16
    if d <= 5:  return 22
    if d <= 10: return 28
    return 34

DIVIDER = "-" * 78


# ══════════════════════════════════════════════════════════════════════════════
# Input helpers
# ══════════════════════════════════════════════════════════════════════════════

def ask(prompt, default=None):
    """Prompt the user, return stripped string. Ctrl-C exits gracefully."""
    try:
        suffix = " [{}]: ".format(default) if default is not None else ": "
        val = input(prompt + suffix).strip()
        return val if val else (str(default) if default is not None else "")
    except (KeyboardInterrupt, EOFError):
        print("\n\nAborted.")
        sys.exit(0)


def ask_time(prompt):
    """Ask for HH:MM, return datetime on 1900-01-01."""
    while True:
        raw = ask(prompt)
        try:
            return datetime.strptime("1900-01-01 " + raw, "%Y-%m-%d %H:%M")
        except ValueError:
            print("  ! Enter time as HH:MM (e.g. 08:30)")


def ask_float(prompt, lo=0.0, hi=9999.0, default=None):
    """Ask for a float in range [lo, hi]."""
    while True:
        raw = ask(prompt, default=default)
        try:
            v = float(raw)
            if lo <= v <= hi:
                return v
            print("  ! Please enter a value between {} and {}".format(lo, hi))
        except ValueError:
            print("  ! Please enter a number")


def ask_int(prompt, lo=1, hi=9999, default=None):
    while True:
        raw = ask(prompt, default=default)
        try:
            v = int(raw)
            if lo <= v <= hi:
                return v
            print("  ! Please enter a whole number between {} and {}".format(lo, hi))
        except ValueError:
            print("  ! Please enter a whole number")


# ══════════════════════════════════════════════════════════════════════════════
# Collect stop data from user
# ══════════════════════════════════════════════════════════════════════════════

def collect_input():
    print("\n" + "=" * 60)
    print("  Manual Delay Analysis  (No Dataset Required)")
    print("=" * 60)
    print("  Enter timing data for one route. Press Ctrl-C to quit.\n")

    route_name = ask("Route or location name", default="Route 1")
    n_stops    = ask_int("Number of stops on this route", lo=2, hi=50, default=4)

    stops = []
    base_date = "1900-01-01"

    for i in range(1, n_stops + 1):
        print("\n  --- Stop {} of {} ---".format(i, n_stops))
        stop_name = ask("  Stop {} name".format(i), default="Stop {}".format(i))

        sched_arr = ask_time("  Scheduled Arrival   (HH:MM)")
        actual_arr = ask_time("  Actual Arrival      (HH:MM)")
        sched_dep = ask_time("  Scheduled Departure (HH:MM)")
        actual_dep = ask_time("  Actual Departure    (HH:MM)")

        # Handle midnight crossover (if departure < arrival, add 1 day)
        if sched_dep < sched_arr:
            sched_dep += timedelta(days=1)
        if actual_dep < actual_arr:
            actual_dep += timedelta(days=1)

        if i < n_stops:
            dist = ask_float(
                "  Distance to next stop (km)", lo=0.0, hi=100.0, default=2.0
            )
        else:
            dist = 0.0
            print("  Distance to next stop: 0.0 (last stop)")

        stops.append({
            "Stop_Name":                stop_name,
            "Stop_Sequence":            i,
            "Distance_to_Next_Stop_km": dist,
            "Scheduled_Arrival":        sched_arr,
            "Actual_Arrival":           actual_arr,
            "Scheduled_Departure":      sched_dep,
            "Actual_Departure":         actual_dep,
        })

    return route_name, stops


# ══════════════════════════════════════════════════════════════════════════════
# Classification engine (same rules as 2_process_logic.py)
# ══════════════════════════════════════════════════════════════════════════════

def classify_stops(stops):
    """Applies all rules to the stops list, returns enriched list."""
    n = len(stops)

    # Derive metrics for each stop
    for i, s in enumerate(stops):
        sa  = s["Scheduled_Arrival"]
        aa  = s["Actual_Arrival"]
        sd  = s["Scheduled_Departure"]
        ad  = s["Actual_Departure"]
        dist = s["Distance_to_Next_Stop_km"]

        s["_arr_delay_min"]   = (aa - sa).total_seconds() / 60.0
        s["_dep_delay_min"]   = (ad - sd).total_seconds() / 60.0
        s["_act_dwell_s"]     = (ad - aa).total_seconds()
        s["_sch_dwell_s"]     = (sd - sa).total_seconds()
        s["_excess_dwell_min"] = (s["_act_dwell_s"] - s["_sch_dwell_s"]) / 60.0

        # Implied speed to next stop
        if i < n - 1 and dist > 0:
            next_s = stops[i + 1]
            travel_hr = (next_s["Scheduled_Arrival"] - sd).total_seconds() / 3600.0
            s["_implied_kmh"] = dist / travel_hr if travel_hr > 0 else 0.0
        else:
            s["_implied_kmh"] = 0.0

    # Consecutive late stop counter
    for i, s in enumerate(stops):
        if i < CONGESTION_CORRIDOR_STOPS - 1:
            s["_consec_late"] = 0
        else:
            window = stops[i - CONGESTION_CORRIDOR_STOPS + 1 : i + 1]
            s["_consec_late"] = sum(
                1 for w in window if w["_arr_delay_min"] >= CONGESTION_ARR_DELAY_MIN
            )

    # Apply rules
    for s in stops:
        seq    = s["Stop_Sequence"]
        dep_d  = s["_dep_delay_min"]
        excess = s["_excess_dwell_min"]
        arr_d  = s["_arr_delay_min"]
        speed  = s["_implied_kmh"]
        consec = s["_consec_late"]
        name   = s["Stop_Name"]
        variance = round(abs(arr_d), 1)

        if seq == 1 and dep_d >= TURNAROUND_DEP_DELAY_MIN:
            cause = LBL_TURNAROUND
            if dep_d >= TURNAROUND_SEVERE_MIN:
                detail = (
                    "Late inbound vehicle — turnaround gap of {:.0f}m at {}"
                    " suggests previous run overran or crew changeover".format(dep_d, name)
                )
            else:
                detail = (
                    "Depot dispatch delay — {:.0f}m late departure from"
                    " first stop ({})".format(dep_d, name)
                )

        elif excess >= EXCESS_DWELL_MIN:
            cause = LBL_DWELL
            if excess >= EXCESS_DWELL_SEVERE_MIN:
                detail = (
                    "Boarding surge at {} — dwell exceeded schedule by"
                    " {:.0f}m (accessibility ramp or high passenger volume)".format(name, excess)
                )
            else:
                detail = (
                    "Minor hold at {} — dwell over by {:.0f}m"
                    " (possible fare dispute or door fault)".format(name, excess)
                )

        elif speed > MAX_URBAN_SPEED_KMH:
            cause = LBL_TIMETABLE
            if speed >= IMPOSSIBLE_SPEED_KMH:
                detail = (
                    "Schedule physically impossible from {} — requires"
                    " {:.0f} km/h (urban bus max ~50 km/h)".format(name, speed)
                )
            else:
                detail = (
                    "Schedule assumes no traffic from {} — requires"
                    " {:.0f} km/h; needs revision for signals".format(name, speed)
                )

        elif seq != 1 and excess < EXCESS_DWELL_MIN and arr_d >= CONGESTION_ARR_DELAY_MIN:
            cause = LBL_CONGESTION
            if consec >= CONGESTION_CORRIDOR_STOPS:
                detail = (
                    "Sustained corridor congestion — {} consecutive stops"
                    " with 10m+ delays, including {}".format(int(consec), name)
                )
            else:
                detail = (
                    "Localised bottleneck near {} — arrival delay {:.0f}m,"
                    " dwell normal".format(name, arr_d)
                )

        else:
            cause  = LBL_ON_TIME
            detail = "Within tolerance — {:.1f}m arrival variance".format(variance)

        s["Attributed_Cause"]  = cause
        s["Root_Cause_Detail"] = detail
        s["Delay_Min"]         = max(0.0, round(arr_d, 1))

    return stops


# ══════════════════════════════════════════════════════════════════════════════
# Console report
# ══════════════════════════════════════════════════════════════════════════════

STATUS_ICON = {
    LBL_ON_TIME:    "[OK]",
    LBL_DWELL:      "[!!]",
    LBL_TURNAROUND: "[!!]",
    LBL_CONGESTION: "[>>]",
    LBL_TIMETABLE:  "[TT]",
}

def print_report(route_name, stops):
    print("\n" + "=" * 60)
    print("  DELAY ANALYSIS REPORT")
    print("  Route: {}".format(route_name))
    print("=" * 60)

    # Column widths
    name_w  = max(18, max(len(s["Stop_Name"]) for s in stops) + 2)
    cause_w = 28

    # Header
    print("\nStop-by-Stop Breakdown:")
    print(DIVIDER)
    print("  {:<{nw}} {:>6}  {:<6}  {:<{cw}}".format(
        "Stop", "Delay", "Status", "Attributed Cause",
        nw=name_w, cw=cause_w))
    print(DIVIDER)

    for s in stops:
        d     = s["Delay_Min"]
        cause = s["Attributed_Cause"]
        icon  = STATUS_ICON.get(cause, "[?]")
        delay_str = "{}m".format(int(d)) if d > 0 else "0m"

        print("  {:<{nw}} {:>5}   {:<6}  {:<{cw}}".format(
            s["Stop_Name"][:name_w], delay_str, icon, cause[:cause_w],
            nw=name_w, cw=cause_w))
        # Root cause indented below
        detail = s["Root_Cause_Detail"]
        # Word-wrap at 68 chars
        while len(detail) > 68:
            cut = detail[:68].rfind(" ")
            if cut < 0: cut = 68
            print("    > {}".format(detail[:cut]))
            detail = detail[cut:].lstrip()
        print("    > {}".format(detail))

    print(DIVIDER)

    # Propagation summary
    delayed = [s for s in stops if s["Delay_Min"] >= CONGESTION_ARR_DELAY_MIN]
    if delayed:
        origin = min(delayed, key=lambda s: s["Stop_Sequence"])
        peak   = max(stops, key=lambda s: s["Delay_Min"])
        last   = stops[-1]
        print("\nPropagation Summary:")
        print("  Delay originated at : {} (Stop {})".format(
            origin["Stop_Name"], origin["Stop_Sequence"]))
        print("  Peak delay          : {:.0f}m at {} (Stop {})".format(
            peak["Delay_Min"], peak["Stop_Name"], peak["Stop_Sequence"]))
        print("  Final stop delay    : {:.0f}m at {}".format(
            last["Delay_Min"], last["Stop_Name"]))
    else:
        print("\nPropagation Summary: No significant delays detected.")

    # Primary root cause
    from collections import Counter
    cause_counts = Counter(s["Attributed_Cause"] for s in stops if s["Attributed_Cause"] != LBL_ON_TIME)
    if cause_counts:
        primary = cause_counts.most_common(1)[0][0]
        count   = cause_counts.most_common(1)[0][1]
        print("\nPrimary Root Cause: {} ({} stop(s))".format(primary, count))
        affected = [s for s in stops if s["Attributed_Cause"] == primary]
        for s in affected:
            print("  -> {}".format(s["Root_Cause_Detail"]))

        # Recommendation
        print("\nRecommendation:")
        if primary == LBL_CONGESTION:
            seqs = [str(s["Stop_Sequence"]) for s in affected]
            print("  Review signal timing and lane priority between"
                  " stops {}".format(", ".join(seqs)))
        elif primary == LBL_DWELL:
            print("  Investigate boarding procedures at high-dwell stops."
                  " Consider pre-boarding payment or wider doors.")
        elif primary == LBL_TURNAROUND:
            print("  Review depot turnaround schedule. Build buffer time"
                  " between inbound run end and outbound departure.")
        elif primary == LBL_TIMETABLE:
            affected_segs = [s["Stop_Name"] for s in affected]
            print("  Revise timetable segments: {}."
                  " Current schedule is physically unachievable.".format(
                      ", ".join(affected_segs)))
    else:
        print("\nPrimary Root Cause: None — route operating on time.")
        print("Recommendation    : No action required.")

    print()


# ══════════════════════════════════════════════════════════════════════════════
# HTML report generator
# ══════════════════════════════════════════════════════════════════════════════

def build_svg_timeline(stops):
    n = len(stops)
    PAD_L=55; PAD_R=55; PAD_T=72; PAD_B=72; STEP=110
    SVG_W = PAD_L + PAD_R + STEP*(n-1) if n>1 else PAD_L+PAD_R+100
    LINE_Y = PAD_T+18
    SVG_H  = PAD_T+PAD_B+36

    def nx(i):
        return PAD_L + i*STEP if n>1 else PAD_L+50

    lines=""; annots=""; nodes=""

    for i in range(n-1):
        x1=nx(i); x2=nx(i+1); sl=x2-x1
        col = delay_color(stops[i+1]["Delay_Min"])
        lines += (
            '<line x1="{x1}" y1="{ly}" x2="{x2}" y2="{ly}" '
            'stroke="{c}" stroke-width="3" stroke-linecap="round" '
            'stroke-dasharray="{sl}" stroke-dashoffset="{sl}" '
            'style="animation:drawLine 0.4s ease forwards;animation-delay:{ad}ms;"/>'
        ).format(x1=x1,ly=LINE_Y,x2=x2,c=col,sl=sl,ad=200+i*120)

    for i in range(1,n):
        diff  = stops[i]["Delay_Min"] - stops[i-1]["Delay_Min"]
        mid_x = (nx(i-1)+nx(i))/2
        ann_y = LINE_Y - 18
        if diff >= 5:
            annots += (
                '<text x="{mx}" y="{ay}" text-anchor="middle" font-size="11" '
                'font-weight="700" fill="#ff9f43" '
                'style="opacity:0;animation:fadeIn 0.4s ease forwards;animation-delay:{ad}ms;">'
                '&#x26A1; +{d:.0f}m</text>'
            ).format(mx=mid_x,ay=ann_y,d=diff,ad=400+i*120)
        elif diff <= -3:
            annots += (
                '<text x="{mx}" y="{ay}" text-anchor="middle" font-size="11" '
                'font-weight="700" fill="#6bcb77" '
                'style="opacity:0;animation:fadeIn 0.4s ease forwards;animation-delay:{ad}ms;">'
                '&#x2193; {d:.0f}m</text>'
            ).format(mx=mid_x,ay=ann_y,d=abs(diff),ad=400+i*120)

    for i,s in enumerate(stops):
        x=nx(i); d=s["Delay_Min"]; col=delay_color(d); r=node_size(d)/2; ad=100+i*120
        nodes += (
            '<circle cx="{x}" cy="{ly}" r="{gr}" fill="none" stroke="{c}" '
            'stroke-width="1.5" opacity="0.3" '
            'style="opacity:0;animation:fadeScale 0.4s ease forwards;animation-delay:{ad}ms;"/>'
        ).format(x=x,ly=LINE_Y,gr=r+6,c=col,ad=ad)
        nodes += (
            '<circle cx="{x}" cy="{ly}" r="{r}" fill="{c}" stroke="#1a1d27" '
            'stroke-width="2.5" style="filter:drop-shadow(0 0 5px {c}99);'
            'opacity:0;animation:fadeScale 0.4s ease forwards;animation-delay:{ad}ms;"/>'
        ).format(x=x,ly=LINE_Y,r=r,c=col,ad=ad)
        nodes += (
            '<text x="{x}" y="{ly}" text-anchor="middle" font-size="10" fill="{mu}" '
            'style="opacity:0;animation:fadeIn 0.4s ease forwards;animation-delay:{ad}ms;">'
            '{sid}</text>'
        ).format(x=x,ly=LINE_Y+r+13,mu=C_MUTED,sid=s["Stop_Name"][:10],ad=ad)
        dt = "{:.0f}m".format(d) if d>0 else "0m"
        nodes += (
            '<text x="{x}" y="{ly}" text-anchor="middle" font-size="12" '
            'font-weight="700" fill="{c}" '
            'style="opacity:0;animation:fadeIn 0.4s ease forwards;animation-delay:{ad}ms;">'
            '{dt}</text>'
        ).format(x=x,ly=LINE_Y+r+27,c=col,dt=dt,ad=ad)

    return (
        '<svg viewBox="0 0 {w} {h}" width="100%" xmlns="http://www.w3.org/2000/svg" '
        'style="overflow:visible;display:block;">'
        '<defs><style>'
        '@keyframes drawLine{{to{{stroke-dashoffset:0;}}}}'
        '@keyframes fadeScale{{from{{opacity:0;transform:scale(0.3);transform-box:fill-box;'
        'transform-origin:center;}}to{{opacity:1;transform:scale(1);transform-box:fill-box;'
        'transform-origin:center;}}}}'
        '@keyframes fadeIn{{from{{opacity:0;}}to{{opacity:1;}}}}'
        '</style></defs>'
        '{lines}{annots}{nodes}'
        '</svg>'
    ).format(w=SVG_W,h=SVG_H,lines=lines,annots=annots,nodes=nodes)


def generate_html_report(route_name, stops, out_file="manual_analysis_report.html"):
    from collections import Counter
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_delay = sum(s["Delay_Min"] for s in stops)
    delayed_n   = sum(1 for s in stops if s["Attributed_Cause"] != LBL_ON_TIME)
    on_time_pct = round((len(stops)-delayed_n)/len(stops)*100,1) if stops else 0

    cause_counts = Counter(s["Attributed_Cause"] for s in stops if s["Attributed_Cause"]!=LBL_ON_TIME)
    primary = cause_counts.most_common(1)[0][0] if cause_counts else LBL_ON_TIME
    primary_color = CAUSE_COLORS.get(primary,"#888888")

    # Summary cards
    def card(emoji,label,value,color):
        return (
            '<div style="flex:1;min-width:160px;background:{bg};border-radius:12px;'
            'padding:20px 22px;box-shadow:{sh};border-top:3px solid {c};">'
            '<div style="font-size:20px;margin-bottom:8px;">{e}</div>'
            '<div style="font-size:28px;font-weight:800;color:{c};margin-bottom:4px;">{v}</div>'
            '<div style="font-size:13px;font-weight:600;color:{tx};">{l}</div>'
            '</div>'
        ).format(bg=BG_CARD,sh=SHADOW,c=color,e=emoji,v=value,l=label,tx=C_TEXT)

    cards_html = (
        '<div style="display:flex;flex-wrap:wrap;gap:16px;margin-bottom:28px;">'
        + card("📍","Stops Analysed",len(stops),"#6bcb77")
        + card("⏱","Total Delay (min)",round(total_delay,1),"#6bcbff")
        + card("🚨","Delayed Stops",delayed_n,primary_color)
        + card("✅","On-Time Rate","{}%".format(on_time_pct),"#4ade80")
        + '</div>'
    )

    # Root cause card
    rc_html = (
        '<div style="background:{bg};border-radius:12px;padding:20px 24px;'
        'box-shadow:{sh};margin-bottom:28px;border-left:4px solid {c};">'
        '<div style="font-size:13px;font-weight:700;color:{mu};text-transform:uppercase;'
        'letter-spacing:0.06em;margin-bottom:8px;">Primary Root Cause</div>'
        '<div style="font-size:18px;font-weight:800;color:{c};margin-bottom:6px;">{p}</div>'
        '<div style="font-size:12px;color:{tx};">{cnt} stop(s) affected</div>'
        '</div>'
    ).format(bg=BG_CARD,sh=SHADOW,c=primary_color,mu=C_MUTED,
             p=primary,cnt=cause_counts.get(primary,0),tx=C_TEXT)

    # SVG timeline
    svg_html = (
        '<div style="background:{bg};border-radius:12px;padding:22px 26px;'
        'box-shadow:{sh};margin-bottom:28px;">'
        '<div style="font-size:15px;font-weight:700;color:{tx};margin-bottom:16px;">'
        'Delay Propagation Timeline</div>'
        '<div style="overflow-x:auto;">{svg}</div>'
        '</div>'
    ).format(bg=BG_CARD,sh=SHADOW,tx=C_TEXT,svg=build_svg_timeline(stops))

    # Stop-by-stop table
    def row_color(cause):
        return CAUSE_COLORS.get(cause,"#888888")

    th = lambda t,c=C_MUTED: (
        '<th style="padding:10px 14px;font-size:11px;font-weight:700;'
        'letter-spacing:0.06em;text-transform:uppercase;'
        'background:{bg};color:{c};text-align:left;">{t}</th>'
    ).format(bg=BG_TH,c=c,t=t)

    table_rows=""
    for s in stops:
        c     = row_color(s["Attributed_Cause"])
        d_str = "{:.0f}m".format(s["Delay_Min"]) if s["Delay_Min"]>0 else "0m"
        table_rows += (
            '<tr style="border-bottom:1px solid #2a2d3e;" '
            'onmouseover="this.style.background=\'rgba(255,255,255,0.03)\'" '
            'onmouseout="this.style.background=\'transparent\'">'
            '<td style="padding:10px 14px;font-weight:600;color:{tx};">{nm}</td>'
            '<td style="padding:10px 14px;text-align:center;font-weight:700;color:{c};">{d}</td>'
            '<td style="padding:10px 14px;">'
            '<span style="background:{c}22;color:{c};border:1px solid {c}44;'
            'border-radius:5px;padding:2px 8px;font-size:11px;font-weight:700;">'
            '{cause}</span></td>'
            '<td style="padding:10px 14px;font-size:11px;color:{mu};">{det}</td>'
            '</tr>'
        ).format(tx=C_TEXT,nm=s["Stop_Name"],c=c,d=d_str,
                 cause=s["Attributed_Cause"],det=s["Root_Cause_Detail"],mu=C_MUTED)

    table_html = (
        '<div style="background:{bg};border-radius:12px;box-shadow:{sh};'
        'overflow:hidden;margin-bottom:28px;">'
        '<div style="padding:18px 22px 0;font-size:15px;font-weight:700;'
        'color:{tx};margin-bottom:12px;">Stop-by-Stop Attribution</div>'
        '<div style="overflow-x:auto;">'
        '<table style="width:100%;border-collapse:collapse;">'
        '<tr>{th_stop}{th_delay}{th_cause}{th_detail}</tr>'
        '{rows}'
        '</table></div></div>'
    ).format(
        bg=BG_CARD,sh=SHADOW,tx=C_TEXT,
        th_stop=th("Stop"),th_delay=th("Delay","#6bcbff"),
        th_cause=th("Cause"),th_detail=th("Root Cause Detail"),
        rows=table_rows
    )

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Manual Delay Analysis — {route}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
html{{scroll-behavior:smooth;}}
body{{background:{bg};color:{tx};font-family:{font};min-height:100vh;}}
::-webkit-scrollbar{{width:6px;}} ::-webkit-scrollbar-track{{background:{bg};}}
::-webkit-scrollbar-thumb{{background:#2e3146;border-radius:3px;}}
</style>
</head>
<body>
<div style="background:#13161f;border-bottom:1px solid #2a2d3e;
  padding:14px 40px;display:flex;justify-content:space-between;align-items:center;">
  <div style="display:flex;align-items:center;gap:10px;">
    <div style="width:8px;height:8px;border-radius:50%;background:#4ade80;
      box-shadow:0 0 8px #4ade80;"></div>
    <span style="font-size:13px;font-weight:700;letter-spacing:0.05em;">TRANSIT ANALYTICS — MANUAL MODE</span>
  </div>
  <span style="font-size:11px;color:{mu};">{ts}</span>
</div>
<div style="max-width:1100px;margin:0 auto;padding:36px 40px 80px;">
  <div style="margin-bottom:28px;">
    <h1 style="font-size:26px;font-weight:800;letter-spacing:-0.02em;margin-bottom:6px;">
      {route}
    </h1>
    <p style="color:{mu};font-size:13px;">
      Manual delay analysis — rule-based heuristic classification, no dataset required
    </p>
  </div>
  {cards}
  {rc}
  {svg}
  {table}
</div>
<div style="text-align:center;padding:28px;color:{mu};font-size:12px;
  border-top:1px solid #2a2d3e;">
  Generated by Offline Transport Delay Attribution System (Manual Mode) &nbsp;|&nbsp; {ts}
</div>
</body>
</html>""".format(
        route=route_name, bg=BG, tx=C_TEXT, font=FONT, mu=C_MUTED, ts=ts,
        cards=cards_html, rc=rc_html, svg=svg_html, table=table_html
    )

    with open(out_file,"w",encoding="utf-8") as f:
        f.write(html)
    print("HTML report saved: {}".format(out_file))
    return out_file


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    route_name, stops = collect_input()
    stops = classify_stops(stops)
    print_report(route_name, stops)

    print(DIVIDER)
    gen = ask("\nGenerate offline HTML report? (y/n)", default="y").lower()
    if gen in ("y","yes",""):
        out = generate_html_report(route_name, stops)
        print("\nOpen '{}' in any browser to view the visual report.".format(out))
    else:
        print("HTML report skipped.")
    print()


if __name__ == "__main__":
    main()