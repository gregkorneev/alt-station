# Настройка VS Code для ALT-Station

Этот документ описывает, как настроить удалённый доступ к окружению разработки на ALT Linux workstation, чтобы вы могли редактировать и запускать код с iPad или другого компьютера. Существует два основных варианта: веб‑версия VS Code (code‑server) и удалённое подключение через SSH c помощью настольной версии VS Code.

## Вариант 1. code‑server (веб‑VS Code)

`code‑server` — это серверная версия Visual Studio Code, которая предоставляет интерфейс в браузере. Это решение удобно для планшетов: достаточно открыть ссылку в браузере.

### Установка code‑server

1. Обновите систему и установите зависимости:
   ```bash
   sudo apt-get update
   sudo apt-get install curl
   ```

2. Скачайте и выполните официальный скрипт установки от разработчиков:
   ```bash
   curl -fsSL https://code-server.dev/install.sh | sh
   ```
   Скрипт автоматически загрузит последнюю версию и создаст бинарник `code-server` в `/usr/lib/code-server`.

3. Создайте директорию для работы и настройте пароль. Например, будем запускать сервер от вашего пользователя:
   ```bash
   mkdir -p ~/.config/code-server
   echo "password: ВашПароль" > ~/.config/code-server/config.yaml
   ```
   Вместо `ВашПароль` укажите сложный пароль, который будете использовать для входа.

### Создание службы systemd

Чтобы сервер запускался автоматически, создайте файл `~/.config/systemd/user/code-server.service` со следующим содержимым:

```ini
[Unit]
Description=code-server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/code-server --bind-addr 0.0.0.0:8080
Restart=always
WorkingDirectory=%h
Environment=PASSWORD=ВашПароль

[Install]
WantedBy=default.target
```

Замените `ВашПароль` на свой пароль. Затем активируйте сервис:

```bash
systemctl --user daemon-reload
systemctl --user enable --now code-server.service
```

### Подключение к code‑server

1. Узнайте IP‑адрес станции: `ip -4 a` или используйте адрес, выданный Tailscale ( например, 100.x.y.z ).
2. На iPad откройте браузер (Safari или Chrome) и перейдите по адресу `http://IP:8080/` (если используете Tailscale — `https://<имя>.ts.net`).
3. Введите пароль — откроется интерфейс VS Code.
4. В настройках (`Settings`) можно установить тему, плагины и т. д. Расположенный слева терминал позволяет выполнять команды на станции.

## Вариант 2. Удалённое SSH‑подключение для настольного VS Code

Если вы хотите использовать полноценный VS Code на другом компьютере (Windows/macOS/Linux) и подключаться к ALT‑станции по SSH, используйте расширение **Remote Development**:

1. Установите последнюю версию Visual Studio Code на своём компьютере.
2. Откройте панель расширений и установите пакет *Remote Development* (включает Remote‑SSH).
3. Убедитесь, что вы можете подключиться к станции по SSH:
   ```bash
   ssh gregory@IP
   ```
   где `gregory` — ваш пользователь на ALT Linux, а `IP` — адрес в локальной сети или Tailscale.
4. В VS Code нажмите `Ctrl+Shift+P` → “Remote‑SSH: Connect to Host…” → добавьте запись в `~/.ssh/config`:
   ```
   Host alt-station
     HostName IP
     User gregory
   ```
5. Затем выберите `alt-station` в списке. VS Code установит требуемые серверные компоненты (`~/.vscode-server`) и откроет удалённый рабочий стол. Теперь вы можете работать с файлами станции, запускать терминал, и всё будет выполняться на ALT Linux.

## Советы для iPad

Для iPad настольный VS Code недоступен, поэтому рекомендуем использовать code‑server. В качестве альтернативы можно:

- Использовать SSH‑клиент (Blink Shell, Termius) и работать в терминале.
- Подключиться к station через Tailscale Serve (см. [руководство по файлам](file.md)) и скачивать/загружать файлы для редактирования.

## Завершение

Теперь у вас есть два способа работы с кодом на ALT‑станции. Для планшета выбирайте code‑server; для настольных систем — Remote‑SSH. Не забывайте использовать безопасные пароли и подключаться только через доверенные сети (VPN/Tailscale).
