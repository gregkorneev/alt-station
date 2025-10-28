#!/usr/bin/env python3
"""
Battery and temperature monitoring bot for ALT Workstation
========================================================

This script implements a Telegram bot that runs on an ALT Linux
workstation (or any Linux system) and monitors the laptop's
battery level, CPU temperature and fan status.  It sends
notifications via Telegram when the battery gets low or when the
charging state changes, and provides commands to query the
current state on demand.  An optional interactive shell and a set
of predefined safe commands are available for administrators.

Features
--------

* **Notifications:** When the battery percentage drops below
  ``ALERT_THRESHOLD`` (default 20 %) and the machine is not
  charging, subscribed users receive a warning.  When the
  percentage climbs above ``ALERT_HYSTERESIS`` (default 25 %), a
  recovery message is sent.  The bot also notifies on changes in
  the charging state (plugged or unplugged).
* **Commands:**
  - ``/start`` – explains available commands.
  - ``/battery`` – displays current battery percentage,
    charging state, CPU temperature and fan status.
  - ``/subscribe`` and ``/unsubscribe`` – manage push
    notifications for the current chat.
  - ``/run <alias>`` – execute a pre-defined safe command on the
    host (see ``SAFE_CMD_MAP`` below).  Use ``/run help`` to see
    available aliases.
  - ``/whoami`` – returns your chat ID (useful for
    ``ADMIN_CHAT_ID``).
  - ``/linux`` – open an interactive shell session for
    administrators; subsequent messages are executed as shell
    commands.  Use ``/cd``, ``/pwd`` and ``/exit`` to navigate
    directories and close the session.  Disabled by default unless
    ``ADMIN_CHAT_ID`` and ``ENABLE_UNSAFE_SHELL`` are configured.
  - ``/exec <command>`` – execute a one‑off shell command as
    admin (also disabled by default).
  - ``/adminstatus``, ``/setadmin <id>``, ``/enable_shell`` and
    ``/disable_shell`` – manage admin privileges and the unsafe
    shell flag.

The bot persists a minimal amount of state (subscribers, last
reported battery percentage and charging state) in text files
under ``STATE_DIR`` so that notifications aren’t sent repeatedly
on every check.

Before running this bot you need to:

* Create a Telegram bot via @BotFather and obtain a token.  See
  the README for detailed instructions.
* Install required Python packages.  The bot uses
  ``python-telegram-bot`` version 20.x and optionally
  ``lm-sensors`` for temperature and fan data.
* Make sure ``upower`` and (optionally) ``lm_sensors`` are
  installed on your system.  On ALT Linux you can install them
  with ``sudo apt-get install upower lm_sensors``.  To enable
  sensor readings run ``sudo sensors-detect`` and follow the
  prompts.  If sensors are unavailable you can set the
  ``DISABLE_SENSORS`` environment variable to ``1`` and the bot
  will avoid calling ``sensors``.

The accompanying ``batterybot.service`` file can be used as a
systemd unit to run the bot automatically on login.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import glob
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

###############################################################################
# Configuration and persistent state

# The bot token must be provided via the environment.  Use @BotFather to
# create a new bot and copy the token.
BOT_TOKEN = os.getenv("BOT_TOKEN", "<PUT_TOKEN>")

# Directory for storing state files.  Defaults to ~/.battery_bot
STATE_DIR = Path(os.getenv("STATE_DIR", str(Path.home() / ".battery_bot")))
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Files for subscribers and last known state
SUBSCRIBERS_FILE = STATE_DIR / "subscribers.txt"
LAST_STATE_FILE = STATE_DIR / "last_state.txt"      # "normal" or "alert"
LAST_PERCENT_FILE = STATE_DIR / "last_percent.txt"  # last battery percentage
LAST_CHARGE_FILE = STATE_DIR / "last_charge.txt"    # last charging state

# Admin and shell settings
ADMIN_FILE = STATE_DIR / "admin_chat_id.txt"
SHELL_FLAG_FILE = STATE_DIR / "enable_shell.txt"

# Polling interval and alert thresholds
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "60"))
ALERT_THRESHOLD = int(os.getenv("ALERT_THRESHOLD", "20"))
ALERT_HYSTERESIS = int(os.getenv("ALERT_HYSTERESIS", "25"))

# Admin environment variables
ENV_ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
ENV_ENABLE_UNSAFE_SHELL = os.getenv("ENABLE_UNSAFE_SHELL", "0").lower() in ("1", "true", "yes", "on")

# Sensor control: set DISABLE_SENSORS=1 to skip calling sensors(1)
DISABLE_SENSORS = os.getenv("DISABLE_SENSORS", "0").lower() in ("1", "true", "yes", "on")
_SENSORS_BROKEN = False  # internal flag set after first failure

# Maximum message length for command outputs (Telegram limit ~4096)
MAX_MSG_LEN = 3800

###############################################################################
# Utility functions for file I/O

def _read_text(path: Path, default: str = "") -> str:
    """Read a file and strip whitespace; return default on error."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return default


