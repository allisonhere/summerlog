#!/usr/bin/env python3
import os
import subprocess
import smtplib
import textwrap
import markdown2
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from openai import OpenAI
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal
from textual.widgets import Header, Footer, Input, Button, Label, Static, RadioSet, RadioButton


# --- Configuration ---
# Build paths relative to the project root
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(project_root, '.env')
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
    """Launches the TUI configuration wizard."""
    TuiApp().run()

class TuiApp(App):
    """A Textual app to configure Summerlog."""

    CSS_PATH = "styles.css"

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Footer()
        with VerticalScroll(id="main-container"):
            yield Static("Summerlog Configuration", classes="title")
            
            yield Label("OpenAI API Key:")
            yield Input(placeholder="sk-...", id="openai_api_key", password=True)

            yield Static("Email Settings", classes="subtitle")
            yield Label("SMTP Host:")
            yield Input(placeholder="smtp.example.com", id="smtp_host")
            yield Label("SMTP Port:")
            yield Input(placeholder="587", id="smtp_port")
            yield Label("SMTP User:")
            yield Input(placeholder="user@example.com", id="smtp_user")
            yield Label("SMTP Password:")
            yield Input(placeholder="Your password", id="smtp_pass", password=True)
            yield Label("From Email:")
            yield Input(placeholder="sender@example.com", id="email_from")
            yield Label("To Email:")
            yield Input(placeholder="recipient@example.com", id="email_to")

            yield Static("Cron Schedule", classes="subtitle")
            with RadioSet(id="schedule"):
                yield RadioButton("Daily at 8:00 AM", id="daily", value=True)
                yield RadioButton("Weekly on Sundays at 8:00 AM", id="weekly")
                yield RadioButton("Hourly", id="hourly")
            
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Quit", id="quit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Event handler called when a button is pressed."""
        if event.button.id == "save":
            self.save_config()
            self.exit("Configuration saved!")
        elif event.button.id == "quit":
            self.exit("Configuration cancelled.")

    def save_config(self) -> None:
        """Save the configuration to the .env file and set up the cron job."""
        # Save .env file
        with open(os.path.join(project_root, ".env"), "w") as f:
            f.write(f"OPENAI_API_KEY={self.query_one('#openai_api_key').value}\n")
            f.write(f"SMTP_HOST={self.query_one('#smtp_host').value}\n")
            f.write(f"SMTP_PORT={self.query_one('#smtp_port').value}\n")
            f.write(f"SMTP_USER={self.query_one('#smtp_user').value}\n")
            f.write(f"SMTP_PASS={self.query_one('#smtp_pass').value}\n")
            f.write(f"EMAIL_FROM={self.query_one('#email_from').value}\n")
            f.write(f"EMAIL_TO={self.query_one('#email_to').value}\n")
        
        # Set up cron job
        schedule_map = {
            "daily": "0 8 * * *",
            "weekly": "0 8 * * 0",
            "hourly": "0 * * * *",
        }
        schedule_id = self.query_one(RadioSet).pressed_button.id
        cron_schedule = schedule_map.get(schedule_id, "0 8 * * *")
        
        python_path = os.path.join(project_root, ".venv/bin/python3")
        script_path = os.path.join(project_root, "summerlog/ai_log_summary.py")
        cron_job = f"{cron_schedule} {python_path} -m summerlog.ai_log_summary"

        # Add the new cron job
        os.system(f'(crontab -l 2>/dev/null | grep -v "summerlog.ai_log_summary" ; echo "{cron_job}") | crontab -')

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