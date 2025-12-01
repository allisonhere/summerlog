#!/usr/bin/env python3
import os
import subprocess
import smtplib
import textwrap
import markdown2
import sys
import getpass
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path
import platformdirs

# Try to import Tkinter, but don't fail if it's not available
try:
    import tkinter as tk
    from tkinter import ttk
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False

# --- Configuration ---
# Look for config in user's config dir first, then project root
app_name = "summerlog"
user_config_dir = Path(platformdirs.user_config_dir(app_name))
dotenv_path_user = user_config_dir / ".env"

project_root = Path(__file__).parent.parent
dotenv_path_project = project_root / ".env"

# Determine which .env file to load
if dotenv_path_user.exists():
    dotenv_path = dotenv_path_user
else:
    # Fallback to project root
    dotenv_path = dotenv_path_project

load_dotenv(dotenv_path=dotenv_path, override=True)


# Load from environment
API_KEY = os.getenv("OPENAI_API_KEY")
API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")
CONTAINERS = [c.strip() for c in os.getenv("CONTAINERS", "").split(",") if c.strip()]
MAX_LOG_CHARS = int(os.getenv("MAX_LOG_CHARS", 20000))
SINCE_HOURS = int(os.getenv("SINCE_HOURS", 24))
TIMESTAMP_FILE = os.path.join(project_root, 'last_run_timestamp.txt')

def get_docker_containers():
    """Returns a list of running Docker container names."""
    if CONTAINERS:
        return CONTAINERS
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"]
        )
        return [c for c in out.splitlines() if c]
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Error getting Docker containers: {e.stderr}")
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
        return completion.choices[0].message.content.strip()
    except Exception as e:
        return f"Error calling OpenAI API: {e}"

def send_email(body):
    """Sends the summary email."""
    try:
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

        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
                if SMTP_USER and SMTP_PASS:
                    smtp.login(SMTP_USER, SMTP_PASS)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
                if SMTP_USER and SMTP_PASS:
                    smtp.starttls()
                    smtp.login(SMTP_USER, SMTP_PASS)
                smtp.send_message(msg)
        
        print("Email sent successfully.")
    except smtplib.SMTPException as e:
        print(f"Error sending email: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while sending email: {e}")

def run_cli_configure():
    """Runs a command-line wizard to configure Summerlog."""
    print("--- Summerlog Configuration Wizard (CLI) ---")
    print(f"This will create a configuration file at {dotenv_path_user}")
    print("Press Enter to accept the default value in brackets, if available.")

    # Load existing values to show as defaults
    load_dotenv(dotenv_path=dotenv_path_user)

    def get_input(prompt_text, default_val=None, is_password=False):
        prompt = f"{prompt_text} [{default_val or ''}]: "
        if is_password:
            val = getpass.getpass(prompt)
            return val if val else default_val
        else:
            val = input(prompt)
            return val if val else default_val

    config = {
        "OPENAI_API_KEY": get_input("OpenAI API Key", os.getenv("OPENAI_API_KEY"), is_password=True),
        "SMTP_HOST": get_input("SMTP Host", os.getenv("SMTP_HOST")),
        "SMTP_PORT": get_input("SMTP Port", os.getenv("SMTP_PORT", "587")),
        "SMTP_USER": get_input("SMTP User", os.getenv("SMTP_USER")),
        "SMTP_PASS": get_input("SMTP Password", os.getenv("SMTP_PASS"), is_password=True),
        "EMAIL_FROM": get_input("From Email", os.getenv("EMAIL_FROM")),
        "EMAIL_TO": get_input("To Email", os.getenv("EMAIL_TO")),
    }

    print("\nWriting the following configuration:")
    for key, value in config.items():
        display_value = "********" if key in ["OPENAI_API_KEY", "SMTP_PASS"] and value else value
        print(f"  {key}: {display_value}")

    if input("\nSave this configuration? (y/n): ").lower() != 'y':
        print("Configuration cancelled.")
        return

    with open(dotenv_path_user, "w") as f:
        for key, value in config.items():
            if value:
                f.write(f"{key}={value}\n")

    print(f"\nConfiguration saved successfully to {dotenv_path_user}")

def run_gui_configure(root):
    """Launch a simple Tkinter GUI to configure Summerlog."""
    env_path = dotenv_path_user
    root.title("Summerlog Configuration")

    defaults = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "SMTP_HOST": os.getenv("SMTP_HOST", ""),
        "SMTP_PORT": os.getenv("SMTP_PORT", "587"),
        "SMTP_USER": os.getenv("SMTP_USER", ""),
        "SMTP_PASS": os.getenv("SMTP_PASS", ""),
        "EMAIL_FROM": os.getenv("EMAIL_FROM", ""),
        "EMAIL_TO": os.getenv("EMAIL_TO", ""),
    }
    fields = {k: tk.StringVar(value=v) for k, v in defaults.items()}
    status_var = tk.StringVar(value=f"Config will be saved to {env_path}")

    container = ttk.Frame(root, padding=12)
    container.pack(fill="both", expand=True)

    ttk.Label(container, text="Summerlog Configuration", font=("TkDefaultFont", 12, "bold")).pack(pady=(0, 8))
    ttk.Label(container, text="Save writes config. Quit closes without saving.").pack(pady=(0, 12))

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

    def save():
        with open(env_path, "w") as f:
            for key in ["OPENAI_API_KEY", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "EMAIL_FROM", "EMAIL_TO"]:
                f.write(f"{key}={fields[key].get()}\n")
        status_var.set(f"Saved to {env_path}")

    btns = ttk.Frame(container, padding=(0, 12))
    btns.pack(fill="x")
    ttk.Button(btns, text="Save", command=save).pack(side="right", padx=4)
    ttk.Button(btns, text="Quit", command=root.destroy).pack(side="right")

    ttk.Label(container, textvariable=status_var, foreground="#555").pack(anchor="w")
    root.mainloop()

def configure():
    """Runs a configuration wizard, using a GUI if available, otherwise falling back to CLI."""
    # Ensure user config directory exists
    user_config_dir.mkdir(parents=True, exist_ok=True)
    
    if not TKINTER_AVAILABLE:
        print("Tkinter not found. Falling back to command-line configuration.")
        run_cli_configure()
        return

    try:
        # The most reliable way to check for a display is to try to create a root window.
        root = tk.Tk()
        run_gui_configure(root)
    except tk.TclError:
        # This will catch cases where a display is not available (e.g., SSH session).
        print("No display found. Falling back to command-line configuration.")
        run_cli_configure()


def main():

    """Main function to orchestrate the log summary process."""
    if not all([API_KEY, SMTP_HOST, EMAIL_FROM, EMAIL_TO]):
        raise SystemExit("Missing required env vars. Check your .env file for: OPENAI_API_KEY, SMTP_HOST, EMAIL_FROM, EMAIL_TO")

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
    summary = get_ai_summary(prompt)

    print("Sending summary email...")
    send_email(summary)

    # Update the timestamp file after a successful run
    with open(TIMESTAMP_FILE, 'w') as f:
        f.write(current_timestamp)
    print(f"Timestamp file updated to {current_timestamp}")

if __name__ == "__main__":
    main()
