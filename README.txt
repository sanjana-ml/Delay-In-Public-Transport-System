================================================================================
PROJECT TITLE
================================================================================
Offline Public Transport Delay Attribution System

================================================================================
PROBLEM STATEMENT
================================================================================
Public transport delay reports typically record only that a vehicle was late —
giving vague reasons like "traffic" or "operational issues." This gives
transport authorities no actionable insight. They cannot distinguish between
delays caused by a poorly-written timetable (unrealistic scheduled speeds),
vehicles failing to depart on time from depots (turnaround issues), passengers
taking too long to board at certain stops (excessive dwell), or genuine road
congestion building up across a route.

This system solves that by applying deterministic, rule-based heuristics to
raw scheduled-vs-actual transit data and attributing every stop-level record
to a specific, actionable delay cause. The result is an offline, interactive
HTML dashboard that transport planners can open on any device — no internet,
no server, no API keys required.

================================================================================
INPUT PARAMETERS
================================================================================
The system expects a CSV file with the following exact column names:

  Route_ID                  - Route identifier (e.g., "R-101")
  Trip_ID                   - Trip identifier (e.g., "R-101-T-003")
  Stop_ID                   - Stop identifier (e.g., "S-07")
  Stop_Sequence             - Stop position in trip (1 = first stop)
  Distance_to_Next_Stop_km  - Distance in km to the next stop (0.0 at last stop)
  Scheduled_Arrival         - Timetabled arrival time (YYYY-MM-DD HH:MM:SS)
  Actual_Arrival            - Observed arrival time (YYYY-MM-DD HH:MM:SS)
  Scheduled_Departure       - Timetabled departure time (YYYY-MM-DD HH:MM:SS)
  Actual_Departure          - Observed departure time (YYYY-MM-DD HH:MM:SS)

================================================================================
DELAY CAUSES DETECTED
================================================================================
The system classifies each record into exactly one of the following causes.
Rules are applied in strict priority order — first match wins.

  1. Vehicle Turnaround Delay
     Trigger: Stop_Sequence == 1 AND actual departure is 5+ minutes after
              scheduled departure. The vehicle was not ready at the depot
              or experienced a crew changeover issue.

  2. Excessive Stop Dwell Time
     Trigger: Actual dwell time (Actual_Departure - Actual_Arrival) exceeds
              scheduled dwell time by 3 or more minutes. Caused by high
              passenger volumes, wheelchair boarding, or mechanical issues.

  3. Unrealistic Timetable
     Trigger: The scheduled time between this stop's departure and the next
              stop's arrival implies a required speed above 65 km/h — physically
              impossible for an urban bus. This is a planning failure, not an
              operational one.

  4. Route Congestion Pattern
     Trigger: Not the first stop, dwell time is normal (< 3 min excess), but
              Actual_Arrival is 10 or more minutes after Scheduled_Arrival.
              The delay was accumulated in motion — strong signal for traffic
              congestion or blocked road segments.

  5. On Time
     Trigger: None of the above conditions were met. The vehicle operated
              within acceptable tolerances.

================================================================================
HOW TO RUN
================================================================================

Quick start (generates data, processes it, builds dashboard):
  python run_all.py

With your own CSV file:
  python upload_and_run.py your_file.csv

Step by step:
  python 1_generate_data.py          # generates transport_data.csv
  python 2_process_logic.py          # classifies delays -> transport_data_processed.csv
  python 3_generate_dashboard.py     # builds offline_dashboard.html

Requirements:
  pip install pandas matplotlib

================================================================================
OUTPUT FILES
================================================================================
  transport_data.csv               - Raw transit data (generated or provided)
  transport_data_processed.csv     - Same data with Attributed_Cause column added
  offline_dashboard.html           - Interactive visual dashboard (open in browser)

Sample outputs are included in the sample_output/ folder.

================================================================================
CONSTRAINTS
================================================================================
  - Fully offline. No internet connection required at any point.
  - No external APIs, no maps, no live tracking of any kind.
  - Rule-based heuristic logic only. No machine learning or prediction models.
  - No external CSS, JS, or font libraries in the HTML output.
  - The dashboard renders correctly when opened from a USB drive.
  - Python 3.7 or higher required.
  - Only two third-party libraries: pandas and matplotlib.
  - All classification thresholds are defined as variables and can be changed
    without modifying business logic.

================================================================================
ARCHITECTURAL FLOW
================================================================================
Raw Transport Data (CSV)
        │
        ▼
Data Generation / Upload
(1_generate_data.py)
        │
        ▼
Heuristic Delay Engine
(2_process_logic.py)
        │
        ▼
Aggregated Metrics
        │
        ▼
Visualization Engine
(3_generate_dashboard.py)
        │
        ▼
Offline Dashboard (HTML)

==================================================================================================================
KEY FEATURES
==================================================================================================================
• Fully offline analytics system
• Deterministic rule-based delay attribution
• Stop-level delay detection
• Route-level congestion pattern detection
• Interactive HTML dashboard
• Zero dependency on APIs or GPS tracking
• Transport planner friendly reports
================================================================================================================
