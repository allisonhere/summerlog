# Summerlog

An AI-powered log summarizer for Docker containers.

## Installation

It is recommended to install Summerlog using `pipx` to ensure its dependencies are isolated from your system.

```bash
pipx install git+https://github.com/allisonhere/summerlog.git
```

If you do not have `pipx`, you can install it with `pip install --user pipx` and `pipx ensurepath`.

## Configuration

After installation, run the interactive configuration wizard:

```bash
summerlog-configure
```

This command will automatically detect your environment.
- If you are in a **desktop environment**, it will launch a graphical (GUI) wizard.
- If you are in a **headless environment** (like an SSH session), it will launch a command-line (CLI) wizard.

Both wizards will guide you through the setup and automatically create a configuration file at `~/.config/summerlog/.env`.

## Usage

To generate a log summary:

```bash
summerlog
```