# Summerlog

An AI-powered log summarizer for Docker containers.

## Installation

It is recommended to install Summerlog using `pipx` to ensure its dependencies are isolated from your system.

```bash
pipx install git+https://github.com/allisonhere/summerlog.git
```

If you do not have `pipx`, you can install it with `pip install --user pipx` and `pipx ensurepath`.

## Configuration

After installation, you need to create a configuration file.

1.  Create the configuration directory:
    ```bash
    mkdir -p ~/.config/summerlog
    ```
2.  Create a new file named `.env` inside that directory:
    ```bash
    nano ~/.config/summerlog/.env
    ```
3.  Add the following content to the file, filling in your own details:
    ```
    OPENAI_API_KEY=your_openai_api_key
    SMTP_HOST=your_smtp_host
    EMAIL_FROM=your_from_email
    EMAIL_TO=your_to_email
    SMTP_PORT=587
    SMTP_USER=your_smtp_user
    SMTP_PASS=your_smtp_password
    ```

The `summerlog-configure` command is also available if you are in a graphical desktop environment, but it is not required.

## Usage

To generate a log summary:

```bash
summerlog
```