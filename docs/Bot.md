# Бот мониторинга заряда и температуры ALT‑Station

Бот отслеживает уровень заряда аккумулятора, температуру CPU и скорость вентиляторов на ALT Linux и отправляет уведомления в Telegram.

## Возможности

- Мониторинг батареи (`upower`)
- Температура и вентилятор (`lm_sensors` или `/sys`)
- Команды `/battery`, `/subscribe`, `/run`, `/whoami`, `/linux`, `/exec` и др.

## Требования

```bash
sudo apt-get install upower lm_sensors python3-pip
python3 -m pip install --upgrade "python-telegram-bot[job-queue]==20.7"
```

## Установка

```bash
git clone <repo>
cd ~/alt-station
export BOT_TOKEN="<токен>"
python3 battery_bot.py
```

## Автозапуск через systemd

```bash
mkdir -p ~/.config/systemd/user
cp batterybot.service ~/.config/systemd/user/
nano ~/.config/systemd/user/batterybot.service

systemctl --user daemon-reload
systemctl --user enable --now batterybot.service
```

## Переменные окружения

| Переменная | Описание |
|-------------|-----------|
| `BOT_TOKEN` | API‑токен |
| `CHECK_INTERVAL_SEC` | Интервал проверки (сек) |
| `ALERT_THRESHOLD` | Порог предупреждения |
| `ADMIN_CHAT_ID` | ID администратора |
| `ENABLE_UNSAFE_SHELL` | Разрешить интерактивную консоль |
| `DISABLE_SENSORS` | Отключить `sensors` |

## Использование

Отправьте `/start`, затем `/battery`.  
Админ может использовать `/linux` для интерактивной оболочки.  

Просмотр логов:
```bash
journalctl --user -u batterybot.service -f
```
