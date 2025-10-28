# ALT‑Station Battery & Temperature Bot

This repository contains a Python script and a SystemD unit for running a
Telegram bot on an ALT Linux workstation (or any modern Linux
distribution).  The bot monitors your laptop’s battery level,
CPU temperature and fan status and sends notifications via Telegram
when the battery gets low or when the charging state changes.  It also
provides commands to query the current state on demand and an
optional interactive shell for administrators.

> **Note**
> This bot does **not** download or execute arbitrary code.  The
> interactive shell is disabled by default and can be enabled only
> by explicitly setting both an admin chat ID and the
> ``ENABLE_UNSAFE_SHELL`` flag.

## Features

* **Battery monitoring** – Periodically checks the battery level using
  ``upower`` and sends notifications to subscribers when it falls
  below a configurable threshold (default 20 %) and when it recovers
  (default ≥ 25 %).  Also notifies when the AC adapter is plugged
  in or unplugged.
* **Temperature and fan status** – If ``lm_sensors`` is available,
  reads CPU temperature and fan RPM via ``sensors -j``.  Falls back
  to reading thermal zones and hwmon entries under ``/sys`` when
  possible.  You can disable sensor queries completely by setting
  ``DISABLE_SENSORS=1``.
* **Commands via Telegram**:
  - ``/battery`` – show current battery percentage, charging state,
    temperature and fan status.
  - ``/subscribe`` and ``/unsubscribe`` – manage push notifications
    for the current chat.
  - ``/run <alias>`` – execute a pre‑defined safe command on the
    host (see ``battery_bot.py`` for the list).  Use ``/run help``
    to see available aliases.
  - ``/whoami`` – show your chat ID (needed to configure admin
    privileges).
  - ``/adminstatus``, ``/setadmin <id>``, ``/enable_shell`` and
    ``/disable_shell`` – manage admin privileges and the unsafe
    shell flag.
  - ``/linux`` – open an interactive shell session (admin only;
    disabled by default).  Subsequent messages are run as shell
    commands.  Use ``/cd``, ``/pwd`` and ``/exit`` to navigate.
  - ``/exec <cmd>`` – run a one‑off shell command (admin only;
    disabled by default).

## Prerequisites

Before installing the bot you need to have:

1. **Python 3.7+** installed.  ALT Linux comes with Python by
   default.
2. **upower** and **lm_sensors** packages.  Install them with:

   ```bash
   sudo apt-get update
   sudo apt-get install upower lm_sensors python3-pip
   # optional but recommended: detect available sensors
   sudo sensors-detect
   ```

3. **Python libraries** – install the required packages for the bot:

   ```bash
   python3 -m pip install --upgrade "python-telegram-bot[job-queue]==20.7"
   ```

4. **A Telegram bot token**.  Create a bot via
   [@BotFather](https://t.me/BotFather):
   - Start a chat with @BotFather and send ``/newbot``.
   - Choose a name and a username for your bot.
   - Copy the API token that BotFather returns – you will need it
     for the ``BOT_TOKEN`` environment variable.

5. **Your chat ID** (optional but needed for admin commands).  After
   running the bot, send ``/whoami`` in your chat with the bot and
   it will reply with your numeric chat ID.  Use this value in the
   ``ADMIN_CHAT_ID`` environment variable or set it via the
   ``/setadmin`` command.

## Installation

Clone or download this repository on the target machine:

```bash
git clone <repository-url> ~/alt-station
cd ~/alt-station
```

The important files are:

* **``battery_bot.py``** – the Python script implementing the bot.
* **``batterybot.service``** – a sample systemd unit for running the
  bot as a user service.
* **``README.md``** – this file.

### Running manually

Set the required environment variable and run the script:

```bash
export BOT_TOKEN="<your-telegram-bot-token>"
python3 battery_bot.py
```

The bot will start polling Telegram and will respond to commands.

### Installing as a user service (recommended)

Running the bot as a systemd **user** service ensures it starts
automatically when you log into your session.  To install:

1. Copy the systemd unit into your user configuration directory and
   edit it to provide your token and optional settings:

   ```bash
   mkdir -p ~/.config/systemd/user
   cp batterybot.service ~/.config/systemd/user/
   # Edit the service to set BOT_TOKEN and other variables
   nano ~/.config/systemd/user/batterybot.service
   ```

   Adjust the ``ExecStart=`` line if you cloned the repository in a
   different location.

2. Reload the systemd user manager and enable/start the service:

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now batterybot.service
   ```

3. Verify that it’s running:

   ```bash
   systemctl --user status batterybot.service
   ```

The bot will now run in the background whenever you are logged in.

## Configuration via Environment Variables

The service file defines environment variables that control the
behaviour of the bot.  You can modify or add them in
``batterybot.service`` under the ``[Service]`` section:

| Variable              | Description                                                   |
|-----------------------|---------------------------------------------------------------|
| **BOT_TOKEN**         | *Required.* Telegram API token from @BotFather.              |
| **CHECK_INTERVAL_SEC**| How often to check the battery (seconds). Default ``60``.    |
| **ALERT_THRESHOLD**   | Battery % to trigger low battery alerts. Default ``20``.      |
| **ALERT_HYSTERESIS**  | Battery % at which recovery messages are sent. Default ``25``.|
| **ADMIN_CHAT_ID**     | Telegram chat ID allowed to use admin commands. Default ``0`` (disabled). |
| **ENABLE_UNSAFE_SHELL** | Set to ``1`` to enable the interactive shell and ``/exec`` commands for the admin. |
| **DISABLE_SENSORS**   | Set to ``1`` to skip calling ``sensors``. Useful if lm_sensors isn't configured. |
| **STATE_DIR**         | Directory where state files are stored. Defaults to ``~/.battery_bot``. |

After editing the service file, reload and restart it:

```bash
systemctl --user daemon-reload
systemctl --user restart batterybot.service
```

## Using the Bot

1. **Start the bot** and open a chat with your bot on Telegram.
2. Send ``/start`` to see a list of commands.  Use ``/battery``
   anytime to get the current battery, temperature and fan status.
3. Send ``/subscribe`` to receive notifications about low battery and
   power events; ``/unsubscribe`` to stop them.
4. If you set an admin chat ID, you can enable the interactive
   shell:

   ```bash
   # either via environment variable
   export ADMIN_CHAT_ID=<your-id>
   export ENABLE_UNSAFE_SHELL=1
   # or via commands in Telegram
   /setadmin <your-id>
   /enable_shell
   ```

   Then send ``/linux`` to open a shell session.  Any subsequent
   messages will be executed on the host.  Use ``/exit`` to close
   the session.

5. Use ``/run help`` to see which safe commands are available.

## Troubleshooting

* **The bot doesn’t respond** – ensure the service is running and
  that ``BOT_TOKEN`` is correct.  Check logs via
  ``journalctl --user -u batterybot.service -f``.
* **Temperature reads “n/a”** – you may need to run
  ``sudo sensors-detect`` and load the appropriate kernel modules,
  or set ``DISABLE_SENSORS=1``.
* **Interactive shell commands fail** – make sure you have set
  ``ADMIN_CHAT_ID`` to your chat ID and ``ENABLE_UNSAFE_SHELL=1``.

## Contributing

Feel free to open issues or pull requests to improve the bot.  You
can add more safe command aliases to ``SAFE_CMD_MAP`` or extend
functionality as needed.