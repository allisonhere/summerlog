# Summerlog

An AI-powered log summarizer for Docker containers.

## Installation

It is recommended to install Summerlog using `pipx` to ensure its dependencies are isolated from your system.

```bash
pipx install git+https://github.com/allisonhere/summerlog.git
```

If you do not have `pipx`, you can install it with `pip install --user pipx` and `pipx ensurepath`.

## Configuration

After installation, run the interactive configuration wizard. This will prompt you for your settings and automatically create the configuration file.

```bash
summerlog-configure
```

This will create a `.env` file at `~/.config/summerlog/.env`. You can also create or edit this file manually if you prefer.

## Usage

To generate a log summary:

```bash
summerlog
```
