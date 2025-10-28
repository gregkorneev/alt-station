# Удалённый Visual Studio Code на ALT‑Station

## 1. Зачем нужен web‑VS Code
Работайте с кодом через браузер с iPad или другого компьютера без установки IDE.

## 2. Установка code‑server
```bash
sudo apt-get install curl
curl -fsSL https://code-server.dev/install.sh | sh
code-server --version
```

### systemd‑служба
`~/.config/systemd/user/code-server.service`
```
[Service]
Environment=PASSWORD=<пароль>
ExecStart=/usr/bin/code-server --bind-addr 0.0.0.0:8080 --auth password
Restart=always
```
```bash
systemctl --user enable --now code-server.service
```

## 3. Подключение
`http://IP:8080` или через `Tailscale` → `http://<tailscale-ip>:8080`

---

## 4. VS Code Tunnel
```bash
sudo apt-get install code
code tunnel user login --provider github
code tunnel service install
```

### Альтернатива вручную
```
[Service]
ExecStart=/usr/bin/code tunnel --name alt-station --accept-server-license-terms
```

```bash
systemctl --user enable --now vscode-tunnel.service
```

Подключение: `https://alt-station.vscode.dev` или `code --remote tunnel:alt-station`

---

## 5. Remote SSH
Используйте расширение **Remote SSH** в VS Code на ноутбуке:
- настройте SSH (через Tailscale);
- подключитесь через `Connect to Host...`.
