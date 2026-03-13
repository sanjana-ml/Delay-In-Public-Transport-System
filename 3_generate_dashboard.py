"""
3_generate_dashboard.py
-----------------------
Reads transport_data_processed.csv -> offline_dashboard.html
Libraries: pandas, matplotlib, base64, io.
Zero external dependencies. Fully offline.

NEW: Delay Propagation Map section -- SVG timelines per route.
"""

import base64
import io
import sys
import json
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from datetime import datetime

INPUT_FILE  = "transport_data_processed.csv"
OUTPUT_FILE = "offline_dashboard.html"

CAUSE_DWELL      = "Excessive Stop Dwell Time"
CAUSE_TURNAROUND = "Vehicle Turnaround Delay"
CAUSE_CONGESTION = "Route Congestion Pattern"
CAUSE_TIMETABLE  = "Unrealistic Timetable"
CAUSE_ON_TIME    = "On Time"
DELAY_CAUSES     = [CAUSE_CONGESTION, CAUSE_DWELL, CAUSE_TIMETABLE, CAUSE_TURNAROUND]
ALL_CAUSES       = DELAY_CAUSES + [CAUSE_ON_TIME]

COLORS = {
    CAUSE_DWELL:      "#ff6b6b",
    CAUSE_TURNAROUND: "#ffd93d",
    CAUSE_CONGESTION: "#6bcb77",
    CAUSE_TIMETABLE:  "#4d96ff",
    CAUSE_ON_TIME:    "#888888",
}
SHORT = {
    CAUSE_DWELL:      "Dwell",
    CAUSE_TURNAROUND: "Turnaround",
    CAUSE_CONGESTION: "Congestion",
    CAUSE_TIMETABLE:  "Timetable",
    CAUSE_ON_TIME:    "On Time",
}

BG       = "#0f1117"
BG_CARD  = "#1a1d27"
BG_TH    = "#252836"
BG_NAV   = "#13161f"
C_TEXT   = "#e6e6e6"
C_MUTED  = "#8b8fa3"
C_BORDER = "#2a2d3e"
SHADOW   = "0 4px 20px rgba(0,0,0,0.4)"
RADIUS   = "12px"
FONT     = "'Segoe UI', system-ui, -apple-system, sans-serif"
CH_BG    = "#0d0f18"
CH_GRID  = "#1a1d2e"

def delay_color(d):
    if d <= 2:  return "#6bcb77"
    if d <= 5:  return "#ffd93d"
    if d <= 10: return "#ff9f43"
    return "#ff6b6b"

def delay_label(d):
    if d <= 2:  return "On Time"
    if d <= 5:  return "Minor Delay"
    if d <= 10: return "Moderate Delay"
    return "Severe Delay"

def node_size(d):
    if d <= 2:  return 16
    if d <= 5:  return 22
    if d <= 10: return 28
    return 34

# ── Data ──────────────────────────────────────────────────────────────────────

def load_data():
    try:
        df = pd.read_csv(INPUT_FILE)
    except FileNotFoundError:
        print("ERROR: '{}' not found. Run 2_process_logic.py first.".format(INPUT_FILE))
        sys.exit(1)
    required = {"Attributed_Cause","Route_ID","Stop_ID","Actual_Arrival",
                "Scheduled_Arrival","Trip_ID","Stop_Sequence",
                "Scheduled_Departure","Actual_Departure"}
    missing = required - set(df.columns)
    if missing:
        print("ERROR: Missing columns: {}".format(missing))
        sys.exit(1)
    for col in ["Actual_Arrival","Scheduled_Arrival","Actual_Departure","Scheduled_Departure"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["Delay_Min"] = (
        (df["Actual_Arrival"] - df["Scheduled_Arrival"])
        .dt.total_seconds().div(60).clip(lower=0).fillna(0)
    )
    return df

def pivot_cause(df, group_col):
    p = df.groupby([group_col,"Attributed_Cause"]).size().unstack(fill_value=0)
    for c in ALL_CAUSES:
        if c not in p.columns: p[c] = 0
    p = p[ALL_CAUSES]
    p["Total_Records"] = p.sum(axis=1)
    p["Total_Delay"]   = df.groupby(group_col)["Delay_Min"].sum().round(1)
    def top_cause(row):
        d = {c: row[c] for c in DELAY_CAUSES}
        b = max(d, key=d.get)
        return b if d[b] > 0 else CAUSE_ON_TIME
    p["Top_Cause"] = p.apply(top_cause, axis=1)
    return p.reset_index()

def build_propagation_data(df):
    routes_data = []
    fmt_dt = lambda dt: dt.strftime("%H:%M:%S") if pd.notna(dt) else "N/A"
    for route_id, rdf in df.groupby("Route_ID"):
        trip_delays = rdf.groupby("Trip_ID")["Delay_Min"].sum()
        if trip_delays.empty: continue
        worst = trip_delays.idxmax()
        tdf   = rdf[rdf["Trip_ID"]==worst].sort_values("Stop_Sequence")
        stops = []
        for _, row in tdf.iterrows():
            d = round(float(row["Delay_Min"]),1)
            stops.append({
                "stop_id":    str(row["Stop_ID"]),
                "seq":        int(row["Stop_Sequence"]),
                "delay":      d,
                "color":      delay_color(d),
                "size":       node_size(d),
                "label":      delay_label(d),
                "sched_arr":  fmt_dt(row["Scheduled_Arrival"]),
                "actual_arr": fmt_dt(row["Actual_Arrival"]),
                "sched_dep":  fmt_dt(row["Scheduled_Departure"]),
                "actual_dep": fmt_dt(row["Actual_Departure"]),
                "cause":      str(row["Attributed_Cause"]),
            })
        routes_data.append({"route_id":route_id,"trip_id":worst,"stops":stops})
    return routes_data

# ── Charts ────────────────────────────────────────────────────────────────────

def to_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf,format="png",dpi=140,bbox_inches="tight",facecolor=fig.get_facecolor())
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return data

def style_ax(ax, fig):
    fig.patch.set_facecolor(CH_BG)
    ax.set_facecolor(CH_BG)
    for sp in ["top","right"]: ax.spines[sp].set_visible(False)
    for sp in ["left","bottom"]: ax.spines[sp].set_color(CH_GRID)
    ax.tick_params(colors=C_TEXT,labelsize=8.5)
    ax.yaxis.grid(True,color=CH_GRID,linewidth=0.6,zorder=0)
    ax.set_axisbelow(True)

def chart_cause_bars(df):
    """Horizontal bar: incident count + avg delay in minutes per cause."""
    causes  = ALL_CAUSES
    counts  = [len(df[df["Attributed_Cause"]==c]) for c in causes]
    avg_del = [round(df[df["Attributed_Cause"]==c]["Delay_Min"].mean(), 1)
               if len(df[df["Attributed_Cause"]==c]) else 0 for c in causes]
    labels  = [SHORT[c] for c in causes]
    cols    = [COLORS[c] for c in causes]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 3.8))
    fig.patch.set_facecolor(CH_BG)

    # Left: incident count
    style_ax(ax1, fig)
    bars = ax1.barh(labels, counts, color=cols, height=0.5, edgecolor="none", zorder=3)
    for bar, v in zip(bars, counts):
        ax1.text(bar.get_width() + max(counts)*0.02,
                 bar.get_y() + bar.get_height()/2,
                 str(v), va="center", ha="left",
                 color=C_TEXT, fontsize=9, fontweight="700")
    ax1.set_title("Incidents by Cause", color=C_TEXT, fontsize=11,
                  fontweight="bold", pad=8, loc="left")
    ax1.set_xlabel("Number of stops", color=C_MUTED, fontsize=9)
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.set_xlim(0, max(counts)*1.2 if max(counts) else 1)

    # Right: avg delay in minutes
    style_ax(ax2, fig)
    bars2 = ax2.barh(labels, avg_del, color=cols, height=0.5, edgecolor="none", zorder=3)
    for bar, v in zip(bars2, avg_del):
        ax2.text(bar.get_width() + (max(avg_del) or 1)*0.02,
                 bar.get_y() + bar.get_height()/2,
                 "{:.1f} min".format(v), va="center", ha="left",
                 color=C_TEXT, fontsize=9, fontweight="700")
    ax2.set_title("Avg Delay per Cause", color=C_TEXT, fontsize=11,
                  fontweight="bold", pad=8, loc="left")
    ax2.set_xlabel("Average delay (minutes)", color=C_MUTED, fontsize=9)
    ax2.set_xlim(0, (max(avg_del) or 1)*1.25)

    fig.tight_layout(pad=1.4)
    return to_b64(fig)


