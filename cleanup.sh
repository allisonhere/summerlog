#!/bin/bash

echo "--- Summerlog Cleanup Script ---"
echo "This script will remove configurations and environments created during testing."
echo

# Function to ask for confirmation
confirm() {
    read -p "$1 (y/n): " response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        return 0
    else
        return 1
    fi
}

# Uninstall pipx package
if command -v pipx &> /dev/null && pipx list | grep -q "summerlog"; then
    echo "Found 'summerlog' installed with pipx."
    if confirm "Uninstall 'summerlog' from pipx?"; then
        pipx uninstall summerlog
        echo "'summerlog' uninstalled from pipx."
    else
        echo "Skipping pipx uninstallation."
    fi
    echo
fi

# Remove user config directory
if [ -d "$HOME/.config/summerlog" ]; then
    echo "Found user configuration directory at ~/.config/summerlog."
    if confirm "Delete ~/.config/summerlog?"; then
        rm -rf "$HOME/.config/summerlog"
        echo "User configuration deleted."
    else
        echo "Skipping user configuration deletion."
    fi
    echo
fi

# Clean up project directory
echo "This script assumes you are running it from the root of the 'summerlog' project directory."
if confirm "Clean up the current project directory? (removes .venv, .egg-info, etc.)"; then
    echo "Deleting .venv directory..."
    rm -rf .venv
    echo "Deleting summerlog.egg-info directory..."
    rm -rf summerlog.egg-info
    echo "Deleting last_run_timestamp.txt..."
    rm -f last_run_timestamp.txt
    echo "Deleting __pycache__ directories..."
    find . -type d -name "__pycache__" -exec rm -r {} +
    echo "Project directory cleaned."
else
    echo "Skipping project directory cleanup."
fi

echo
echo "Cleanup complete."
