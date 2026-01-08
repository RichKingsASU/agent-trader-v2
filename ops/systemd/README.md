# VM ingest hardening (systemd)

This folder provides **systemd unit templates** + **env-file templates** to run ingestion processes on a VM without restart storms and with usable logs.

## 1) Detect what the VM uses today (supervisor vs systemd vs nohup)

Run on the VM:

```bash
# systemd?
systemctl list-units --type=service | grep -i ingest || true
systemctl status agenttrader-market-ingest.service || true
systemctl status agenttrader-congressional-ingest.service || true

# supervisor?
command -v supervisorctl >/dev/null && supervisorctl status || true
ls -la /etc/supervisor/conf.d 2>/dev/null || true

# nohup/screen/tmux ad-hoc?
ps auxww | egrep -i "backend\.ingestion|market_data_ingest|congressional_disclosures|nohup|screen|tmux" | grep -v egrep || true
```

## 2) Install (idempotent) — systemd + journald best-practice

Assumptions:
- Repo is deployed to: `/opt/agenttrader/agent-trader-v2`
- You have (or will create) a service user: `agenttrader`

### Create directories + user (safe to rerun)

```bash
sudo id -u agenttrader >/dev/null 2>&1 || sudo useradd --system --create-home --shell /usr/sbin/nologin agenttrader
sudo install -d -m 0755 /etc/agenttrader
```

### Install env files (secrets) (safe to rerun)

Create these on the VM (do **not** commit secrets):

```bash
sudo install -m 0640 -o root -g agenttrader /dev/null /etc/agenttrader/market-ingest.env
sudo install -m 0640 -o root -g agenttrader /dev/null /etc/agenttrader/congressional-ingest.env
```

Then edit them with your values:

```bash
sudoedit /etc/agenttrader/market-ingest.env
sudoedit /etc/agenttrader/congressional-ingest.env
```

### Install journald persistence/caps (optional, idempotent)

```bash
sudo install -d -m 0755 /etc/systemd/journald.conf.d
sudo install -m 0644 /opt/agenttrader/agent-trader-v2/ops/systemd/journald-agenttrader.conf /etc/systemd/journald.conf.d/10-agenttrader.conf
sudo systemctl restart systemd-journald
```

### Install + enable services (idempotent)

```bash
sudo install -m 0644 /opt/agenttrader/agent-trader-v2/ops/systemd/agenttrader-market-ingest.service /etc/systemd/system/agenttrader-market-ingest.service
sudo install -m 0644 /opt/agenttrader/agent-trader-v2/ops/systemd/agenttrader-congressional-ingest.service /etc/systemd/system/agenttrader-congressional-ingest.service

sudo systemctl daemon-reload

# Enable one or both:
sudo systemctl enable --now agenttrader-market-ingest.service
sudo systemctl enable --now agenttrader-congressional-ingest.service
```

## 3) Operational usage (logs + storm-proofing behavior)

### Logs (usable, no log files to chase)

```bash
# Follow logs
journalctl -u agenttrader-market-ingest.service -f
journalctl -u agenttrader-congressional-ingest.service -f

# Last 2 hours
journalctl -u agenttrader-market-ingest.service --since "2 hours ago"
```

### Restart storm prevention (what happens)

Both units implement:
- **Backoff** via `RestartSec=...`
- **Circuit breaker** via `StartLimitIntervalSec` + `StartLimitBurst`
- **No-loop on misconfig** via `ConditionPathExists=...` (won’t start if env/repo path missing)

If the service keeps failing fast, systemd will stop retrying and you’ll see:

```bash
systemctl status agenttrader-market-ingest.service
```

## 4) Rollback steps

### Stop + disable services

```bash
sudo systemctl disable --now agenttrader-market-ingest.service || true
sudo systemctl disable --now agenttrader-congressional-ingest.service || true
```

### Remove unit files

```bash
sudo rm -f /etc/systemd/system/agenttrader-market-ingest.service
sudo rm -f /etc/systemd/system/agenttrader-congressional-ingest.service
sudo systemctl daemon-reload
```

### Remove journald drop-in (optional)

```bash
sudo rm -f /etc/systemd/journald.conf.d/10-agenttrader.conf
sudo systemctl restart systemd-journald
```

### (Optional) Remove env files

```bash
sudo rm -f /etc/agenttrader/market-ingest.env /etc/agenttrader/congressional-ingest.env
```

