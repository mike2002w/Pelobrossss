#!/bin/bash
# Regenerate every output from workouts.json. Safe to re-run.
set -e
cd "$(dirname "$0")/.."
python3 tools/json_to_xlsx.py workouts.json tools/template.xlsx exports/pelobrosssss-workout-tracker.xlsx
echo "outputs regenerated from workouts.json"
