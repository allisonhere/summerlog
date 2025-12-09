#!/usr/bin/env python3
import getpass
import os
import smtplib
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
import argparse
import shutil
from importlib import metadata

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # Tk may be missing on minimal/headless installs
    tk = None
    ttk = None

import markdown2
from dotenv import load_dotenv
from openai import OpenAI


# --- Configuration ---
# Build paths under the user's config directory (~/.config/summerlog by default)
CONFIG_ROOT = os.path.join(os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "summerlog")
os.makedirs(CONFIG_ROOT, exist_ok=True)
DOTENV_PATH = os.path.join(CONFIG_ROOT, ".env")
TIMESTAMP_FILE = os.path.join(CONFIG_ROOT, "last_run_timestamp.txt")
load_dotenv(dotenv_path=DOTENV_PATH, override=True)


def _int_env(name, default):
    """Parse integer environment variables safely, returning default on invalid or missing values."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Warning: env {name} expected int; got '{raw}'. Using default {default}.")
        return default


# Load from environment
API_KEY = os.getenv("OPENAI_API_KEY")
API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = _int_env("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_SECURITY = os.getenv("SMTP_SECURITY", "starttls").lower()
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")
CONTAINERS = [c.strip() for c in os.getenv("CONTAINERS", "").split(",") if c.strip()]
MAX_LOG_CHARS = _int_env("MAX_LOG_CHARS", 20000)
SINCE_HOURS = _int_env("SINCE_HOURS", 24)
REDACTION_PATTERNS = [p.strip() for p in os.getenv("REDACTION_PATTERNS", "").split(",") if p.strip()]
SCHEDULER = os.getenv("SCHEDULER", "").lower()

def get_docker_containers():
    """Returns a list of running Docker container names."""
    if CONTAINERS:
        return CONTAINERS
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"]
        )
        return [c.decode("utf-8") for c in out.splitlines() if c]
    except subprocess.CalledProcessError as e:
        output = e.output.decode("utf-8") if e.output else ""
        raise SystemExit(f"Error getting Docker containers: {output or e}")
    except FileNotFoundError:
        raise SystemExit("Error: 'docker' command not found. Is Docker installed and in your PATH?")

def get_container_logs(container_name, since_iso):
    """Collects logs for a given container since a specific time."""
    try:
        logs = subprocess.check_output(
            ["docker", "logs", container_name, f"--since={since_iso}"],
            stderr=subprocess.STDOUT
        )
        return logs.decode("utf-8")
    except subprocess.CalledProcessError as e:
        return f"Error collecting logs: {e.output.decode('utf-8')}"

def build_prompt(log_data, since_str):
    """Builds the prompt for the language model."""
    log_sections = []
    for name, logs in log_data.items():
        trimmed_logs = logs[-MAX_LOG_CHARS:]
        log_sections.append(f"## Container: {name}\n\n```\n{trimmed_logs}\n```")

    logs_block = "\n\n".join(log_sections)
    return textwrap.dedent(f"""
    You are an expert SRE assistant. Your task is to analyze the following Docker container logs since {since_str} and provide a clear, actionable summary.

    Please structure your response in Markdown as follows:

    ### 1. Overall Health Summary
    - A brief, one-sentence summary of the system's health. If everything is normal, state that clearly.

    ### 2. Key Events & Issues
    - Use a bulleted list to describe significant events, warnings, or errors.
    - For each item, specify the affected container and the severity.
    - **IMPORTANT**: Wrap the severity level in a span tag with a class corresponding to the severity. For example:
      - For HIGH severity: `<span class="severity-high">HIGH</span>`
      - For MEDIUM severity: `<span class="severity-medium">MEDIUM</span>`
      - For LOW severity: `<span class="severity-low">LOW</span>`

    ### 3. Recommendations & Next Steps
    - For each issue identified, provide a clear, numbered list of recommended actions to investigate or resolve it.
    - If no issues are found, recommend continued monitoring.

    Here are the logs:

    {logs_block}
    """)



def get_ai_summary(prompt):
    """Calls the OpenAI API to get a summary of the logs."""
    try:
        client = OpenAI(api_key=API_KEY, base_url=API_BASE)
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a concise, practical SRE assistant who provides summaries in Markdown."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        return completion.choices[0].message.content.strip(), None
    except Exception as e:
        return None, f"Error calling OpenAI API: {e}"

def send_email(body):
    """Sends the summary email."""
    try:
        security_mode = SMTP_SECURITY if SMTP_SECURITY in {"starttls", "ssl", "none"} else "starttls"
        style = """
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f8f9fa; padding: 20px; }
            h1, h2, h3 { color: #2c3e50; border-bottom: 2px solid #eaecef; padding-bottom: 0.3em; }
            code { background-color: #e8eaed; padding: 2px 6px; border-radius: 6px; font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace; }
            pre { background-color: #e8eaed; padding: 1em; border-radius: 6px; overflow-x: auto; }
            ul { padding-left: 20px; }
            li { margin-bottom: 0.5em; }
            .severity-high { background-color: #e74c3c; color: white; padding: 4px 10px; border-radius: 15px; font-size: 0.85em; font-weight: bold; text-transform: uppercase; }
            .severity-medium { background-color: #f39c12; color: white; padding: 4px 10px; border-radius: 15px; font-size: 0.85em; font-weight: bold; text-transform: uppercase; }
            .severity-low { background-color: #3498db; color: white; padding: 4px 10px; border-radius: 15px; font-size: 0.85em; font-weight: bold; text-transform: uppercase; }
        </style>
        """
        html_body = markdown2.markdown(body)
        full_html = f"<html><head>{style}</head><body>{html_body}</body></html>"
        msg = MIMEText(full_html, 'html')
        msg["Subject"] = f"Container Log Summary - {datetime.now().strftime('%Y-%m-%d')}"
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO

        if security_mode == "ssl":
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
                if SMTP_USER and SMTP_PASS:
                    smtp.login(SMTP_USER, SMTP_PASS)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
                if security_mode == "starttls":
                    if SMTP_USER and SMTP_PASS:
                        smtp.starttls()
                        smtp.login(SMTP_USER, SMTP_PASS)
                elif SMTP_USER and SMTP_PASS:
                    smtp.login(SMTP_USER, SMTP_PASS)
                smtp.send_message(msg)
        
        print("Email sent successfully.")
        return True
    except smtplib.SMTPException as e:
        print(f"Error sending email: {e}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred while sending email: {e}")
        return False

def configure():
    """Launch the appropriate configuration wizard based on environment."""
    if _can_launch_gui():
        try:
            return _configure_gui()
        except Exception as e:
            # Fallback to CLI when GUI cannot start (e.g., DISPLAY unset/denied)
            print(f"GUI configuration unavailable ({e}). Falling back to CLI wizard.")
    return _configure_cli()


def _configure_gui():
    """Launch a Tkinter GUI to configure Summerlog."""
    root = tk.Tk()
    root.title("Summerlog Configuration")

    defaults = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "SMTP_HOST": os.getenv("SMTP_HOST", ""),
        "SMTP_PORT": os.getenv("SMTP_PORT", "587"),
        "SMTP_USER": os.getenv("SMTP_USER", ""),
        "SMTP_PASS": os.getenv("SMTP_PASS", ""),
        "EMAIL_FROM": os.getenv("EMAIL_FROM", ""),
        "EMAIL_TO": os.getenv("EMAIL_TO", ""),
        "SCHEDULER": SCHEDULER or _default_scheduler(),
    }
    fields = {k: tk.StringVar(value=v) for k, v in defaults.items()}
    schedule_var = tk.StringVar(value="daily")
    status_var = tk.StringVar(value="Fill in the fields and click Save.")
    scheduler_var = fields["SCHEDULER"]

    container = ttk.Frame(root, padding=12)
    container.pack(fill="both", expand=True)

    ttk.Label(container, text="Summerlog Configuration", font=("TkDefaultFont", 12, "bold")).pack(pady=(0, 8))
    ttk.Label(container, text="Save writes .env and installs the scheduled job. Quit closes without saving.").pack(pady=(0, 12))

    def add_field(label, key, show=None):
        frame = ttk.Frame(container, padding=(0, 4))
        frame.pack(fill="x")
        ttk.Label(frame, text=label, width=18, anchor="w").pack(side="left")
        entry = ttk.Entry(frame, textvariable=fields[key], show=show)
        entry.pack(side="left", fill="x", expand=True)
        return entry

    ttk.Label(container, text="OpenAI", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
    add_field("API Key", "OPENAI_API_KEY", show="*")

    ttk.Label(container, text="Email Settings", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(8, 0))
    add_field("SMTP Host", "SMTP_HOST")
    add_field("SMTP Port", "SMTP_PORT")
    add_field("SMTP User", "SMTP_USER")
    add_field("SMTP Password", "SMTP_PASS", show="*")
    add_field("From Email", "EMAIL_FROM")
    add_field("To Email", "EMAIL_TO")

    ttk.Label(container, text="Scheduler", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(8, 0))
    scheduler_frame = ttk.Frame(container, padding=(0, 4))
    scheduler_frame.pack(fill="x", anchor="w")
    ttk.Radiobutton(scheduler_frame, text="cron", variable=scheduler_var, value="cron").pack(anchor="w")
    ttk.Radiobutton(scheduler_frame, text="systemd", variable=scheduler_var, value="systemd").pack(anchor="w")

    ttk.Label(container, text="Cron Schedule", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(8, 0))
    schedule_frame = ttk.Frame(container, padding=(0, 4))
    schedule_frame.pack(fill="x")
    ttk.OptionMenu(schedule_frame, schedule_var, "daily", "daily", "weekly", "hourly").pack(fill="x")
    ttk.Label(container, text="Choose how often to run the summary email.").pack(anchor="w")

    def save():
        _write_env({key: fields[key].get() for key in fields})
        cron_schedules = {"daily": "0 8 * * *", "weekly": "0 8 * * 0", "hourly": "0 * * * *"}
        cron_schedule = cron_schedules.get(schedule_var.get(), "0 8 * * *")
        scheduler_choice = fields["SCHEDULER"].get().strip().lower() or _default_scheduler()
        _update_scheduler(scheduler_choice, cron_schedule)
        status_var.set(f"Saved to {DOTENV_PATH} and scheduler updated.")

    btns = ttk.Frame(container, padding=(0, 12))
    btns.pack(fill="x")
    ttk.Button(btns, text="Save", command=save).pack(side="right", padx=4)
    ttk.Button(btns, text="Quit", command=root.destroy).pack(side="right")

    ttk.Label(container, textvariable=status_var, foreground="#555").pack(anchor="w")
    root.mainloop()


def _configure_cli():
    """Headless configuration wizard for terminals."""
    print("Summerlog configuration (CLI mode). Leave blank to keep defaults where applicable.")
    print("Required fields must be provided.")
    print()
    defaults = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "SMTP_HOST": os.getenv("SMTP_HOST", ""),
        "SMTP_PORT": os.getenv("SMTP_PORT", "587"),
        "SMTP_USER": os.getenv("SMTP_USER", ""),
        "SMTP_PASS": os.getenv("SMTP_PASS", ""),
        "EMAIL_FROM": os.getenv("EMAIL_FROM", ""),
        "EMAIL_TO": os.getenv("EMAIL_TO", ""),
        "SCHEDULER": SCHEDULER or _default_scheduler(),
    }

    def prompt(label, key, secret=False, required=False, validator=None, hint=None):
        current = defaults[key]
        display_default = "(current set)" if secret and current else current
        hint_suffix = f" ({hint})" if hint else ""
        prompt_text = f"{label}{hint_suffix}"
        if display_default:
            prompt_text += f" [{display_default}]"
        prompt_text += ": "

        while True:
            if secret:
                value = getpass.getpass(prompt_text)
            else:
                value = input(prompt_text)

            if not value:
                value = current

            if required and not value:
                print("  Value is required. Please enter a value.")
                continue

            if validator:
                valid, err = validator(value)
                if not valid:
                    print(f"  {err}")
                    continue

            return value

    new_values = {
        "OPENAI_API_KEY": prompt("OpenAI API Key", "OPENAI_API_KEY", secret=True, required=True),
        "SMTP_HOST": prompt("SMTP Host", "SMTP_HOST", required=True),
        "SMTP_PORT": prompt("SMTP Port", "SMTP_PORT", required=True, validator=_validate_port),
        "SMTP_USER": prompt("SMTP User", "SMTP_USER"),
        "SMTP_PASS": prompt("SMTP Password", "SMTP_PASS", secret=True),
        "EMAIL_FROM": prompt("From Email", "EMAIL_FROM", required=True, validator=_validate_email),
        "EMAIL_TO": prompt("To Email", "EMAIL_TO", required=True, validator=_validate_email),
        "SCHEDULER": prompt("Scheduler (cron/systemd)", "SCHEDULER", hint="leave blank for auto"),
    }

    cron_schedules = {"daily": "0 8 * * *", "weekly": "0 8 * * 0", "hourly": "0 * * * *"}
    while True:
        schedule_choice = input("Schedule (daily/weekly/hourly) [daily]: ").strip().lower() or "daily"
        if schedule_choice in cron_schedules:
            break
        print("  Invalid choice. Please enter daily, weekly, or hourly.")
    cron_schedule = cron_schedules[schedule_choice]

    print("\nSummary (secrets hidden):")
    print(f"  OpenAI API Key: {'(set)' if new_values['OPENAI_API_KEY'] else '(not set)'}")
    print(f"  SMTP Host: {new_values['SMTP_HOST']}")
    print(f"  SMTP Port: {new_values['SMTP_PORT']}")
    print(f"  SMTP User: {new_values['SMTP_USER']}")
    print(f"  SMTP Password: {'(set)' if new_values['SMTP_PASS'] else '(not set)'}")
    print(f"  From Email: {new_values['EMAIL_FROM']}")
    print(f"  To Email: {new_values['EMAIL_TO']}")
    print(f"  Schedule: {schedule_choice} -> {cron_schedule}")
    print(f"  Scheduler: {new_values['SCHEDULER'] or '(auto)'}")

    confirm = input("\nSave and update scheduler? [Y/n]: ").strip().lower() or "y"
    if confirm.startswith("y"):
        _write_env(new_values)
        scheduler_choice = new_values["SCHEDULER"].strip().lower() or _default_scheduler()
        _update_scheduler(scheduler_choice, cron_schedule)
        print(f"Saved to {DOTENV_PATH} and scheduler updated.")
    else:
        print("Canceled; no changes were saved.")


def _write_env(values):
    """Persist environment values to the config directory."""
    os.makedirs(CONFIG_ROOT, exist_ok=True)
    # Preserve additional tunables so re-running the wizard does not drop them.
    keys = [
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_MODEL",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASS",
        "SMTP_SECURITY",
        "EMAIL_FROM",
        "EMAIL_TO",
        "CONTAINERS",
        "MAX_LOG_CHARS",
        "SINCE_HOURS",
        "REDACTION_PATTERNS",
        "SCHEDULER",
    ]
    with open(DOTENV_PATH, "w") as f:
        for key in keys:
            current_value = values.get(key, os.getenv(key, ""))
            f.write(f"{key}={current_value}\n")


def _update_cron(cron_schedule):
    """Install/update the cron entry; fails gracefully if cron is unavailable."""
    python_path = sys.executable
    cron_job = f"{cron_schedule} {python_path} -m summerlog.ai_log_summary"

    try:
        existing = subprocess.run(["crontab", "-l"], check=False, capture_output=True, text=True)
    except FileNotFoundError:
        print("Warning: cron not available (crontab command not found). Skipping cron setup.")
        return

    if existing.returncode not in (0, 1):
        print(f"Warning: unable to read existing crontab ({existing.stderr.strip()}). Skipping cron setup.")
        return

    current_lines = existing.stdout.splitlines() if existing.stdout else []
    filtered = [line for line in current_lines if "summerlog.ai_log_summary" not in line]
    filtered.append(cron_job)
    new_crontab = "\n".join(filtered) + "\n"

    applied = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
    if applied.returncode != 0:
        print(f"Warning: failed to update crontab ({applied.stderr.strip()}).")
    else:
        print("Cron entry updated.")


def _update_systemd(cron_schedule):
    """Install/update a systemd user timer; fails gracefully if systemd is unavailable."""
    if not shutil.which("systemctl"):
        print("Warning: systemctl not available. Skipping systemd setup.")
        return

    python_path = sys.executable
    service_dir = os.path.join(os.path.expanduser("~/.config"), "systemd", "user")
    os.makedirs(service_dir, exist_ok=True)

    service_path = os.path.join(service_dir, "summerlog.service")
    timer_path = os.path.join(service_dir, "summerlog.timer")

    with open(service_path, "w") as f:
        f.write(
            "[Unit]\n"
            "Description=Summerlog container log summary\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={python_path} -m summerlog.ai_log_summary\n"
        )

    on_calendar = {
        "0 8 * * *": "*-*-* 08:00:00",
        "0 8 * * 0": "Sun *-*-* 08:00:00",
        "0 * * * *": "hourly",
    }.get(cron_schedule, "daily")

    with open(timer_path, "w") as f:
        f.write(
            "[Unit]\n"
            "Description=Run Summerlog on schedule\n\n"
            "[Timer]\n"
            f"OnCalendar={on_calendar}\n"
            "Persistent=true\n"
            "Unit=summerlog.service\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        )

    reload = subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
    if reload.returncode != 0:
        print(f"Warning: systemd daemon-reload failed ({reload.stderr.strip()}).")
        return

    enable = subprocess.run(["systemctl", "--user", "enable", "--now", "summerlog.timer"], capture_output=True, text=True)
    if enable.returncode != 0:
        print(f"Warning: enabling summerlog.timer failed ({enable.stderr.strip()}).")
    else:
        print("Systemd timer enabled.")


def _default_scheduler():
    """Pick a scheduler based on availability: prefer cron if present, else systemd."""
    has_cron = bool(shutil.which("crontab"))
    has_systemd = bool(shutil.which("systemctl"))
    if has_cron:
        return "cron"
    if has_systemd:
        return "systemd"
    return "cron"


def _update_scheduler(scheduler_choice, cron_schedule):
    """Update cron or systemd based on choice, with fallback."""
    choice = scheduler_choice or _default_scheduler()
    if choice == "systemd":
        if shutil.which("systemctl"):
            _update_systemd(cron_schedule)
            return
        print("systemd not available; falling back to cron.")
    if choice == "cron":
        if shutil.which("crontab"):
            _update_cron(cron_schedule)
            return
        print("cron not available; attempting systemd instead.")
        _update_systemd(cron_schedule)


def _validate_port(value):
    """Validate a port number."""
    try:
        port = int(value)
        if 1 <= port <= 65535:
            return True, None
        return False, "Port must be between 1 and 65535."
    except ValueError:
        return False, "Port must be an integer."


def _validate_email(value):
    """Very basic email validation."""
    if "@" in value and "." in value.split("@")[-1]:
        return True, None
    return False, "Please enter a valid email address."


def _can_launch_gui():
    """Detect if a display is available for Tkinter."""
    if tk is None:
        return False
    has_display = os.getenv("DISPLAY") or sys.platform.startswith("win") or sys.platform == "darwin"
    return bool(has_display)

def main():
    """Main function to orchestrate the log summary process."""
    parser = argparse.ArgumentParser(
        description="Summarize Docker container logs with AI and email the results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            f"""\
            Environment configuration is loaded from:
              {DOTENV_PATH}
            Required: OPENAI_API_KEY, SMTP_HOST, EMAIL_FROM, EMAIL_TO
            Optional: OPENAI_API_BASE, OPENAI_MODEL, SMTP_SECURITY, SMTP_PORT, SMTP_USER, SMTP_PASS,
                      CONTAINERS, MAX_LOG_CHARS, SINCE_HOURS, REDACTION_PATTERNS, SCHEDULER
            """
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the summary without sending email or updating timestamp.")
    parser.add_argument("--version", action="version", version=f"summerlog {metadata.version('summerlog')}")
    args = parser.parse_args()

    if not all([API_KEY, SMTP_HOST, EMAIL_FROM, EMAIL_TO]):
        raise SystemExit(f"Missing required env vars. Check {DOTENV_PATH} for: OPENAI_API_KEY, SMTP_HOST, EMAIL_FROM, EMAIL_TO")

    # Determine the timeframe for log collection
    try:
        with open(TIMESTAMP_FILE, 'r') as f:
            since_iso = f.read().strip()
            since_str = f"the last run at {since_iso}"
    except FileNotFoundError:
        since_iso = (datetime.now(timezone.utc) - timedelta(hours=SINCE_HOURS)).isoformat()
        since_str = f"the last {SINCE_HOURS} hours"

    current_timestamp = datetime.now(timezone.utc).isoformat()

    print(f"Collecting logs from containers since {since_iso}...")
    containers = get_docker_containers()
    if not containers:
        print("No running containers found to analyze.")
        return

    log_data = {}
    for name in containers:
        log_data[name] = get_container_logs(name, since_iso)

    # Check if there are any new logs
    if all(not logs for logs in log_data.values()):
        print("No new logs to analyze.")
        # Update the timestamp file even if there are no new logs
        with open(TIMESTAMP_FILE, 'w') as f:
            f.write(current_timestamp)
        return

    print("Generating AI summary...")
    prompt = build_prompt(log_data, since_str)
    summary, ai_error = get_ai_summary(prompt)
    if ai_error:
        print(ai_error)
        raise SystemExit(1)

    if args.dry_run:
        print("\n--- DRY RUN: Summary ---\n")
        print(summary)
        return

    print("Sending summary email...")
    email_sent = send_email(summary)
    if not email_sent:
        raise SystemExit(1)

    # Update the timestamp file after a successful run
    with open(TIMESTAMP_FILE, 'w') as f:
        f.write(current_timestamp)
    print(f"Timestamp file updated to {current_timestamp}")

if __name__ == "__main__":
    main()
