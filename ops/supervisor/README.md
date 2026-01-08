# VM ingest hardening (supervisor)

Use this if the VM already runs ingestion under **Supervisor** (instead of systemd).

## Detect supervisor on the VM

```bash
command -v supervisorctl >/dev/null && supervisorctl status || true
ps auxww | egrep -i "supervisord|supervisorctl" | grep -v egrep || true
ls -la /etc/supervisor/conf.d 2>/dev/null || true
```

## Install (idempotent)

Assumptions:
- Repo is deployed to `/opt/agenttrader/agent-trader-v2`
- A service user exists: `agenttrader`

```bash
sudo id -u agenttrader >/dev/null 2>&1 || sudo useradd --system --create-home --shell /usr/sbin/nologin agenttrader
sudo install -d -m 0755 /etc/agenttrader
sudo install -d -m 0755 /var/log/agenttrader

# Create env files (secrets) (do not commit them)
sudo install -m 0640 -o root -g agenttrader /dev/null /etc/agenttrader/market-ingest.env
sudo install -m 0640 -o root -g agenttrader /dev/null /etc/agenttrader/congressional-ingest.env
sudoedit /etc/agenttrader/market-ingest.env
sudoedit /etc/agenttrader/congressional-ingest.env

# Install supervisor program configs
sudo install -m 0644 /opt/agenttrader/agent-trader-v2/ops/supervisor/agenttrader-market-ingest.conf /etc/supervisor/conf.d/agenttrader-market-ingest.conf
sudo install -m 0644 /opt/agenttrader/agent-trader-v2/ops/supervisor/agenttrader-congressional-ingest.conf /etc/supervisor/conf.d/agenttrader-congressional-ingest.conf

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status
```

## Rollback

```bash
sudo supervisorctl stop agenttrader-market-ingest || true
sudo supervisorctl stop agenttrader-congressional-ingest || true

sudo rm -f /etc/supervisor/conf.d/agenttrader-market-ingest.conf
sudo rm -f /etc/supervisor/conf.d/agenttrader-congressional-ingest.conf

sudo supervisorctl reread
sudo supervisorctl update
```

