# Ansible deployment

The playbook deploys a controller, any number of agents, or both services on the same Jetson. It creates the service account and directories, checks out the requested revision, installs ClusterWatch in a virtual environment, configures the existing systemd units, and enables them at boot.

## Prepare the control machine

The target hosts need SSH access and Python 3. Install Ansible on the machine from which the playbook will run:

```bash
python3 -m venv .venv-ansible
source .venv-ansible/bin/activate
pip install "ansible-core>=2.16,<3"
cd deploy/ansible
cp inventory.example.yml inventory.yml
```

Edit `inventory.yml` with reachable hostnames or IP addresses and the SSH user. A machine may appear in both `controllers` and `agents`; the example uses this layout for a Jetson head node.

Set `clusterwatch_controller_url` to an address every agent can reach. The default inventory assumes SSH keys and an account with passwordless `sudo`. Add `--ask-become-pass` when sudo requires a password.

## Configure authentication

Leave `clusterwatch_api_key` empty for a trusted private network, or set one shared value for the controller and agents. Do not commit an inventory containing a real key. Ansible Vault can store it as an encrypted variable:

```bash
ansible-vault encrypt_string --name clusterwatch_api_key 'replace-with-a-long-random-value'
```

Place the generated variable under `all.vars` in `inventory.yml` and add `--ask-vault-pass` when running the playbook.

## Deploy

Check connectivity, preview changes, and then apply them:

```bash
ansible all -m ping
ansible-playbook site.yml --check --diff
ansible-playbook site.yml
```

The first check-mode run can report skipped tasks because the source checkout and virtual environment do not exist yet. Apply the playbook once, then check mode can evaluate the complete installed state.

Useful variables include:

| Variable | Default | Purpose |
|---|---|---|
| `clusterwatch_repository_version` | `main` | Branch, tag, or commit to deploy |
| `clusterwatch_controller_url` | `http://127.0.0.1:8000` | Controller address used by agents |
| `clusterwatch_api_key` | empty | Optional shared agent key |
| `clusterwatch_node_id` | inventory hostname | Stable agent identity |
| `clusterwatch_node_labels` | `role=physical` | Agent labels |
| `clusterwatch_enable_jetson_telemetry` | `true` | Enable best-effort Jetson probes |

Controller thresholds, sample timing, retry behavior, paths, and repository URL are also configurable in `roles/clusterwatch/defaults/main.yml`.

## Verify the deployment

```bash
ansible controllers -a "systemctl is-active clusterwatch-controller"
ansible agents -a "systemctl is-active clusterwatch-agent"
ansible controllers -a "curl -fsS http://127.0.0.1:8000/health"
```

Re-running the playbook is safe. Configuration or source changes restart only the affected services. Per-service revision markers ensure both processes restart after an upgrade when one machine, such as the Jetson head node, runs both roles.
