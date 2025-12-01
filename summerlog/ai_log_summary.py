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

def configure():
    """Runs a command-line wizard to configure Summerlog."""
    print("--- Summerlog Configuration Wizard ---")
    print(f"This will create a configuration file at {dotenv_path_user}")
    print("Press Enter to accept the default value in brackets, if available.")

    # Ensure user config directory exists
    user_config_dir.mkdir(parents=True, exist_ok=True)

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