def _write_text(path: Path, value: str) -> None:
    """Write a string to a file; ignore errors."""
    try:
        path.write_text(value, encoding="utf-8")
    except Exception:
        pass


def _load_admin_chat_id() -> int:
    txt = _read_text(ADMIN_FILE, "")
    return int(txt) if txt.isdigit() else ENV_ADMIN_CHAT_ID


def _shell_enabled() -> bool:
    txt = _read_text(SHELL_FLAG_FILE, "")
    if txt:
        return txt.lower() in ("1", "true", "yes", "on")
    return ENV_ENABLE_UNSAFE_SHELL


###############################################################################
# System information retrieval

def read_battery() -> Tuple[int, str]:
    """Return (percentage, state) for the laptop battery.

    Uses upower to obtain the current battery level and charging state.  If
    upower fails, falls back to reading from /sys/class/power_supply.
    Returns (-1, "unknown") if no data is available.
    """
    # Try upower first
    try:
        out = subprocess.check_output(
            ["upower", "-i", "/org/freedesktop/UPower/devices/battery_BAT0"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        perc = re.search(r"percentage:\s*(\d+)%", out)
        state = re.search(r"state:\s*(\w+)", out)
        if perc and state:
            return int(perc.group(1)), state.group(1)
    except Exception:
        pass
    # Fallback to /sys
    try:
        with open("/sys/class/power_supply/BAT0/capacity", "r") as f:
            percent = int(f.read().strip())
        with open("/sys/class/power_supply/BAT0/status", "r") as f:
            status = f.read().strip().lower()
        return percent, status
    except Exception:
        return -1, "unknown"


def _sensors_json() -> Optional[dict]:
    """Return a JSON dict from sensors(1), or None on failure.

    On the first failure, the internal _SENSORS_BROKEN flag is set
    to avoid repeated calls.
    """
    global _SENSORS_BROKEN
    if DISABLE_SENSORS or _SENSORS_BROKEN:
        return None
    try:
        out = subprocess.check_output(["sensors", "-j"], text=True, stderr=subprocess.DEVNULL)
        return json.loads(out)
    except Exception:
        _SENSORS_BROKEN = True
        return None


def get_cpu_temp_c() -> Optional[float]:
    """Return the current CPU temperature in °C, or None if unavailable."""
    data = _sensors_json()
    best: Optional[float] = None
    if data:
        prefer = ("Package id", "Tctl", "Tdie")  # vendor-specific labels
        for chip, sensors in data.items():
            if not isinstance(sensors, dict):
                continue
            for label, values in sensors.items():
                if not isinstance(values, dict):
                    continue
                temps = []
                for k, v in values.items():
                    if k.startswith("temp") and k.endswith("_input"):
                        try:
                            temps.append(float(v))
                        except Exception:
                            pass
                if temps:
                    tmax = max(temps)
                    # Prefer CPU package sensors, otherwise take any
                    if any(p.lower() in label.lower() for p in prefer):
                        if best is None or tmax > best:
                            best = tmax
                    elif best is None:
                        best = tmax
    if best is None:
        # Fallback: read thermal zones in /sys
        try:
            vals: List[float] = []
            for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
                with open(path, "r") as f:
                    txt = f.read().strip()
                if txt.isdigit():
                    iv = int(txt)
                    vals.append(iv / 1000.0 if iv > 1000 else float(iv))
            if vals:
                best = max(vals)
        except Exception:
            pass
    return round(best, 1) if best is not None else None


def get_fan_status() -> str:
    """Return a textual description of the fan speed."""
    data = _sensors_json()
    rpms: List[int] = []
    if data:
        for chip, sensors in data.items():
            if not isinstance(sensors, dict):
                continue
            for label, values in sensors.items():
                if not isinstance(values, dict):
                    continue
                for k, v in values.items():
                    if k.startswith("fan") and k.endswith("_input"):
                        try:
                            rpms.append(int(float(v)))
                        except Exception:
                            pass
    if not rpms:
        for path in glob.glob("/sys/class/hwmon/hwmon*/fan*_input"):
            try:
                with open(path, "r") as f:
                    rpms.append(int(f.read().strip()))
            except Exception:
                pass
    if not rpms:
        return "unknown"
    m = max(rpms)
    return f"running ~ {m} RPM" if m > 0 else "off/idle"


###############################################################################
# Subscriber management

def load_subscribers() -> set[int]:
    if not SUBSCRIBERS_FILE.exists():
        return set()
    res: set[int] = set()
    for line in _read_text(SUBSCRIBERS_FILE, "").splitlines():
        s = line.strip()
        if s.isdigit():
            res.add(int(s))
    return res


def save_subscribers(subs: set[int]) -> None:
    SUBSCRIBERS_FILE.write_text("\n".join(str(x) for x in sorted(subs)), encoding="utf-8")


###############################################################################
# Shell session management for interactive console

# Stores current working directory per chat ID for interactive shell
SHELL_SESSIONS: Dict[int, Path] = {}


def _truncate(msg: str, limit: int = MAX_MSG_LEN) -> str:
    return msg if len(msg) <= limit else (msg[:limit] + "\n…[truncated]")


###############################################################################
# Command handlers

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Я слежу за батареей, температурой и кулером вашего ноутбука.\n"
        "Доступные команды:\n"
        "/battery — показать текущее состояние\n"
        "/subscribe — подписаться на уведомления\n"
        "/unsubscribe — отписаться от уведомлений\n"
        "/run help — список безопасных команд\n"
        "/whoami — узнать свой chat_id\n"
        "Админские: /linux, /exec, /adminstatus, /setadmin, /enable_shell, /disable_shell"
    )


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Ваш chat_id: {update.effective_chat.id}")


async def cmd_battery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    percent, state = read_battery()
    temp = get_cpu_temp_c()
    fan = get_fan_status()
    if percent < 0:
        await update.message.reply_text("Не удалось прочитать состояние батареи.")
        return
    t = f"{temp}°C" if temp is not None else "n/a"
    await update.message.reply_text(
        f"Батарея: {percent}% ({state})\nТемпература (CPU): {t}\nКулер: {fan}"
    )


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subs = load_subscribers()
    subs.add(update.effective_chat.id)
    save_subscribers(subs)
    await update.message.reply_text("Подписал. Теперь вы будете получать уведомления о батарее.")


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subs = load_subscribers()
    subs.discard(update.effective_chat.id)
    save_subscribers(subs)
    await update.message.reply_text("Больше не будете получать уведомления.")


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        aliases = " ".join(sorted(SAFE_CMD_MAP.keys()))
        await update.message.reply_text(
            "Использование: /run <алиас>\nДоступные: " + aliases + "\nПодсказка: /run help"
        )
        return
    if args[0] == "help":
        lines = [f"{k} → `{v}`" for k, v in sorted(SAFE_CMD_MAP.items())]
        await update.message.reply_text(
            "Белый список:\n" + "\n".join(lines), parse_mode="Markdown"
        )
        return
    alias = args[0]
    if alias not in SAFE_CMD_MAP:
        await update.message.reply_text("Неизвестный алиас. /run help")
        return
    try:
        proc = subprocess.run(
            SAFE_CMD_MAP[alias],
            shell=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        text = f"$ {SAFE_CMD_MAP[alias]}\n\n{proc.stdout or ''}{proc.stderr or ''}\n(exit {proc.returncode})"
        await update.message.reply_text(_truncate(text))
    except subprocess.TimeoutExpired:
        await update.message.reply_text("✋ Команда превысила лимит времени (20 с).")


async def cmd_adminstatus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    effective = _load_admin_chat_id()
    await update.message.reply_text(
        f"ADMIN_CHAT_ID (env): {ENV_ADMIN_CHAT_ID}\n"
        f"ADMIN_CHAT_ID (effective): {effective}\n"
        f"enable_shell flag (effective): {_shell_enabled()}\n"
        f"Ваш chat_id: {update.effective_chat.id}"
    )


async def cmd_setadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    effective = _load_admin_chat_id()
    requester = update.effective_chat.id
    if effective not in (0, requester) and requester != ENV_ADMIN_CHAT_ID:
        await update.message.reply_text("Недостаточно прав для /setadmin.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /setadmin <chat_id>")
        return
    _write_text(ADMIN_FILE, context.args[0])
    await update.message.reply_text(f"OK. ADMIN_CHAT_ID теперь {_read_text(ADMIN_FILE)}")


async def cmd_enable_shell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("Недостаточно прав.")
        return
    _write_text(SHELL_FLAG_FILE, "1")
    await update.message.reply_text("Интерактивная консоль: ВКЛ.")


async def cmd_disable_shell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("Недостаточно прав.")
        return
    _write_text(SHELL_FLAG_FILE, "0")
    await update.message.reply_text("Интерактивная консоль: ВЫКЛ.")


def _is_admin(update: Update) -> bool:
    return (
        update.effective_chat is not None
        and update.effective_chat.id == _load_admin_chat_id()
        and _load_admin_chat_id() != 0
    )


async def cmd_exec(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update) or not _shell_enabled():
        await update.message.reply_text("Команда недоступна.")
        return
    raw = " ".join(context.args).strip()
    if not raw:
        await update.message.reply_text("Использование: /exec <команда>")
        return
    try:
        proc = subprocess.run(
            raw,
            shell=True,
            capture_output=True,
            text=True,
            timeout=25,
        )
        text = f"$ {raw}\n\n{proc.stdout or ''}{proc.stderr or ''}\n(exit {proc.returncode})"
        await update.message.reply_text(_truncate(text))
    except subprocess.TimeoutExpired:
        await update.message.reply_text("✋ Команда превысила лимит времени (25 с).")


async def cmd_linux(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update) or not _shell_enabled():
        await update.message.reply_text("Команда недоступна.")
        return
    chat_id = update.effective_chat.id
    if chat_id in SHELL_SESSIONS:
        await update.message.reply_text("Консоль уже открыта.\nИспользуйте /exit для выхода.")
        return
    SHELL_SESSIONS[chat_id] = Path.home()
    await update.message.reply_text(
        "🔐 Интерактивная консоль открыта.\n"
        "Отправляйте команды, чтобы выполнить их.\n"
        "Команды:\n"
        "• /cd <путь> — смена каталога\n"
        "• /pwd — показать текущий каталог\n"
        "• /exit — закрыть консоль"
    )


async def cmd_pwd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id not in SHELL_SESSIONS:
        await update.message.reply_text("Консоль не открыта. Используйте /linux.")
        return
    await update.message.reply_text(str(SHELL_SESSIONS[chat_id]))


async def cmd_cd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id not in SHELL_SESSIONS:
        await update.message.reply_text("Консоль не открыта. Используйте /linux.")
        return
    args = context.args
    if not args:
        SHELL_SESSIONS[chat_id] = Path.home()
        await update.message.reply_text(f"cd ~ → {SHELL_SESSIONS[chat_id]}")
        return
    target = Path(args[0]).expanduser()
    if not target.is_absolute():
        target = (SHELL_SESSIONS[chat_id] / target).resolve()
    if target.exists() and target.is_dir():
        SHELL_SESSIONS[chat_id] = target
        await update.message.reply_text(f"OK: {target}")
    else:
        await update.message.reply_text("Нет такого каталога.")


async def cmd_exit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in SHELL_SESSIONS:
        del SHELL_SESSIONS[chat_id]
        await update.message.reply_text("Консоль закрыта.")
    else:
        await update.message.reply_text("Консоль не открыта.")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    # Only handle plain messages when a session is active
    if chat_id not in SHELL_SESSIONS:
        return
    # Check permissions again
    if not _is_admin(update) or not _shell_enabled():
        await update.message.reply_text("Сеанс закрыт: недостаточно прав.")
        del SHELL_SESSIONS[chat_id]
        return
    raw = (update.message.text or "").strip()
    if not raw:
        return
    # Support triple backticks to ignore code fences
    if raw.startswith("```") and raw.endswith("```"):
        raw = raw.strip("`").strip()
    cwd = SHELL_SESSIONS[chat_id]
    try:
        proc = subprocess.run(
            raw,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=25,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        prefix = f"{cwd}$ {raw}\n\n"
        await update.message.reply_text(_truncate(prefix + out + f"\n(exit {proc.returncode})"))
    except subprocess.TimeoutExpired:
        await update.message.reply_text("✋ Команда превысила лимит времени (25 с).")


###############################################################################
# Safe command map

SAFE_CMD_MAP: Dict[str, str] = {
    "uptime": "uptime",
    "df": "df -h",
    "free": "free -h",
    "top1": "ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -n 12",
    "temp": "sensors",
    "ip": "ip -br a",
    "disk": "lsblk -o NAME,SIZE,TYPE,MOUNTPOINT",
}


###############################################################################
# Periodic job: monitor battery and send notifications

async def job_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    subs = load_subscribers()
    percent, state = read_battery()
    if percent < 0:
        return
    temp = get_cpu_temp_c()
    fan = get_fan_status()
    # Update last percentage and state
    last_p_txt = _read_text(LAST_PERCENT_FILE, "")
    last_p = int(last_p_txt) if last_p_txt.isdigit() else None
    crossed20 = last_p is not None and last_p > 20 and percent <= 20
    # Low battery alert with hysteresis
    last_state = _read_text(LAST_STATE_FILE, "normal")
    # Only notify if there are subscribers
    if subs:
        # 1) Crossing the 20% boundary
        if crossed20:
            text = (
                f"⚠️ Заряд достиг 20 %\n"
                f"Сейчас: {percent}% ({state})\n"
                f"Температура: {temp if temp is not None else 'n/a'}°C\n"
                f"Кулер: {fan}"
            )
            for cid in subs:
                await context.bot.send_message(cid, text)
        # 2) General low battery
        if not crossed20:
            if last_state != "alert" and percent <= ALERT_THRESHOLD and state != "charging":
                text = (
                    f"⚠️ Низкий заряд: {percent}% ({state})\n"
                    f"Температура: {temp if temp is not None else 'n/a'}°C\n"
                    f"Кулер: {fan}"
                )
                for cid in subs:
                    await context.bot.send_message(cid, text)
                _write_text(LAST_STATE_FILE, "alert")
            elif last_state == "alert" and percent >= ALERT_HYSTERESIS:
                text = (
                    f"✅ Заряд восстановился до {percent}%\n"
                    f"Температура: {temp if temp is not None else 'n/a'}°C\n"
                    f"Кулер: {fan}"
                )
                for cid in subs:
                    await context.bot.send_message(cid, text)
                _write_text(LAST_STATE_FILE, "normal")
        # 3) Charging state change
        last_charge = _read_text(LAST_CHARGE_FILE, "")
        if state != last_charge and last_charge != "":
            # Determine message based on transition
            if state == "charging" and last_charge in ("discharging", "unknown"):
                msg = f"🔌 Питание ПОДКЛЮЧЕНО • {percent}%"
            elif last_charge == "charging" and state in ("discharging", "full"):
                msg = f"🔋 Питание ОТКЛЮЧЕНО • {percent}%"
            else:
                msg = f"ℹ️ Состояние батареи: {last_charge} → {state} • {percent}%"
            for cid in subs:
                await context.bot.send_message(cid, msg)
    _write_text(LAST_CHARGE_FILE, state)
    _write_text(LAST_PERCENT_FILE, str(percent))


###############################################################################
# Main entry point

def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN.startswith("<PUT_TOKEN>"):
        raise RuntimeError("Не задан BOT_TOKEN (получите его у @BotFather)")
    app = Application.builder().token(BOT_TOKEN).build()
    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("battery", cmd_battery))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("run", cmd_run))
    # Admin commands
    app.add_handler(CommandHandler("adminstatus", cmd_adminstatus))
    app.add_handler(CommandHandler("setadmin", cmd_setadmin))
    app.add_handler(CommandHandler("enable_shell", cmd_enable_shell))
    app.add_handler(CommandHandler("disable_shell", cmd_disable_shell))
    app.add_handler(CommandHandler("exec", cmd_exec))
    app.add_handler(CommandHandler("linux", cmd_linux))
    app.add_handler(CommandHandler("pwd", cmd_pwd))
    app.add_handler(CommandHandler("cd", cmd_cd))
    app.add_handler(CommandHandler("exit", cmd_exit))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_text))
    # Schedule periodic job
    app.job_queue.run_repeating(job_check, interval=CHECK_INTERVAL_SEC, first=5)
    # Run bot
    app.run_polling()


if __name__ == "__main__":
    main()