# Доступ к файлам ALT‑Station: Samba и Tailscale Serve

## 1. Локальный доступ через Samba (SMB)

### Установка
```bash
sudo apt-get install samba
sudo smbpasswd -a gregory
```

### Конфигурация `/etc/samba/smb.conf`
```
[gregory]
path = /home/gregory
read only = no
browseable = yes
guest ok = no
create mask = 0755
```

### Подключение с iPad
`Файлы → … → Подключиться к серверу → smb://<IP>/gregory`

---

## 2. Удалённый доступ через Tailscale Serve

### Установка
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh
```

### Автозапуск службы
```
/etc/systemd/system/tailscaled.service
ExecStart=/usr/local/bin/tailscaled
```

### Публикация каталога
```bash
sudo tailscale serve --bg /home/gregory
sudo tailscale serve status
```

Доступ по адресу `https://<устройство>.ts.net` внутри Tailnet.

Для публичной ссылки:
```bash
sudo tailscale funnel --bg /home/gregory
```
