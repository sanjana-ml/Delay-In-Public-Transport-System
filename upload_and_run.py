"""
upload_and_run.py
-----------------
Two modes:
  1. CSV mode (default):  python upload_and_run.py path/to/file.csv
  2. Manual mode:         python upload_and_run.py --manual

CSV mode validates columns, copies file, runs scripts 2 and 3.
Manual mode launches the interactive CLI from 5_manual_analysis.py.
"""

import sys
import os
import shutil
import subprocess

REQUIRED_COLUMNS = [
    "Route_ID", "Trip_ID", "Stop_ID", "Stop_Sequence",
    "Distance_to_Next_Stop_km",
    "Scheduled_Arrival", "Actual_Arrival",
    "Scheduled_Departure", "Actual_Departure",
]
TARGET_CSV = "transport_data.csv"
DIVIDER    = "=" * 60


def validate_csv(path):
    try:
        import csv
        with open(path, encoding="utf-8", newline="") as f:
            headers = [h.strip() for h in next(csv.reader(f))]
    except FileNotFoundError:
        print("\nERROR: File not found: '{}'".format(path))
        sys.exit(1)
    except StopIteration:
        print("\nERROR: File '{}' is empty.".format(path))
        sys.exit(1)
    except Exception as e:
        print("\nERROR reading '{}': {}".format(path, e))
        sys.exit(1)

    present = set(headers)
    missing = [c for c in REQUIRED_COLUMNS if c not in present]
    extra   = [c for c in headers if c not in REQUIRED_COLUMNS]

    print("\n" + DIVIDER)
    print("  Column Validation Report")
    print(DIVIDER)
    print("  Status: {}".format("PASSED" if not missing else
                                "FAILED — {} column(s) missing".format(len(missing))))
    print("\n  Required columns:")
    for col in REQUIRED_COLUMNS:
        mark = "OK" if col in present else "MISSING"
        print("    [{:<7}]  {}".format(mark, col))
    if extra:
        print("\n  Extra columns in your file (ignored):")
        for col in extra:
            print("    [EXTRA  ]  {}".format(col))
    if missing:
        print("\n  Missing columns:")
        for col in missing:
            print("    {}".format(col))
        print("\n  Column names are case-sensitive. Rename them and retry.")
        print(DIVIDER + "\n")
        return False
    print(DIVIDER)
    return True


def count_rows(path):
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for _ in f) - 1
    except Exception:
        return "unknown"


def run_script(script):
    if not os.path.exists(script):
        print("ERROR: '{}' not found. Run from inside transport_delay_system/".format(script))
        sys.exit(1)
    result = subprocess.run([sys.executable, script])
    if result.returncode != 0:
        print("\nERROR: '{}' failed (exit code {}).".format(script, result.returncode))
        sys.exit(result.returncode)


def run_csv_mode(input_path):
    print("\n" + DIVIDER)
    print("  Offline Transport Delay Attribution System")
    print("  upload_and_run.py  [CSV mode]")
    print(DIVIDER)
    print("  Input file : {}".format(input_path))
    print("  Row count  : {}".format(count_rows(input_path)))

    if not validate_csv(input_path):
        sys.exit(1)

    print("\n[1/3] Copying '{}' → '{}' ...".format(
        os.path.basename(input_path), TARGET_CSV))
    try:
        shutil.copy2(input_path, TARGET_CSV)
        print("      Done.")
    except Exception as e:
        print("ERROR copying file: {}".format(e))
        sys.exit(1)

    print("\n[2/3] Running delay classification (2_process_logic.py) ...")
    run_script("2_process_logic.py")

    print("\n[3/3] Building dashboard (3_generate_dashboard.py) ...")
    run_script("3_generate_dashboard.py")

    print("\n" + DIVIDER)
    print("  Done! Open offline_dashboard.html to view results.")
    print(DIVIDER + "\n")


def run_manual_mode():
    print("\n" + DIVIDER)
    print("  Offline Transport Delay Attribution System")
    print("  upload_and_run.py  [--manual mode]")
    print(DIVIDER)
    if not os.path.exists("5_manual_analysis.py"):
        print("ERROR: '5_manual_analysis.py' not found.")
        print("Make sure you are running from inside transport_delay_system/")
        sys.exit(1)
    result = subprocess.run([sys.executable, "5_manual_analysis.py"])
    sys.exit(result.returncode)


def main():
    args = sys.argv[1:]

    if not args:
        print("\nUsage:")
        print("  python upload_and_run.py your_file.csv      # CSV mode")
        print("  python upload_and_run.py --manual           # Manual input mode")
        sys.exit(1)

    if args[0] == "--manual":
        run_manual_mode()
    else:
        run_csv_mode(args[0])


if __name__ == "__main__":
    main()
    