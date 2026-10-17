# netlab-mcp-server

An MCP server that lets an AI assistant query and (carefully) configure a real home network lab, two Cisco Catalyst 9300 core switches and a Palo Alto PA-440 firewall, instead of a simulated one.

This is a personal lab project, not production-hardened code. It was built to learn network automation and MCP server design on real hardware. If you're adapting this for your own network, read through `netlab_mcp_server.py` before pointing it at anything you care about, especially `push_vlan_config`, which is the one tool here that changes live device config.

## What's in here

- **`netlab_mcp_server.py`** — the MCP server. Exposes six tools to any MCP client (Claude Desktop, etc.):
  - `get_device_state(device_name)` — live interfaces, VLANs, port-channels, and version info for one switch
  - `get_all_device_states()` — the same, for every switch at once
  - `get_firewall_policy()` — current security rulebase from the PA-440
  - `get_firewall_interfaces()` — interface and zone state from the PA-440
  - `run_diff_check()` — compares live switch state against `golden_config.yaml` right now, no saved file needed
  - `push_vlan_config(device_name, vlan_id, vlan_name, confirm=False)` — creates or renames a VLAN. Defaults to a dry run; nothing changes on the device until the caller explicitly passes `confirm=True`. This is the only write-capable tool in the file.
- **`state_dump.py`** — pulls live state from the switches and writes it to a timestamped JSON file.
- **`diff_config.py`** — compares the latest state dump against `golden_config.yaml` and emails an alert (via Gmail SMTP) if anything's missing, mismatched, or unexpectedly present.
- **`golden_config.yaml`** — the expected state: VLANs, port-channel membership, and SVIs to ignore per device.
- **`pa_pull.py`** — pulls the PA-440's security rulebase to a local JSON file.
- **`inventory.yml`, `vlan_push.yml`, `vlan_delete.yml`** — Ansible inventory and playbooks for pushing/removing a test VLAN the same way `push_vlan_config` does it, just outside the MCP path.
- **`connect_test.py`** — a one-off Netmiko connectivity check.

## Setup

1. Clone the repo and create a virtualenv:

   ```
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your own values. Never commit `.env`, it's already in `.gitignore`.

3. Update the `DEVICES` dict in `netlab_mcp_server.py` (and `state_dump.py`) with your own switch hostnames/IPs, and `golden_config.yaml` with your own expected VLANs and port-channels.

4. Point an MCP client at the server. For Claude Desktop, add this to its MCP config:

   ```json
   {
     "mcpServers": {
       "netlab": {
         "command": "/absolute/path/to/venv/bin/python3",
         "args": ["/absolute/path/to/netlab_mcp_server.py"]
       }
     }
   }
   ```

5. Restart Claude Desktop and ask it something like "what's the state of CSW1" or "any config drift on my network right now."

## Why the write tool is guardrailed

`push_vlan_config` is the only tool here that can change a live device. Rather than let an AI client just go do that, it defaults to a dry run, it reports exactly what it would push and changes nothing. The caller (a person, through their MCP client) has to see that dry run and explicitly pass `confirm=True` to make it real. That's a stand-in for a proper human-approval gate, not a substitute for one, treat it as a reminder to build real guardrails before giving an AI write access to anything that matters.

