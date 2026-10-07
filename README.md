# NRB Discord Hosting Bot — Panel Edition

`/create` logs into the NRB Panel as the configured administrator, creates a random NRB user, then creates that user's VPS through the existing admin routes.

Configuration:
- `NRB_PANEL_URL`
- `NRB_ADMIN_USERNAME`
- `NRB_ADMIN_PASSWORD`
- `DEFAULT_NODE_ID`
- `DEFAULT_OS`, `DEFAULT_CPU`, `DEFAULT_RAM`, `DEFAULT_DISK`

Ubuntu setup:
```bash
unzip NRB_Discord_Hosting_Bot_Panel.zip
cd NRB_Discord_Hosting_Bot_Portal
./install.sh
nano .env
./start.sh
```

24/7:
```bash
sudo mkdir -p /opt/nrb-discord-bot
sudo cp -r . /opt/nrb-discord-bot/
sudo cp nrb-discord-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nrb-discord-bot
```

The bot uses the panel's existing `/login`, `/admin/users/create`, and `/admin/vps/create` routes found in the supplied NRB source. It does not copy HVM/AVM code.
