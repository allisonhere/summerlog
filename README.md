# Summerlog

An AI-powered log summarizer for Docker containers.

## Installation

### One-liner (Ubuntu/Debian, headless safe)

This installs/refreshes Summerlog via `pipx`, sets up PATH, and launches the CLI configurator:

```bash
curl -fsSL https://raw.githubusercontent.com/allisonhere/summerlog/master/scripts/install_summerlog.sh | bash
```

If you prefer to inspect first:

```bash
curl -fsSL -o install_summerlog.sh https://raw.githubusercontent.com/allisonhere/summerlog/master/scripts/install_summerlog.sh
bash install_summerlog.sh
```

### Manual install with pipx

```bash
pipx install git+https://github.com/allisonhere/summerlog.git@master
```

If you do not have `pipx`, you can install it with:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

## Configuration

After installation, run the interactive configuration wizard:

```bash
summerlog-configure
```

This command will automatically detect your environment.
- If you are in a **desktop environment**, it will launch a graphical (GUI) wizard.
- If you are in a **headless environment** (like an SSH session), it will launch a command-line (CLI) wizard.

Both wizards will guide you through the setup and automatically create a configuration file at `~/.config/summerlog/.env`.
Runtime state (like the last run timestamp) is also stored alongside that config.

You can re-run the wizard at any time to update credentials or the schedule:

```bash
summerlog-configure
```

The wizard installs a **cron** entry to run Summerlog on the cadence you pick (daily/weekly/hourly).

## Usage

To generate a log summary:

```bash
summerlog
```
