"""
run_all.py
----------
One-click pipeline runner. Executes scripts 1 → 2 → 3 in sequence.
Stops immediately and prints the error if any step fails.

Usage:
    python run_all.py
"""

import subprocess
import sys
import os
import time

STEPS = [
    ("1_generate_data.py",    "Generating synthetic transit data"),
    ("2_process_logic.py",    "Classifying delay causes"),
    ("3_generate_dashboard.py", "Building offline dashboard"),
]

DIVIDER = "=" * 56

def run_step(script, description, step_num, total):
    print("\n{div}".format(div=DIVIDER))
    print("  Step {}/{} — {}".format(step_num, total, description))
    print("  Script : {}".format(script))
    print(DIVIDER)

    if not os.path.exists(script):
        print("\nERROR: '{}' not found in current directory.".format(script))
        print("Make sure you are running this from inside transport_delay_system/")
        sys.exit(1)

    t_start = time.time()
    result  = subprocess.run(
        [sys.executable, script],
        capture_output=False   # let script print directly to terminal
    )
    elapsed = round(time.time() - t_start, 1)

    if result.returncode != 0:
        print("\n{div}".format(div=DIVIDER))
        print("  FAILED: '{}' exited with code {}.".format(
            script, result.returncode))
        print("  Pipeline stopped.")
        print(DIVIDER)
        sys.exit(result.returncode)

    print("\n  Completed in {}s".format(elapsed))


def main():
    print("\n" + DIVIDER)
    print("  Offline Transport Delay Attribution System")
    print("  Pipeline: all 3 steps")
    print(DIVIDER)

    for i, (script, description) in enumerate(STEPS, start=1):
        run_step(script, description, i, len(STEPS))

    print("\n" + DIVIDER)
    print("  ALL STEPS COMPLETE")
    print(DIVIDER)
    print("\n  Generated files:")
    for fname in ["transport_data.csv",
                  "transport_data_processed.csv",
                  "offline_dashboard.html"]:
        exists = os.path.exists(fname)
        size   = os.path.getsize(fname) // 1024 if exists else 0
        status = "OK  ~{} KB".format(size) if exists else "MISSING"
        print("    [{s}]  {f}".format(s=status, f=fname))

    print("\n  Open offline_dashboard.html in any browser to view results.\n")


if __name__ == "__main__":
    main()
