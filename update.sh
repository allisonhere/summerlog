#!/bin/bash

# This script updates the Summerlog application to the latest version from Git.
# It is designed to be safe and preserve the .env configuration file.

echo "Starting Summerlog update..."

# --- Ensure we are in the script's directory ---
cd "$( dirname "${BASH_SOURCE[0]}" )" || exit

# --- 1. Get Latest Code ---
echo "Fetching latest code from GitHub..."
git fetch origin
git reset --hard origin/master

# --- 2. Clean Up ---
# Safely remove untracked files and directories, but exclude the .env file.
echo "Cleaning up old files..."
git clean -fd -e .env

# --- 3. Recreate Virtual Environment ---
echo "Setting up Python virtual environment..."
rm -rf .venv
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# --- 4. Update Cron Job ---
echo "Updating cron job..."
./setup.sh

echo ""
echo "Summerlog update complete!"