def chart_route_avg_delay(df):
    """Bar chart: avg delay in minutes per route."""
    route_stats = df.groupby("Route_ID")["Delay_Min"].agg(["mean","max","count"]).reset_index()
    route_stats.columns = ["Route_ID","Avg","Max","Count"]
    route_stats = route_stats.sort_values("Route_ID")
    routes = route_stats["Route_ID"].tolist()
    x      = list(range(len(routes)))

    fig, ax = plt.subplots(figsize=(8, 3.8))
    style_ax(ax, fig)

    # Grouped bars: avg delay and max delay
    w = 0.35
    bar1 = ax.bar([i-w/2 for i in x], route_stats["Avg"].tolist(),
                  width=w, color="#4d96ff", edgecolor="none", zorder=3, label="Avg Delay")
    bar2 = ax.bar([i+w/2 for i in x], route_stats["Max"].tolist(),
                  width=w, color="#ff6b6b", edgecolor="none", zorder=3, label="Max Delay")

    # Value labels
    for bar in bar1:
        h = bar.get_height()
        ax.text(bar.get_x()+bar.get_width()/2, h+0.1,
                "{:.1f}m".format(h), ha="center", va="bottom",
                color="#4d96ff", fontsize=8, fontweight="700")
    for bar in bar2:
        h = bar.get_height()
        ax.text(bar.get_x()+bar.get_width()/2, h+0.1,
                "{:.1f}m".format(h), ha="center", va="bottom",
                color="#ff6b6b", fontsize=8, fontweight="700")

    ax.set_xticks(x)
    ax.set_xticklabels(routes, color=C_TEXT, fontsize=9)
    ax.set_title("Avg & Max Delay by Route", color=C_TEXT, fontsize=12,
                 fontweight="bold", pad=10, loc="left")
    ax.set_ylabel("Delay (minutes)", color=C_MUTED, fontsize=9)
    ax.legend(loc="upper right", framealpha=0.2, labelcolor=C_TEXT,
              fontsize=8, facecolor=BG_CARD, edgecolor=C_BORDER)
    fig.tight_layout(pad=1.4)
    return to_b64(fig)

# ── HTML helpers ──────────────────────────────────────────────────────────────

def pill(cause):
    c = COLORS.get(cause,C_MUTED)
    t = SHORT.get(cause,cause)
    return ('<span class="pill" style="--pc:{c};" '
            'onmouseover="this.style.boxShadow=\'0 0 8px {c}\'" '
            'onmouseout="this.style.boxShadow=\'none\'">{t}</span>').format(c=c,t=t)

def num_cell(v,cause):
    if v==0: return '<td style="text-align:center;color:{};font-size:12px;">-</td>'.format(C_MUTED)
    c = COLORS.get(cause,C_TEXT)
    return '<td style="text-align:center;color:{c};font-weight:700;">{v}</td>'.format(c=c,v=v)

