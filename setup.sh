#!/bin/bash

# This script sets up the ai_log_summary.py script to run as a cron job.

# --- Configuration ---
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PYTHON_PATH="$SCRIPT_DIR/.venv/bin/python3"
SCRIPT_PATH="$SCRIPT_DIR/summerlog/ai_log_summary.py"
CRON_SCHEDULE="0 8 * * *" # Run every day at 8:00 AM

# --- Main Logic ---
CRON_JOB="$CRON_SCHEDULE $PYTHON_PATH $SCRIPT_PATH"

# Check if the cron job already exists
if crontab -l | grep -Fq "$CRON_JOB"; then
    echo "Cron job already exists. No changes made."
else
    # Add the new cron job
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "Cron job added successfully."
    echo "It will run daily at 8:00 AM."
fi
