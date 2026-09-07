# Linux and Jetson installation

The systemd services run ClusterWatch from a dedicated virtual environment under `/opt/clusterwatch`, keep configuration in `/etc/clusterwatch`, and store controller data in `/var/lib/clusterwatch`. These steps target Ubuntu and NVIDIA Jetson systems running JetPack.

## Install the application

Install the required operating-system packages:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
```

Create a service account and the required directories:

```bash
sudo useradd --system --home-dir /var/lib/clusterwatch --create-home --shell /usr/sbin/nologin clusterwatch
sudo install -d -o root -g root -m 0755 /opt/clusterwatch
sudo install -d -o root -g clusterwatch -m 0750 /etc/clusterwatch
sudo install -d -o clusterwatch -g clusterwatch -m 0750 /var/lib/clusterwatch
```

Clone and install ClusterWatch:

```bash
sudo git clone https://github.com/TolgaBilgis/ClusterWatch.git /opt/clusterwatch/src
sudo python3 -m venv /opt/clusterwatch/venv
sudo /opt/clusterwatch/venv/bin/pip install /opt/clusterwatch/src
sudo install -o root -g root -m 0644 /opt/clusterwatch/src/deploy/systemd/*.service /etc/systemd/system/
```

## Configure the controller

Install the controller environment file:

```bash
sudo install -o root -g root -m 0600 \
  /opt/clusterwatch/src/deploy/systemd/controller.env.example \
  /etc/clusterwatch/controller.env
sudoedit /etc/clusterwatch/controller.env
```

Set `CW_API_KEY` to a long random value if agent authentication is required. Leave it empty to retain the default trusted-LAN behavior. Start the controller and verify its health endpoint:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now clusterwatch-controller
systemctl status clusterwatch-controller
curl http://127.0.0.1:8000/health
```

The dashboard, API, Prometheus endpoint, and agent receiver listen on port `8000`. Permit that port only from the trusted cluster network when configuring a firewall.

## Configure an agent

Install and edit the agent environment file on every monitored machine:

```bash
sudo install -o root -g root -m 0600 \
  /opt/clusterwatch/src/deploy/systemd/agent.env.example \
  /etc/clusterwatch/agent.env
sudoedit /etc/clusterwatch/agent.env
```

Set `CW_CONTROLLER_URL` to the controller's reachable address. Give each machine a unique `CW_NODE_ID`, or leave it empty to use the hostname. If the controller has an API key, copy the same value into `CW_API_KEY` here.

Start the agent and follow its log:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now clusterwatch-agent
systemctl status clusterwatch-agent
journalctl -u clusterwatch-agent -f
```

On a Jetson, keep `CW_ENABLE_JETSON_TELEMETRY=true`. The agent automatically uses accessible thermal sysfs entries and `tegrastats`; it continues with standard Linux telemetry if either source is unavailable. To run the controller and agent on the same Jetson, configure the agent with `CW_CONTROLLER_URL=http://127.0.0.1:8000` and enable both services.

## Upgrade

Pull the latest code, reinstall it into the existing virtual environment, and restart the installed services:

```bash
cd /opt/clusterwatch/src
sudo git pull --ff-only
sudo /opt/clusterwatch/venv/bin/pip install --upgrade /opt/clusterwatch/src
sudo systemctl restart clusterwatch-controller clusterwatch-agent
```

Restart only the service installed on that machine. Database files and environment configuration remain outside the source checkout and are not replaced by an upgrade.

## Troubleshooting

Inspect recent logs and the resolved unit configuration:

```bash
journalctl -u clusterwatch-controller -n 100 --no-pager
journalctl -u clusterwatch-agent -n 100 --no-pager
systemctl cat clusterwatch-controller
systemctl cat clusterwatch-agent
```

After changing an environment file, restart its service. After replacing a unit file, run `sudo systemctl daemon-reload` before restarting.