def fmt_delay(minutes):
    m = round(float(minutes), 1)
    if m < 60:
        return "{:.1f} min".format(m)
    return "{} hr {:.0f} min".format(int(m//60), m%60)


def build_cards(df):
    total_rows  = len(df)
    avg_delay   = round(df["Delay_Min"].mean(), 1)
    max_delay   = round(df["Delay_Min"].max(), 1)
    on_time_n   = len(df[df["Attributed_Cause"]==CAUSE_ON_TIME])
    on_time_pct = round(on_time_n/total_rows*100,1) if total_rows else 0
    delayed     = df[df["Attributed_Cause"]!=CAUSE_ON_TIME]["Attributed_Cause"].value_counts()
    top_cause   = delayed.index[0] if len(delayed) else "N/A"
    top_count   = int(delayed.iloc[0]) if len(delayed) else 0
    top_color   = COLORS.get(top_cause,C_TEXT)
    top_short   = SHORT.get(top_cause,top_cause)
    def card(anchor,emoji,label,vid,value,unit,color,note,dms):
        return """
        <div class="card fade-card" style="animation-delay:{dms}ms;border-top:3px solid {c};"
             onclick="document.querySelector('#{a}').scrollIntoView({{behavior:'smooth'}})">
          <div class="card-icon">{e}</div>
          <div style="display:flex;align-items:baseline;gap:5px;margin-bottom:4px;">
            <div class="card-val" id="{vid}" data-target="{v}" style="color:{c};">{v}</div>
            <div style="font-size:13px;font-weight:600;color:{c};">{u}</div>
          </div>
          <div class="card-label">{l}</div>
          <div class="card-note">{n}</div>
        </div>""".format(a=anchor,e=emoji,l=label,vid=vid,v=value,u=unit,c=color,n=note,dms=dms)
    return (
        '<div class="cards-row">'
        + card("summary","📋","Total Stop Visits","cnt-records",total_rows,"stops","#6bcb77","records analysed",0)
        + card("summary","⏱","Avg Arrival Delay","cnt-avg",avg_delay,"min","#6bcbff","per stop visit",150)
        + card("summary","📈","Max Delay Recorded","cnt-max",max_delay,"min","#ff9f43","worst single stop",300)
        + card("summary","🚨","Most Common Cause","cnt-top",top_count,"events",top_color,top_short,450)
        + card("summary","✅","On-Time Rate","cnt-ontime",on_time_pct,"%","#4ade80","of all stop visits",600)
        + '</div>'
    )

def build_expanded_detail(gdf, gval, tc, avg_d, max_d):
    """Compact 2-point expanded panel: top 2 distinct RCD lines + recommendation."""
    has_rcd = "Root_Cause_Detail" in gdf.columns
    delayed = gdf[gdf["Attributed_Cause"] != CAUSE_ON_TIME]

    # ── Top 2 distinct root cause lines ──────────────────────────────────────
    rcd_lines = ""
    if has_rcd and not delayed.empty:
        seen = set()
        count = 0
        for rcd_text in delayed["Root_Cause_Detail"].tolist():
            key = str(rcd_text)[:55]
            if key in seen or count >= 2:
                continue
            seen.add(key)
            count += 1
            rcd_lines += (
                '<div style="display:flex;align-items:flex-start;gap:6px;margin-bottom:5px;">'
                '<span style="color:#a78bfa;flex-shrink:0;">&#8227;</span>'
                '<span style="color:#c9c9d4;font-size:11px;line-height:1.5;">{}</span>'
                '</div>'
            ).format(str(rcd_text))

    # ── Recommendation ────────────────────────────────────────────────────────
    RECS = {
        CAUSE_CONGESTION:  "Review signal timings and add buffer time at high-delay stops. Consider bus priority lanes to reduce propagation.",
        CAUSE_DWELL:       "Investigate boarding bottlenecks — consider pre-ticketing, platform improvements, or longer scheduled dwell.",
        CAUSE_TIMETABLE:   "Revise timetable to reflect realistic urban speeds (15–25 km/h). This is a planning failure, not an operational one.",
        CAUSE_TURNAROUND:  "Review depot dispatch and crew changeover procedures. Late first-stop departures propagate delays across the full trip.",
        CAUSE_ON_TIME:     "Performing within tolerance. Continue monitoring during peak periods.",
    }
    rec_text = RECS.get(tc, "Review operational data for further insight.")

    html = (
        '<div style="font-size:11px;line-height:1.6;padding:2px 0;">'
        '{rcd_lines}'
        '<div style="border-top:1px solid #2a2d3e;margin:8px 0 6px;"></div>'
        '<div style="color:#6bcb77;font-weight:700;margin-bottom:3px;">Recommendation</div>'
        '<div style="color:#c9c9d4;">{rec_text}</div>'
        '</div>'
    ).format(
        rcd_lines=rcd_lines or '<span style="color:#8b8fa3;">No delay records.</span>',
        rec_text=rec_text,
    )
    return html


def build_table(df, group_col, section_id, section_title, max_rows=None):
    piv = pivot_cause(df,group_col).sort_values("Total_Delay",ascending=False)
    if max_rows: piv = piv.head(max_rows)

    # Pre-compute most common root cause detail per group (if column exists)
    has_rcd = "Root_Cause_Detail" in df.columns
    rcd_map = {}
    if has_rcd:
        for gval, gdf in df.groupby(group_col):
            delayed = gdf[gdf["Attributed_Cause"] != CAUSE_ON_TIME]
            if not delayed.empty:
                top = delayed["Root_Cause_Detail"].value_counts()
                rcd_map[gval] = top.index[0] if len(top) else ""
            else:
                rcd_map[gval] = ""

    def th(label,color=C_MUTED):
        return ('<th style="padding:11px 14px;font-size:11px;font-weight:700;'
                'letter-spacing:0.06em;text-transform:uppercase;'
                'background:{bg};color:{c};text-align:center;">{l}</th>'
                ).format(bg=BG_TH,c=color,l=label)

    n_cols = 4 + len(DELAY_CAUSES) + 1  # group + records + delay + cause + each delay cause + ontime
    head = ("<tr>"
            +'<th style="padding:11px 14px;font-size:11px;font-weight:700;letter-spacing:0.06em;'
             'text-transform:uppercase;background:{};color:{};text-align:left;">{}</th>'.format(
                BG_TH,C_MUTED,group_col.replace("_"," "))
            +th("Records")+th("Avg Delay","#6bcbff")+th("Max Delay","#ff9f43")+th("Top Cause"))
    for c in DELAY_CAUSES: head += th(SHORT[c],COLORS[c])
    head += th("On Time",COLORS[CAUSE_ON_TIME])
    if has_rcd:
        head += th("Root Cause Detail","#a78bfa")
    head += "</tr>"

    rows = ""
    for _,row in piv.iterrows():
        gval  = row[group_col]
        tc    = row["Top_Cause"]
        row_id = "rcd-{}-{}".format(section_id, str(gval).replace(" ","_"))
        cells = '<td style="padding:10px 14px;font-weight:700;color:{};font-size:13px;">{}</td>'.format(C_TEXT,gval)
        cells += '<td style="text-align:center;color:{};">{}</td>'.format(C_MUTED,int(row["Total_Records"]))
        avg_d = round(row["Total_Delay"]/row["Total_Records"],1) if row["Total_Records"]>0 else 0
        max_d = round(df[df[group_col]==gval]["Delay_Min"].max(),1) if group_col in df.columns else 0
        cells += '<td style="text-align:center;font-weight:700;color:#6bcbff;">{:.1f} min</td>'.format(avg_d)
        cells += '<td style="text-align:center;font-weight:700;color:#ff9f43;">{:.1f} min</td>'.format(max_d)
        cells += '<td style="text-align:center;">{}</td>'.format(pill(tc))
        for c in DELAY_CAUSES: cells += num_cell(int(row[c]),c)
        cells += num_cell(int(row[CAUSE_ON_TIME]),CAUSE_ON_TIME)

        if has_rcd:
            rcd      = rcd_map.get(gval,"")
            tc_color = COLORS.get(tc, C_MUTED)
            gdf      = df[df[group_col] == gval]
            avg_d    = round(row["Total_Delay"]/row["Total_Records"],1) if row["Total_Records"]>0 else 0
            max_d_v  = round(df[df[group_col]==gval]["Delay_Min"].max(),1)
            expanded = build_expanded_detail(gdf, gval, tc, avg_d, max_d_v)
            short_lbl = (rcd[:60]+"…") if len(rcd)>60 else (rcd if rcd else "Click to expand details")
            cells += (
                '<td style="padding:8px 14px;max-width:300px;">'
                '<div class="rcd-summary" onclick="toggleRcd(\'{rid}\')" '
                'style="cursor:pointer;display:flex;align-items:flex-start;gap:7px;">'
                '<span style="color:{tc};font-size:14px;flex-shrink:0;'
                'transition:transform 0.2s;" id="arr-{rid}">&#9656;</span>'
                '<span style="font-size:11px;color:{mu};line-height:1.4;">{short}</span>'
                '</div>'
                '<div id="{rid}" style="display:none;margin-top:8px;padding:12px 14px;'
                'background:#0d0f18;border-radius:8px;border-left:3px solid {tc};">'
                '{expanded}'
                '</div>'
                '</td>'
            ).format(
                rid=row_id, tc=tc_color, mu=C_MUTED,
                short=short_lbl, expanded=expanded
            )

        rows  += '<tr class="trow">{}</tr>'.format(cells)

    sub = ' <span style="font-size:12px;color:{};font-weight:400;">(Top {} by delay)</span>'.format(C_MUTED,max_rows) if max_rows else ""
    return """
    <div class="section-card" id="{sid}">
      <div class="section-title">{title}{sub}</div>
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;">{head}{rows}</table>
      </div>
    </div>""".format(sid=section_id,title=section_title,sub=sub,head=head,rows=rows)

def build_legend():
    items = ""
    for cause in ALL_CAUSES:
        c = COLORS[cause]
        items += ('<div style="display:flex;align-items:center;gap:8px;">'
                  '<div style="width:11px;height:11px;border-radius:3px;background:{c};"></div>'
                  '<span style="font-size:12px;color:{t};">{l}</span></div>').format(c=c,t=C_TEXT,l=cause)
    return ('<div style="display:flex;flex-wrap:wrap;gap:14px 28px;'
            'background:{bg};border-radius:10px;padding:14px 20px;'
            'margin-bottom:28px;box-shadow:{sh};">{items}</div>'
            ).format(bg=BG_CARD,sh=SHADOW,items=items)

# ── Propagation Map ───────────────────────────────────────────────────────────


def build_stop_timing_table(df):
    """
    Stop-level timing table showing scheduled vs actual arrival/departure
    and delay in minutes for the worst trip of each route.
    """
    # For each route get the worst trip (most total delay)
    df2 = df.copy()
    df2["Delay_Min"] = (
        (pd.to_datetime(df2["Actual_Arrival"]) - pd.to_datetime(df2["Scheduled_Arrival"]))
        .dt.total_seconds().div(60).clip(lower=0).fillna(0)
    )
    trip_totals = df2.groupby(["Route_ID","Trip_ID"])["Delay_Min"].sum()
    worst_trips = trip_totals.groupby(level=0).idxmax().apply(lambda x: x[1])

    rows_html = ""
    for route_id, trip_id in worst_trips.items():
        tdf = df2[(df2["Route_ID"]==route_id) & (df2["Trip_ID"]==trip_id)].sort_values("Stop_Sequence").head(2)
        for _, row in tdf.iterrows():
            d     = round(row["Delay_Min"], 1)
            cause = row["Attributed_Cause"]
            col   = COLORS.get(cause, C_MUTED)
            d_col = delay_color(d)

            def fmt_t(col_name):
                try:
                    return pd.to_datetime(row[col_name]).strftime("%H:%M")
                except:
                    return "N/A"

            delay_str = "{:.1f} min".format(d) if d > 0 else "0 min"

            rows_html += (
                '<tr class="trow">' +
                '<td style="padding:9px 14px;font-weight:700;color:{ct};">{rid}</td>'.format(ct=C_TEXT, rid=route_id) +
                '<td style="padding:9px 14px;color:{mu};font-size:12px;">{tid}</td>'.format(mu=C_MUTED, tid=trip_id) +
                '<td style="padding:9px 14px;text-align:center;color:{ct};">{sid}</td>'.format(ct=C_TEXT, sid=row["Stop_ID"]) +
                '<td style="padding:9px 14px;text-align:center;color:{mu};">{sa}</td>'.format(mu=C_MUTED, sa=fmt_t("Scheduled_Arrival")) +
                '<td style="padding:9px 14px;text-align:center;color:{ct};font-weight:600;">{aa}</td>'.format(ct=C_TEXT, aa=fmt_t("Actual_Arrival")) +
                '<td style="padding:9px 14px;text-align:center;color:{mu};">{sd}</td>'.format(mu=C_MUTED, sd=fmt_t("Scheduled_Departure")) +
                '<td style="padding:9px 14px;text-align:center;color:{ct};font-weight:600;">{ad}</td>'.format(ct=C_TEXT, ad=fmt_t("Actual_Departure")) +
                '<td style="padding:9px 14px;text-align:center;font-weight:700;color:{dc};">{ds}</td>'.format(dc=d_col, ds=delay_str) +
                '<td style="padding:9px 14px;text-align:center;">{pill}</td>'.format(pill=pill(cause)) +
                '</tr>'
            )

    def th(label, color=C_MUTED, align="center"):
        return ('<th style="padding:10px 14px;font-size:11px;font-weight:700;'
                'letter-spacing:0.06em;text-transform:uppercase;'
                'background:{bg};color:{c};text-align:{a};">{l}</th>'
                ).format(bg=BG_TH, c=color, l=label, a=align)

    head = (
        "<tr>" +
        th("Route", align="left") +
        th("Trip ID", align="left") +
        th("Stop") +
        th("Sched Arr", "#8b8fa3") +
        th("Actual Arr", "#6bcbff") +
        th("Sched Dep", "#8b8fa3") +
        th("Actual Dep", "#6bcbff") +
        th("Delay", "#ff9f43") +
        th("Cause") +
        "</tr>"
    )

    return """
    <div class="section-card" id="timings">
      <div class="section-title">Arrival &amp; Departure Times
        <span style="font-size:12px;color:{mu};font-weight:400;">
          (2 stops per route · worst trip · scheduled vs actual)
        </span>
      </div>
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;">{head}{rows}</table>
      </div>
    </div>""".format(mu=C_MUTED, head=head, rows=rows_html)

def build_lookup_panel(df):
    """
    Stop Lookup Panel — a clearly visible table panel where users type a Route ID
    and Stop ID to instantly fetch all matching records with full details.
    Sits as its own titled section in the dashboard.
    """
    # Serialise the full dataset into embedded JSON for client-side lookup
    df2 = df.copy()
    for col in ["Actual_Arrival","Scheduled_Arrival","Actual_Departure","Scheduled_Departure"]:
        df2[col] = pd.to_datetime(df2[col], errors="coerce")
    df2["Delay_Min"] = (
        (df2["Actual_Arrival"] - df2["Scheduled_Arrival"])
        .dt.total_seconds().div(60).clip(lower=0).fillna(0).round(2)
    )
    fmt_t = lambda v: v.strftime("%H:%M") if pd.notna(v) else "N/A"
    fmt_full = lambda v: v.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(v) else "N/A"

    records = []
    for _, row in df2.iterrows():
        d = round(float(row["Delay_Min"]), 2)
        records.append({
            "route":      str(row["Route_ID"]),
            "trip":       str(row["Trip_ID"]),
            "stop":       str(row["Stop_ID"]),
            "seq":        int(row["Stop_Sequence"]),
            "sched_arr":  fmt_t(row["Scheduled_Arrival"]),
            "actual_arr": fmt_t(row["Actual_Arrival"]),
            "sched_dep":  fmt_t(row["Scheduled_Departure"]),
            "actual_dep": fmt_t(row["Actual_Departure"]),
            "date":       fmt_full(row["Scheduled_Arrival"])[:10],
            "delay":      d,
            "cause":      str(row["Attributed_Cause"]),
            "rcd":        str(row.get("Root_Cause_Detail","")) if "Root_Cause_Detail" in df2.columns else "",
        })

    dataset_json = json.dumps(records, ensure_ascii=False)
    colors_json  = json.dumps(COLORS, ensure_ascii=False)
    short_json   = json.dumps(SHORT,  ensure_ascii=False)

    # Build route and stop hint lists for placeholder text
    all_routes = sorted(df2["Route_ID"].unique().tolist())
    all_stops  = sorted(df2["Stop_ID"].unique().tolist())
    route_hint = ", ".join(all_routes[:5])
    stop_hint  = ", ".join(all_stops[:6])

    TH = ('padding:11px 14px;font-size:11px;font-weight:700;letter-spacing:0.06em;'
          'text-transform:uppercase;background:{bg};color:{{c}};text-align:{{a}};white-space:nowrap;'
          ).format(bg=BG_TH)

    return """
<div class="section-card" id="lookup" style="margin-bottom:32px;">

  <!-- Section header -->
  <div style="padding:22px 24px 0;">
    <div style="font-size:16px;font-weight:800;color:{ct};margin-bottom:4px;">
      🔎 Stop Record Lookup
    </div>
    <div style="font-size:13px;color:{mu};margin-bottom:20px;">
      Enter a <strong style="color:{ct};">Route ID</strong> and / or
      <strong style="color:{ct};">Stop ID</strong> below to fetch all matching
      records — scheduled vs actual times, delay duration, and delay cause.
    </div>

    <!-- Input row -->
    <div style="display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;
                background:#0d0f18;border-radius:10px;padding:18px 20px;
                border:1px solid {border};margin-bottom:0;">

      <!-- Route ID -->
      <div style="display:flex;flex-direction:column;gap:6px;flex:1;min-width:160px;">
        <label style="font-size:11px;font-weight:800;color:{mu};letter-spacing:0.08em;
                      text-transform:uppercase;">Route ID</label>
        <input id="lk-route" type="text" placeholder="e.g. {route_hint_first}"
          style="background:#1a1d27;border:1.5px solid {border};color:{ct};
                 border-radius:8px;padding:11px 14px;font-size:14px;
                 font-weight:600;outline:none;transition:border-color .2s;
                 font-family:inherit;"
          onfocus="this.style.borderColor='#4d96ff'"
          onblur="this.style.borderColor='{border}'"
          onkeydown="if(event.key==='Enter') lkSearch()" />
        <span style="font-size:11px;color:{mu};">Available: {route_hint}</span>
      </div>

      <!-- Stop ID -->
      <div style="display:flex;flex-direction:column;gap:6px;flex:1;min-width:160px;">
        <label style="font-size:11px;font-weight:800;color:{mu};letter-spacing:0.08em;
                      text-transform:uppercase;">Stop ID</label>
        <input id="lk-stop" type="text" placeholder="e.g. {stop_hint_first}"
          style="background:#1a1d27;border:1.5px solid {border};color:{ct};
                 border-radius:8px;padding:11px 14px;font-size:14px;
                 font-weight:600;outline:none;transition:border-color .2s;
                 font-family:inherit;"
          onfocus="this.style.borderColor='#4d96ff'"
          onblur="this.style.borderColor='{border}'"
          onkeydown="if(event.key==='Enter') lkSearch()" />
        <span style="font-size:11px;color:{mu};">Available: {stop_hint}</span>
      </div>

      <!-- Buttons -->
      <div style="display:flex;gap:10px;padding-bottom:18px;">
        <button onclick="lkSearch()"
          style="background:linear-gradient(135deg,#4d96ff 0%,#6bcb77 100%);
                 color:#0f1117;border:none;border-radius:8px;padding:11px 28px;
                 font-size:14px;font-weight:800;cursor:pointer;letter-spacing:0.02em;
                 font-family:inherit;transition:opacity .2s;"
          onmouseover="this.style.opacity='0.85'"
          onmouseout="this.style.opacity='1'">
          Fetch Records
        </button>
        <button onclick="lkClear()"
          style="background:#252836;color:{mu};border:1px solid {border};
                 border-radius:8px;padding:11px 20px;font-size:13px;font-weight:600;
                 cursor:pointer;font-family:inherit;">
          Clear
        </button>
      </div>
    </div>
  </div>

  <!-- Summary stats strip (hidden until search) -->
  <div id="lk-stats" style="display:none;margin:18px 24px 0;padding:16px 20px;
    background:#0d0f18;border-radius:10px;border:1px solid {border};
    display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:16px;">
  </div>

  <!-- No-match / suggestions message -->
  <div id="lk-msg" style="display:none;margin:18px 24px 0;padding:14px 18px;
    background:#1a150a;border-radius:10px;border:1px solid #ffd93d55;
    color:#ffd93d;font-size:13px;line-height:1.7;">
  </div>

  <!-- Results table -->
  <div id="lk-table-wrap" style="display:none;padding:18px 24px 24px;">
    <div id="lk-count" style="font-size:12px;color:{mu};margin-bottom:12px;"></div>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:12.5px;">
        <thead>
          <tr>
            <th style="{ths}text-align:left;color:{mu};">Route</th>
            <th style="{ths}color:{mu};">Stop</th>
            <th style="{ths}color:{mu};">Seq</th>
            <th style="{ths}text-align:left;color:{mu};">Trip ID</th>
            <th style="{ths}color:#8b8fa3;">Date</th>
            <th style="{ths}color:#8b8fa3;">Sched&nbsp;Arr</th>
            <th style="{ths}color:#6bcbff;">Actual&nbsp;Arr</th>
            <th style="{ths}color:#8b8fa3;">Sched&nbsp;Dep</th>
            <th style="{ths}color:#6bcbff;">Actual&nbsp;Dep</th>
            <th style="{ths}color:#ff9f43;">Delay</th>
            <th style="{ths}">Cause</th>
            <th style="{ths}text-align:left;color:#a78bfa;min-width:200px;">Root Cause Detail</th>
          </tr>
        </thead>
        <tbody id="lk-tbody"></tbody>
      </table>
    </div>
    <div id="lk-pages" style="margin-top:14px;display:flex;gap:8px;
      align-items:center;flex-wrap:wrap;"></div>
  </div>

  <!-- Idle state prompt -->
  <div id="lk-idle" style="padding:36px 24px;text-align:center;">
    <div style="font-size:32px;margin-bottom:10px;">🚌</div>
    <div style="font-size:14px;color:{mu};">
      Type a <strong style="color:{ct};">Route ID</strong> (e.g. <code style="color:#4d96ff;">{route_hint_first}</code>)
      and / or <strong style="color:{ct};">Stop ID</strong>
      (e.g. <code style="color:#4d96ff;">{stop_hint_first}</code>)
      above, then click <strong style="color:#6bcb77;">Fetch Records</strong>.
    </div>
    <div style="font-size:12px;color:{mu};margin-top:8px;">
      Leave one field blank to search by route only or stop only.
    </div>
  </div>

</div>

<script>
(function(){{
  var DATA   = {dataset};
  var COLORS = {colors};
  var SHORT  = {short};
  var PAGE   = 2;
  var cur    = [];
  var page   = 1;

  function dc(d){{
    if(d<=2)  return '#6bcb77';
    if(d<=5)  return '#ffd93d';
    if(d<=10) return '#ff9f43';
    return '#ff6b6b';
  }}

  function pillH(cause){{
    var c=COLORS[cause]||'#8b8fa3', t=SHORT[cause]||cause;
    return '<span style="background:'+c+'22;color:'+c+';border:1px solid '+c+'44;'+
           'border-radius:5px;padding:2px 9px;font-size:11px;font-weight:700;">'+t+'</span>';
  }}

  function stat(label,val,col){{
    return '<div style="display:flex;flex-direction:column;gap:4px;">'+
      '<span style="font-size:10px;color:#8b8fa3;text-transform:uppercase;'+
      'letter-spacing:0.07em;font-weight:700;">'+label+'</span>'+
      '<span style="font-size:20px;font-weight:800;color:'+(col||'#e6e6e6')+';">'+val+'</span>'+
      '</div>';
  }}

  function renderStats(rows){{
    var el=document.getElementById('lk-stats');
    if(!rows.length){{el.style.display='none';return;}}
    var delays=rows.map(function(r){{return r.delay;}});
    var avg=(delays.reduce(function(a,b){{return a+b;}},0)/rows.length).toFixed(1);
    var max=Math.max.apply(null,delays).toFixed(1);
    var ot=rows.filter(function(r){{return r.cause==='On Time';}}).length;
    var pct=((ot/rows.length)*100).toFixed(0);
    var hc={{}};
    rows.forEach(function(r){{if(r.delay>2)hc[r.delay>0?('0'+r.seq).slice(-2):'']=(hc[('0'+r.seq).slice(-2)]||0)+1;}});
    var causeCounts={{}};
    rows.forEach(function(r){{if(r.cause!=='On Time')causeCounts[r.cause]=(causeCounts[r.cause]||0)+1;}});
    var topC='On Time',topN=0;
    Object.keys(causeCounts).forEach(function(c){{if(causeCounts[c]>topN){{topN=causeCounts[c];topC=c;}}}});
    el.innerHTML=
      stat('Total Records', rows.length.toLocaleString(), '#6bcb77')+
      stat('Avg Delay', avg+' min', '#6bcbff')+
      stat('Max Delay', max+' min', '#ff6b6b')+
      stat('On-Time', pct+'%', '#4ade80')+
      stat('Top Cause', SHORT[topC]||topC, COLORS[topC]||'#e6e6e6');
    el.style.display='grid';
  }}

  function renderTable(rows, p){{
    var tbody=document.getElementById('lk-tbody');
    var slice=rows.slice((p-1)*PAGE, p*PAGE);
    tbody.innerHTML=slice.map(function(r){{
      var d=r.delay, dc_=dc(d);
      var ds=d>0?d.toFixed(1)+' min':'0 min';
      return '<tr class="lk-tr">'+
        '<td style="padding:10px 14px;font-weight:700;color:#e6e6e6;">'+r.route+'</td>'+
        '<td style="padding:10px 14px;text-align:center;font-weight:700;color:#6bcbff;">'+r.stop+'</td>'+
        '<td style="padding:10px 14px;text-align:center;color:#8b8fa3;">'+r.seq+'</td>'+
        '<td style="padding:10px 14px;color:#8b8fa3;font-size:11px;">'+r.trip+'</td>'+
        '<td style="padding:10px 14px;text-align:center;color:#8b8fa3;">'+r.date+'</td>'+
        '<td style="padding:10px 14px;text-align:center;color:#8b8fa3;">'+r.sched_arr+'</td>'+
        '<td style="padding:10px 14px;text-align:center;color:#6bcbff;font-weight:600;">'+r.actual_arr+'</td>'+
        '<td style="padding:10px 14px;text-align:center;color:#8b8fa3;">'+r.sched_dep+'</td>'+
        '<td style="padding:10px 14px;text-align:center;color:#6bcbff;font-weight:600;">'+r.actual_dep+'</td>'+
        '<td style="padding:10px 14px;text-align:center;font-weight:800;font-size:13px;color:'+dc_+';">'+ds+'</td>'+
        '<td style="padding:10px 14px;text-align:center;">'+pillH(r.cause)+'</td>'+
        '<td style="padding:10px 14px;font-size:11px;color:#8b8fa3;line-height:1.5;max-width:240px;">'+
          (r.rcd||'—')+'</td>'+
        '</tr>';
    }}).join('');
  }}

  function renderPages(total, p){{
    var pages=Math.ceil(total/PAGE);
    var el=document.getElementById('lk-pages');
    if(pages<=1){{el.innerHTML='';return;}}
    var html='<span style="font-size:12px;color:#8b8fa3;margin-right:4px;">Page:</span>';
    for(var i=1;i<=pages;i++){{
      var active=i===p;
      html+='<button onclick="lkPage('+i+')" style="'+
        'background:'+(active?'#4d96ff':'#252836')+';'+
        'color:'+(active?'#0f1117':'#e6e6e6')+';'+
        'border:1px solid '+(active?'#4d96ff':'#2a2d3e')+';'+
        'border-radius:6px;padding:5px 12px;font-size:12px;font-weight:700;cursor:pointer;">'+i+'</button>';
    }}
    el.innerHTML=html;
  }}

  window.lkSearch = function(){{
    var rv = document.getElementById('lk-route').value.trim().toUpperCase();
    var sv = document.getElementById('lk-stop').value.trim().toUpperCase();
    var msg = document.getElementById('lk-msg');
    var idle= document.getElementById('lk-idle');

    if(!rv && !sv){{
      msg.innerHTML='<strong>Please enter a Route ID or Stop ID to search.</strong>';
      msg.style.display='block';
      document.getElementById('lk-table-wrap').style.display='none';
      document.getElementById('lk-stats').style.display='none';
      idle.style.display='none';
      return;
    }}

    var results = DATA.filter(function(r){{
      var rm = !rv || r.route.toUpperCase()===rv;
      var sm = !sv || r.stop.toUpperCase()===sv;
      return rm && sm;
    }});

    // Sort by date desc (most recent first), then by stop seq
    results.sort(function(a,b){{
      if(a.date!==b.date) return a.date<b.date?1:-1;
      return a.seq - b.seq;
    }});

    idle.style.display='none';
    msg.style.display='none';

    if(results.length===0){{
      // Build helpful suggestion
      var hint = '<strong>No records found';
      if(rv && sv) hint += ' for Route <em>'+rv+'</em> + Stop <em>'+sv+'</em>';
      else if(rv)  hint += ' for Route <em>'+rv+'</em>';
      else         hint += ' for Stop <em>'+sv+'</em>';
      hint += '.</strong><br/><br/>';

      if(rv){{
        var routeRows=DATA.filter(function(r){{return r.route.toUpperCase()===rv;}});
        if(routeRows.length>0){{
          var stops=[...new Set(routeRows.map(function(r){{return r.stop;}}))].sort();
          hint+='✅ Route <strong>'+rv+'</strong> exists. Its stops are: '+
                stops.map(function(s){{return '<code style="color:#6bcbff;">'+s+'</code>';}}).join(' &nbsp;')+'<br/>';
        }} else {{
          var allR=[...new Set(DATA.map(function(r){{return r.route;}}))].sort();
          hint+='❌ Route <strong>'+rv+'</strong> not found. Available routes: '+
                allR.map(function(r){{return '<code style="color:#6bcbff;">'+r+'</code>';}}).join(' &nbsp;')+'<br/>';
        }}
      }}
      if(sv){{
        var stopRows=DATA.filter(function(r){{return r.stop.toUpperCase()===sv;}});
        if(stopRows.length>0){{
          var routes=[...new Set(stopRows.map(function(r){{return r.route;}}))].sort();
          hint+='✅ Stop <strong>'+sv+'</strong> exists on routes: '+
                routes.map(function(r){{return '<code style="color:#6bcbff;">'+r+'</code>';}}).join(' &nbsp;');
        }} else {{
          var allS=[...new Set(DATA.map(function(r){{return r.stop;}}))].sort();
          hint+='❌ Stop <strong>'+sv+'</strong> not found. Available stops: '+
                allS.map(function(s){{return '<code style="color:#6bcbff;">'+s+'</code>';}}).join(' &nbsp;');
        }}
      }}
      msg.innerHTML=hint;
      msg.style.display='block';
      document.getElementById('lk-table-wrap').style.display='none';
      document.getElementById('lk-stats').style.display='none';
      return;
    }}

    cur=results; page=1;
    renderStats(results);
    renderTable(results, 1);
    renderPages(results.length, 1);

    var countEl=document.getElementById('lk-count');
    var label= (rv&&sv)? 'Route <strong style="color:#6bcb77;">'+rv+'</strong> · Stop <strong style="color:#6bcb77;">'+sv+'</strong>'
             : rv? 'Route <strong style="color:#6bcb77;">'+rv+'</strong>'
             : 'Stop <strong style="color:#6bcb77;">'+sv+'</strong>';
    countEl.innerHTML = label + ' — <strong style="color:#6bcb77;">'+results.length+'</strong> record(s) found'+
      (results.length>PAGE?' · showing '+PAGE+' per page':'')+ ' · sorted by date (most recent first)';

    document.getElementById('lk-table-wrap').style.display='block';
  }};

  window.lkClear = function(){{
    document.getElementById('lk-route').value='';
    document.getElementById('lk-stop').value='';
    showDefault();
  }};

  window.lkPage = function(p){{
    page=p;
    renderTable(cur,p);
    renderPages(cur.length,p);
    document.getElementById('lookup').scrollIntoView({{behavior:'smooth'}});
  }};

  function showDefault(){{
    var seen={{}};
    var def_rows=[];
    DATA.forEach(function(r){{
      if(!seen[r.route]) seen[r.route]=0;
      if(seen[r.route]<2){{ def_rows.push(r); seen[r.route]++; }}
    }});
    cur=def_rows; page=1;
    document.getElementById('lk-idle').style.display='none';
    document.getElementById('lk-msg').style.display='none';
    document.getElementById('lk-stats').style.display='none';
    var countEl=document.getElementById('lk-count');
    countEl.innerHTML='Showing <strong style="color:#6bcb77;">2 records per route</strong> (10 rows) &nbsp;·&nbsp; '
      +'<span style="color:#8b8fa3;">search above to filter any route or stop</span>';
    renderTable(def_rows,1);
    renderPages(def_rows.length,1);
    document.getElementById('lk-table-wrap').style.display='block';
  }}

  showDefault();
}})();
</script>
""".format(
        ct=C_TEXT, mu=C_MUTED, border=C_BORDER,
        route_hint=route_hint, route_hint_first=all_routes[0] if all_routes else "R-101",
        stop_hint=stop_hint,   stop_hint_first=all_stops[0]   if all_stops  else "S-01",
        dataset=dataset_json, colors=colors_json, short=short_json,
        ths=('padding:11px 14px;font-size:11px;font-weight:700;letter-spacing:0.06em;'
             'text-transform:uppercase;background:{};text-align:center;white-space:nowrap;'.format(BG_TH)),
    )


def build_propagation_section(routes_data):
    legend_html = """
    <div style="display:flex;flex-wrap:wrap;gap:18px;margin-bottom:24px;
                background:#13161f;border-radius:10px;padding:14px 20px;">
      <div style="display:flex;align-items:center;gap:7px;">
        <div style="width:13px;height:13px;border-radius:50%;background:#6bcb77;"></div>
        <span style="font-size:12px;color:#e6e6e6;">On Time (0-2m)</span></div>
      <div style="display:flex;align-items:center;gap:7px;">
        <div style="width:13px;height:13px;border-radius:50%;background:#ffd93d;"></div>
        <span style="font-size:12px;color:#e6e6e6;">Minor Delay (3-5m)</span></div>
      <div style="display:flex;align-items:center;gap:7px;">
        <div style="width:13px;height:13px;border-radius:50%;background:#ff9f43;"></div>
        <span style="font-size:12px;color:#e6e6e6;">Moderate Delay (6-10m)</span></div>
      <div style="display:flex;align-items:center;gap:7px;">
        <div style="width:13px;height:13px;border-radius:50%;background:#ff6b6b;"></div>
        <span style="font-size:12px;color:#e6e6e6;">Severe Delay (&gt;10m)</span></div>
    </div>"""

    cards_html = ""
    all_json   = json.dumps(routes_data, ensure_ascii=False)

    for route in routes_data:
        route_id = route["route_id"]
        trip_id  = route["trip_id"]
        stops    = route["stops"]
        n        = len(stops)
        if n == 0: continue

        PAD_L  = 55; PAD_R = 55; PAD_T = 72; PAD_B = 72; STEP = 108
        SVG_W  = PAD_L + PAD_R + STEP*(n-1) if n>1 else PAD_L+PAD_R+100
        LINE_Y = PAD_T + 18
        SVG_H  = PAD_T + PAD_B + 36

        def nx(i):
            return PAD_L + i*STEP if n>1 else PAD_L+50

        svg_lines = ""; svg_annots = ""; svg_nodes = ""

        # Lines between nodes
        for i in range(n-1):
            x1=nx(i); x2=nx(i+1); sl=x2-x1
            svg_lines += (
                '<line x1="{x1}" y1="{ly}" x2="{x2}" y2="{ly}" '
                'stroke="{c}" stroke-width="3" stroke-linecap="round" '
                'stroke-dasharray="{sl}" stroke-dashoffset="{sl}" '
                'style="animation:drawLine 0.4s ease forwards;animation-delay:{ad}ms;"/>'
            ).format(x1=x1,ly=LINE_Y,x2=x2,c=stops[i+1]["color"],sl=sl,ad=200+i*120)

        # Annotations
        for i in range(1,n):
            diff  = stops[i]["delay"] - stops[i-1]["delay"]
            mid_x = (nx(i-1)+nx(i))/2
            ann_y = LINE_Y - 18
            if diff >= 5:
                svg_annots += (
                    '<text x="{mx}" y="{ay}" text-anchor="middle" font-size="11" '
                    'font-weight="700" fill="#ff9f43" '
                    'style="opacity:0;animation:fadeIn 0.4s ease forwards;animation-delay:{ad}ms;">'
                    'zap +{d:.0f}m</text>'
                ).format(mx=mid_x,ay=ann_y,d=diff,ad=400+i*120)
            elif diff <= -3:
                svg_annots += (
                    '<text x="{mx}" y="{ay}" text-anchor="middle" font-size="11" '
                    'font-weight="700" fill="#6bcb77" '
                    'style="opacity:0;animation:fadeIn 0.4s ease forwards;animation-delay:{ad}ms;">'
                    'down {d:.0f}m</text>'
                ).format(mx=mid_x,ay=ann_y,d=abs(diff),ad=400+i*120)

        # Nodes
        for i,stop in enumerate(stops):
            x=nx(i); r=stop["size"]/2; col=stop["color"]; d=stop["delay"]
            ad=100+i*120
            # glow ring
            svg_nodes += (
                '<circle cx="{x}" cy="{ly}" r="{gr}" fill="none" stroke="{c}" '
                'stroke-width="1.5" '
                'style="opacity:0;animation:fadeScale 0.4s ease forwards;animation-delay:{ad}ms;"/>'
            ).format(x=x,ly=LINE_Y,gr=r+6,c=col,ad=ad)
            # main circle
            svg_nodes += (
                '<circle class="prop-node" cx="{x}" cy="{ly}" r="{r}" '
                'fill="{c}" stroke="{bg}" stroke-width="2.5" '
                'data-route="{rid}" data-idx="{idx}" '
                'style="cursor:pointer;filter:drop-shadow(0 0 5px {c}99);'
                'opacity:0;animation:fadeScale 0.4s ease forwards;animation-delay:{ad}ms;"/>'
            ).format(x=x,ly=LINE_Y,r=r,c=col,bg=BG_CARD,rid=route_id,idx=i,ad=ad)
            # stop label
            svg_nodes += (
                '<text x="{x}" y="{ly}" text-anchor="middle" font-size="11" fill="{mu}" '
                'style="opacity:0;animation:fadeIn 0.4s ease forwards;animation-delay:{ad}ms;">'
                '{sid}</text>'
            ).format(x=x,ly=LINE_Y+r+14,mu=C_MUTED,sid=stop["stop_id"],ad=ad)
            # delay label
            dt = "{:.0f}m".format(d) if d>0 else "0m"
            svg_nodes += (
                '<text x="{x}" y="{ly}" text-anchor="middle" font-size="12" '
                'font-weight="700" fill="{c}" '
                'style="opacity:0;animation:fadeIn 0.4s ease forwards;animation-delay:{ad}ms;">'
                '{dt}</text>'
            ).format(x=x,ly=LINE_Y+r+28,c=col,dt=dt,ad=ad)

        svg = (
            '<svg viewBox="0 0 {w} {h}" width="100%" xmlns="http://www.w3.org/2000/svg" '
            'style="overflow:visible;display:block;">'
            '<defs><style>'
            '@keyframes drawLine{{to{{stroke-dashoffset:0;}}}}'
            '@keyframes fadeScale{{from{{opacity:0;transform:scale(0.3);transform-box:fill-box;'
            'transform-origin:center;}}to{{opacity:1;transform:scale(1);transform-box:fill-box;'
            'transform-origin:center;}}}}'
            '@keyframes fadeIn{{from{{opacity:0;}}to{{opacity:1;}}}}'
            '.prop-node:hover{{filter:drop-shadow(0 0 12px currentColor) brightness(1.25)!important;}}'
            '</style></defs>'
            '{lines}{annots}{nodes}'
            '</svg>'
        ).format(w=SVG_W,h=SVG_H,lines=svg_lines,annots=svg_annots,nodes=svg_nodes)

        cards_html += """
        <div class="section-card prop-card" style="margin-bottom:18px;padding:22px 26px;">
          <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px;">
            <span style="font-size:16px;font-weight:800;color:{ct};">{rid}</span>
            <span style="font-size:12px;color:{mu};">Delay Propagation - Worst Trip</span>
          </div>
          <div style="font-size:11px;color:{mu};margin-bottom:18px;">
            Trip: <span style="color:{ct};font-weight:600;">{tid}</span>
            &nbsp;·&nbsp; {ns} stops analysed
          </div>
          <div style="overflow-x:auto;padding-bottom:10px;">{svg}</div>
        </div>""".format(ct=C_TEXT,rid=route_id,mu=C_MUTED,tid=trip_id,ns=n,svg=svg)

    # Tooltip div
    tooltip = """
    <div id="prop-tooltip" style="
      position:fixed;pointer-events:none;opacity:0;
      background:#1e2235;border:1px solid #3a3f58;border-radius:10px;
      padding:12px 16px;font-size:12px;color:#e6e6e6;
      box-shadow:0 8px 32px rgba(0,0,0,0.6);
      z-index:9999;min-width:210px;max-width:280px;
      transition:opacity 0.15s ease;line-height:1.6;"></div>"""

    # Tooltip JS
    prop_js = """
(function(){{
  var ROUTES={data};
  var tip=document.getElementById('prop-tooltip');
  var lookup={{}};
  ROUTES.forEach(function(r){{lookup[r.route_id]=r.stops;}});
  document.querySelectorAll('.prop-node').forEach(function(c){{
    c.addEventListener('mouseenter',function(e){{
      var rid=this.getAttribute('data-route');
      var idx=parseInt(this.getAttribute('data-idx'));
      var s=lookup[rid]?lookup[rid][idx]:null;
      if(!s)return;
      var col=s.color;
      tip.innerHTML=
        '<div style="font-weight:700;font-size:13px;color:'+col+';margin-bottom:8px;">'+
          s.stop_id+' \u2014 '+s.label+
        '</div>'+
        '<div style="display:grid;grid-template-columns:auto 1fr;gap:3px 10px;">'+
          '<span style="color:#8b8fa3;">Delay</span>'+
          '<span style="color:'+col+';font-weight:700;">'+s.delay+' min</span>'+
          '<span style="color:#8b8fa3;">Sched Arr</span><span>'+s.sched_arr+'</span>'+
          '<span style="color:#8b8fa3;">Actual Arr</span><span>'+s.actual_arr+'</span>'+
          '<span style="color:#8b8fa3;">Sched Dep</span><span>'+s.sched_dep+'</span>'+
          '<span style="color:#8b8fa3;">Actual Dep</span><span>'+s.actual_dep+'</span>'+
          '<span style="color:#8b8fa3;">Cause</span>'+
          '<span style="font-size:11px;">'+s.cause+'</span>'+
        '</div>';
      tip.style.opacity='1';
      pos(e);
    }});
    c.addEventListener('mousemove',function(e){{pos(e);}});
    c.addEventListener('mouseleave',function(){{tip.style.opacity='0';}});
  }});
  function pos(e){{
    var tw=tip.offsetWidth||220,th=tip.offsetHeight||160;
    var x=e.clientX+14,y=e.clientY-th/2;
    if(x+tw>window.innerWidth-10) x=e.clientX-tw-14;
    if(y<10) y=10;
    if(y+th>window.innerHeight-10) y=window.innerHeight-th-10;
    tip.style.left=x+'px';tip.style.top=y+'px';
  }}
}})();""".format(data=all_json)

    return """
    <div id="propagation" style="margin-bottom:36px;">
      <div style="margin-bottom:20px;">
        <div style="font-size:20px;font-weight:800;color:{ct};margin-bottom:6px;">
          Delay Propagation Map
        </div>
        <div style="font-size:13px;color:{mu};">
          Shows the worst trip per route - where delay entered, how it spread stop-by-stop,
          and where recovery occurred. Hover any circle for full stop details.
        </div>
      </div>
      {legend}
      {cards}
      {tooltip}
    </div>
    <script>{js}</script>
    """.format(ct=C_TEXT,mu=C_MUTED,legend=legend_html,cards=cards_html,
               tooltip=tooltip,js=prop_js)

# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = (
"*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}"
"html{scroll-behavior:smooth;}"
"body{background:"+BG+";color:"+C_TEXT+";font-family:"+FONT+";min-height:100vh;}"
"::-webkit-scrollbar{width:6px;height:6px;}"
"::-webkit-scrollbar-track{background:"+BG+";}"
"::-webkit-scrollbar-thumb{background:#2e3146;border-radius:3px;}"
".nav{position:sticky;top:0;z-index:200;background:"+BG_NAV+"cc;"
"backdrop-filter:blur(12px);border-bottom:1px solid "+C_BORDER+";"
"display:flex;align-items:center;justify-content:space-between;padding:12px 40px;gap:12px;flex-wrap:wrap;}"
".nav-brand{display:flex;align-items:center;gap:10px;}"
".nav-dot{width:8px;height:8px;border-radius:50%;background:#4ade80;"
"box-shadow:0 0 8px #4ade80;animation:pulse 2s infinite;}"
".nav-title{font-size:13px;font-weight:700;letter-spacing:0.05em;}"
".nav-links{display:flex;gap:20px;flex-wrap:wrap;}"
".nav-links a{color:"+C_MUTED+";text-decoration:none;font-size:12px;"
"font-weight:600;letter-spacing:0.04em;text-transform:uppercase;transition:color .2s;}"
".nav-links a:hover{color:"+C_TEXT+";}"
".cards-row{display:flex;flex-wrap:wrap;gap:18px;margin-bottom:32px;}"
".card{flex:1;min-width:180px;background:"+BG_CARD+";border-radius:"+RADIUS+";"
"padding:22px 24px;box-shadow:"+SHADOW+";cursor:pointer;transition:transform .2s,box-shadow .2s;}"
".card:hover{transform:translateY(-3px);box-shadow:0 8px 32px rgba(0,0,0,0.5);}"
".card-icon{font-size:22px;margin-bottom:10px;}"
".card-val{font-size:32px;font-weight:800;letter-spacing:-0.03em;margin-bottom:4px;}"
".card-label{font-size:13px;font-weight:600;color:"+C_TEXT+";margin-bottom:3px;}"
".card-note{font-size:11px;color:"+C_MUTED+";}"
".section-card{background:"+BG_CARD+";border-radius:"+RADIUS+";"
"box-shadow:"+SHADOW+";overflow:hidden;margin-bottom:32px;"
"opacity:0;transform:translateY(20px);transition:opacity .6s,transform .6s;}"
".section-card.visible{opacity:1;transform:translateY(0);}"
".section-title{padding:20px 22px 0;font-size:15px;font-weight:700;color:"+C_TEXT+";margin-bottom:14px;}"
".prop-card{overflow:visible!important;}"
".chart-card{background:"+BG_CARD+";border-radius:"+RADIUS+";"
"padding:20px;box-shadow:"+SHADOW+";flex:1;min-width:300px;"
"opacity:0;transform:translateY(20px);transition:opacity .6s,transform .6s;}"
".chart-card.visible{opacity:1;transform:translateY(0);}"
".chart-title{font-size:13px;font-weight:700;color:"+C_TEXT+";margin-bottom:14px;letter-spacing:0.01em;}"
".charts-row{display:flex;flex-wrap:wrap;gap:20px;margin-bottom:32px;}"
".trow{border-bottom:1px solid "+C_BORDER+";transition:background .15s;}"
".trow:hover{background:rgba(255,255,255,0.03);}"
".pill{background:var(--pc)1a;color:var(--pc);"
"border:1px solid var(--pc)44;border-radius:5px;"
"padding:2px 9px;font-size:11px;font-weight:700;"
"white-space:nowrap;letter-spacing:0.02em;transition:box-shadow .2s;cursor:default;}"
"@keyframes fadeInUp{from{opacity:0;transform:translateY(24px);}to{opacity:1;transform:translateY(0);}}"
"@keyframes pulse{0%,100%{box-shadow:0 0 8px #4ade80;}50%{box-shadow:0 0 16px #4ade80;}}"
".fade-card{opacity:0;animation:fadeInUp .5s forwards;}"
".main{max-width:1240px;margin:0 auto;padding:36px 40px 80px;}"
".page-header{margin-bottom:32px;}"
".page-header h1{font-size:30px;font-weight:800;letter-spacing:-0.02em;line-height:1.2;margin-bottom:8px;}"
".page-header p{color:"+C_MUTED+";font-size:13px;}"
".gradient-text{background:linear-gradient(90deg,#6bcb77,#4d96ff);"
"-webkit-background-clip:text;-webkit-text-fill-color:transparent;}"
".footer{text-align:center;padding:32px;color:"+C_MUTED+";"
"font-size:12px;border-top:1px solid "+C_BORDER+";}"
".lk-tr{border-bottom:1px solid "+C_BORDER+";transition:background .15s;}"
".lk-tr:hover{background:rgba(255,255,255,0.03);}"
)

JS_MAIN = """
// Toggle expandable root cause detail rows
function toggleRcd(id) {
  var el  = document.getElementById(id);
  var arr = document.getElementById('arr-' + id);
  if (!el) return;
  if (el.style.display === 'none') {
    el.style.display  = 'block';
    if (arr) arr.style.transform = 'rotate(90deg)';
  } else {
    el.style.display  = 'none';
    if (arr) arr.style.transform = 'rotate(0deg)';
  }
}

function countUp(el){
  var isPct=el.getAttribute('data-target').includes('%');
  var raw=isPct?parseFloat(el.getAttribute('data-target')):parseFloat(el.getAttribute('data-target'));
  var start=0,duration=1000,t0=null;
  function step(ts){
    if(!t0)t0=ts;
    var p=Math.min((ts-t0)/duration,1),ease=1-Math.pow(1-p,3),cur=raw*ease;
    el.textContent=isPct?cur.toFixed(1)+'%':Math.round(cur).toLocaleString();
    if(p<1)requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
var io=new IntersectionObserver(function(entries){
  entries.forEach(function(e){
    if(e.isIntersecting){
      e.target.classList.add('visible');
      e.target.querySelectorAll('[data-target]').forEach(function(el){countUp(el);});
    }
  });
},{threshold:0.08});
document.querySelectorAll('.section-card,.chart-card,.fade-card').forEach(function(el){io.observe(el);});
setTimeout(function(){document.querySelectorAll('.card-val[data-target]').forEach(countUp);},400);
"""

# ── Full HTML ─────────────────────────────────────────────────────────────────


def build_sample_table(df):
    """
    One row per distinct root-cause sub-type.
    Iterates keyword variants per cause and picks the first matching row
    not yet seen — gives maximum variety across all root-cause wording.
    """
    has_rcd = "Root_Cause_Detail" in df.columns

    CAUSE_KEYWORDS = {
        CAUSE_CONGESTION:  ["Sustained corridor", "Localised bottleneck"],
        CAUSE_DWELL:       ["Boarding surge",     "Minor hold"],
        CAUSE_TIMETABLE:   ["physically impossible", "assumes no traffic",
                            "Schedule physically",  "Schedule assumes"],
        CAUSE_TURNAROUND:  ["Late inbound vehicle", "Depot dispatch",
                            "turnaround",           "late departure"],
        CAUSE_ON_TIME:     ["Within tolerance"],
    }

    def ft(row, col):
        try: return pd.to_datetime(row[col]).strftime("%H:%M")
        except: return "N/A"

    def th(label, color=C_MUTED, align="center"):
        return ('<th style="padding:11px 16px;font-size:11px;font-weight:700;'
                'letter-spacing:0.06em;text-transform:uppercase;'
                'background:{bg};color:{c};text-align:{a};white-space:nowrap;">{l}</th>'
                ).format(bg=BG_TH, c=color, l=label, a=align)

    rows_html = ""
    seen_rcds = set()

    for cause in [CAUSE_CONGESTION, CAUSE_DWELL, CAUSE_TIMETABLE, CAUSE_TURNAROUND, CAUSE_ON_TIME]:
        sub = df[df["Attributed_Cause"] == cause]
        if sub.empty:
            continue
        for kw in CAUSE_KEYWORDS.get(cause, [""]):
            if has_rcd and kw:
                match = sub[sub["Root_Cause_Detail"].str.contains(kw, na=False, regex=False)]
                row = match.iloc[0] if not match.empty else None
            else:
                row = sub.iloc[0]
            if row is None:
                continue
            rcd_full = str(row.get("Root_Cause_Detail", "")) if has_rcd else "—"
            rcd_key  = rcd_full[:60]
            if rcd_key in seen_rcds:
                continue
            seen_rcds.add(rcd_key)
            d   = round(float(row["Delay_Min"]), 1)
            dc_ = delay_color(d)
            ds  = "{:.1f} min".format(d) if d > 0 else "0 min"
            rcd = rcd_full[:120] + "…" if len(rcd_full) > 120 else rcd_full
            rows_html += (
                '<tr class="trow">'
                '<td style="padding:11px 16px;font-weight:700;color:{ct};">{rid}</td>'
                '<td style="padding:11px 16px;text-align:center;font-weight:700;color:#6bcbff;">{sid}</td>'
                '<td style="padding:11px 16px;text-align:center;color:{mu};">{sa}</td>'
                '<td style="padding:11px 16px;text-align:center;color:#6bcbff;font-weight:600;">{aa}</td>'
                '<td style="padding:11px 16px;text-align:center;font-weight:800;color:{dc};">{ds}</td>'
                '<td style="padding:11px 16px;text-align:center;">{pl}</td>'
                '<td style="padding:11px 16px;font-size:11px;color:{mu};line-height:1.5;max-width:260px;">{rcd}</td>'
                '</tr>'
            ).format(ct=C_TEXT, mu=C_MUTED, dc=dc_,
                     rid=row["Route_ID"], sid=row["Stop_ID"],
                     sa=ft(row,"Scheduled_Arrival"), aa=ft(row,"Actual_Arrival"),
                     ds=ds, pl=pill(cause), rcd=rcd)

    head = (
        "<tr>"
        + th("Route", align="left") + th("Stop")
        + th("Sched Arr","#8b8fa3") + th("Actual Arr","#6bcbff")
        + th("Delay","#ff9f43") + th("Cause")
        + th("Root Cause Detail","#a78bfa",align="left")
        + "</tr>"
    )
    return """
    <div class="section-card" id="sample">
      <div class="section-title">Sample Records — All Delay Cause Varieties
        <span style="font-size:12px;color:{mu};font-weight:400;">
          &nbsp;·&nbsp; one row per root cause sub-type &nbsp;·&nbsp; use Stop Lookup to search all 500 records
        </span>
      </div>
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;">{head}{rows}</table>
      </div>
    </div>""".format(mu=C_MUTED, head=head, rows=rows_html)



def build_html(df, b64_cause, b64_route, prop_section, lookup_section, ts):
    cards    = build_cards(df)
    legend   = build_legend()
    sample       = build_sample_table(df)
    rt_table     = build_table(df,"Route_ID","routes","Route Summary",max_rows=5)
    st_table      = build_table(df,"Stop_ID","stops","Stop-Wise Delay Attribution",max_rows=20)
    timing_table  = build_stop_timing_table(df)

    chart1 = ('<div class="chart-card" id="causes">'
              '<div class="chart-title">Incidents &amp; Avg Delay by Cause</div>'
              '<img src="data:image/png;base64,{}" style="width:100%;border-radius:8px;"/>'
              '</div>').format(b64_cause)
    chart2 = ('<div class="chart-card">'
              '<div class="chart-title">Avg &amp; Max Delay by Route (minutes)</div>'
              '<img src="data:image/png;base64,{}" style="width:100%;border-radius:8px;"/>'
              '</div>').format(b64_route)

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Transport Delay Attribution Dashboard</title>
<style>{css}</style>
</head>
<body>
<nav class="nav">
  <div class="nav-brand">
    <div class="nav-dot"></div>
    <span class="nav-title">TRANSIT ANALYTICS</span>
  </div>
  <div class="nav-links">
    <a href="#lookup" style="color:#6bcb77!important;font-weight:800;">&#128269; Stop Lookup</a>
    <a href="#summary">Summary</a>
    <a href="#causes">Cause Breakdown</a>
    <a href="#timings">Timings</a>
    <a href="#sample" style="color:#a78bfa!important;font-weight:800;">&#128203; Sample Records</a>
    <a href="#propagation" style="color:#ffd93d!important;font-weight:800;">&#9889; Propagation Map</a>
  </div>
  <span style="font-size:11px;color:{mu};">{ts}</span>
</nav>
<div class="main">
  <div class="page-header" id="summary">
    <h1>Public Transport Delay<br/>
      <span class="gradient-text">Attribution Dashboard</span></h1>
    <p>Rule-based heuristic classification &nbsp;·&nbsp; 500 stop records &nbsp;·&nbsp; 5 routes &nbsp;·&nbsp; 1 operating day</p>
  </div>
  {lookup_section}
  {cards}
  {legend}
  <div class="charts-row">{chart1}{chart2}</div>
  {rt_table}
  {st_table}
  {timing_table}
  {sample}
  {prop_section}
</div>
<div class="footer">Offline Transport Delay Attribution System &nbsp;|&nbsp; {ts}</div>
<script>{js}</script>
</body>
</html>""".format(css=CSS,mu=C_MUTED,ts=ts,cards=cards,legend=legend,
                  chart1=chart1,chart2=chart2,rt_table=rt_table,
                  st_table=st_table,sample=sample,timing_table=timing_table,prop_section=prop_section,lookup_section=lookup_section,js=JS_MAIN)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n[START] 3_generate_dashboard.py\n")
    df = load_data()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("[INFO] Generating charts ...")
    b64_c = chart_cause_bars(df)
    b64_r = chart_route_avg_delay(df)

    print("[INFO] Building stop lookup panel ...")
    lookup_section = build_lookup_panel(df)

    print("[INFO] Building propagation map ...")
    prop_data     = build_propagation_data(df)
    prop_section  = build_propagation_section(prop_data)

    print("[INFO] Building HTML ...")
    html = build_html(df, b64_c, b64_r, prop_section, lookup_section, ts)

    with open(OUTPUT_FILE,"w",encoding="utf-8") as f:
        f.write(html)

    print("Dashboard saved: {}".format(OUTPUT_FILE))
    print("  Records   : {:,}".format(len(df)))
    print("  Routes in map  : {}".format(len(prop_data)))
    print("  File size : ~{} KB".format(len(html)//1024))
    print("\nOpen {} in any browser.\n".format(OUTPUT_FILE))
    print("[DONE]\n")

if __name__ == "__main__":
    main()