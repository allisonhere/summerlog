# Changelog

## [1.1.0] - 2024-XX-XX
- Move config and runtime state to `~/.config/summerlog` for writable installs.
- Add headless-friendly CLI configurator with GUI fallback detection.
- Add scheduler choice: cron (default) or systemd user timer.
- Add CLI improvements (validation, summaries, confirmation).
- Add log redaction (built-ins plus custom regex) and `--dry-run` option.
- Make Tk optional to avoid crashes on minimal installs.
- Improve cron setup with safer error handling; surface docker errors better.
- Remove unused `textual` dependency.
