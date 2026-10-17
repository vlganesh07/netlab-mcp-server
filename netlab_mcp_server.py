import os
import json
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from netmiko import ConnectHandler
from panos.firewall import Firewall
from panos.policies import Rulebase, SecurityRule
from panos.network import EthernetInterface, Zone

# Reusing your diff_config.py checks instead of copy-pasting them here.
# Importing it is safe: all of its real work happens under
# `if __name__ == '__main__':`, so importing just gives us its functions
# (load_golden_config, check_vlans, check_portchannels, check_svis)
# without it trying to load a state_dump file or send an email.
import diff_config as dc

# Load .env once, at import time, so credentials are ready no matter
# how this script gets started (directly, or launched by Claude Desktop)
load_dotenv()

# FastMCP() creates the actual server object. The string "netlab" is just
# a label, it shows up as this server's name when a client connects to it.
mcp = FastMCP("netlab")

# Same device list you already use in state_dump.py
DEVICES = {
    'CSW1': {'host': '10.0.0.2', 'device_type': 'cisco_ios'},
    'CSW2': {'host': '10.0.0.3', 'device_type': 'cisco_ios'},
}


def _netlab_creds():
    # Small helper since every switch tool needs the same two env vars.
    return {
        'username': os.environ['NETLAB_USERNAME'],
        'password': os.environ['NETLAB_PASSWORD'],
    }


def dump_device(dev, creds):
    # This is your existing function from state_dump.py, unchanged.
    # Kept as a plain helper function, NOT decorated, because it takes
    # a dict argument (dev), which isn't a clean tool interface.
    # The @mcp.tool() functions below call this instead of duplicating logic.
    conn = ConnectHandler(device_type=dev['device_type'], host=dev['host'], **creds)
    data = {
        'interfaces': conn.send_command('show ip interface brief', use_textfsm=True),
        'vlans': conn.send_command('show vlan brief', use_textfsm=True),
        'portchannels': conn.send_command('show etherchannel summary', use_textfsm=True),
        'version': conn.send_command('show version', use_textfsm=True),
    }
    conn.disconnect()
    return data


# @mcp.tool() is the decorator that turns this ordinary function into
# something an AI assistant can discover and call. FastMCP reads the
# function name, the docstring, and the type hints (device_name: str)
# to figure out what this tool does and what it expects as input.
@mcp.tool()
def get_device_state(device_name: str) -> dict:
    """Pull live interface, VLAN, and port-channel state from a lab switch.
    device_name must be 'CSW1' or 'CSW2'."""
    if device_name not in DEVICES:
        # Returning an error message instead of crashing, since an AI
        # client might pass a bad value, and this way it gets a clear
        # answer back instead of a stack trace.
        return {"error": f"Unknown device '{device_name}'. Valid options: {list(DEVICES.keys())}"}

    return dump_device(DEVICES[device_name], _netlab_creds())


@mcp.tool()
def get_all_device_states() -> dict:
    """Pull live state from every lab switch (CSW1 and CSW2) at once."""
    creds = _netlab_creds()
    return {name: dump_device(dev, creds) for name, dev in DEVICES.items()}


@mcp.tool()
def get_firewall_policy() -> list:
    """Pull the current security rulebase from the PA-440 firewall."""
    fw = Firewall(
        os.environ['PA_HOST'],
        api_username=os.environ['PA_USERNAME'],
        api_password=os.environ['PA_PASSWORD'],
    )
    rulebase = Rulebase()
    fw.add(rulebase)
    rules = SecurityRule.refreshall(rulebase)

    return [
        {
            "name": r.name,
            "source": r.source,
            "destination": r.destination,
            "action": r.action,
            "fromzone": r.fromzone,
            "tozone": r.tozone,
            "application": r.application,
        }
        for r in rules
    ]


@mcp.tool()
def get_firewall_interfaces() -> dict:
    """Pull interface and zone assignment state from the PA-440 firewall.
    Read-only, same pattern as get_firewall_policy but for interfaces/zones
    instead of the security rulebase."""
    fw = Firewall(
        os.environ['PA_HOST'],
        api_username=os.environ['PA_USERNAME'],
        api_password=os.environ['PA_PASSWORD'],
    )

    # EthernetInterface and Zone are panos "tree" objects, same idea as
    # Rulebase/SecurityRule above: add them under the firewall, then
    # refreshall() pulls the live list from the device.
    interfaces = EthernetInterface.refreshall(fw)
    zones = Zone.refreshall(fw)

    return {
        "interfaces": [
            {
                "name": i.name,
                "mode": i.mode,
                "ip": i.ip,
            }
            for i in interfaces
        ],
        "zones": [
            {
                "name": z.name,
                "interfaces": z.interface,
            }
            for z in zones
        ],
    }


@mcp.tool()
def run_diff_check() -> dict:
    """Compare LIVE switch state against golden_config.yaml right now.
    Same checks as diff_config.py (missing VLANs, port-channel mismatches,
    unexpected SVI down/up), but pulls fresh state instead of reading the
    last saved state_dump_*.json file, and does not send an email alert."""
    creds = _netlab_creds()
    golden = dc.load_golden_config()
    issues = []

    for device_name, config in golden['devices'].items():
        if device_name not in DEVICES:
            continue
        live = dump_device(DEVICES[device_name], creds)

        missing_vlans = dc.check_vlans(config['expected_vlans'], live['vlans'])
        for vlan_id in missing_vlans:
            issues.append(f"{device_name}: VLAN {vlan_id} missing")

        issues += [
            f"{device_name}: {issue}"
            for issue in dc.check_portchannels(config['expected_portchannels'], live['portchannels'])
        ]
        issues += [
            f"{device_name}: {issue}"
            for issue in dc.check_svis(live['interfaces'], config.get('excluded_svis', []))
        ]

    if not issues:
        return {"issue_count": 0, "issues": [], "status": "all checks passed"}
    return {"issue_count": len(issues), "issues": issues}


@mcp.tool()
def push_vlan_config(device_name: str, vlan_id: int, vlan_name: str, confirm: bool = False) -> dict:
    """Create or rename a VLAN on a lab switch. THIS IS A WRITE ACTION — it
    changes live device config, unlike every other tool in this file.

    Guardrail: without confirm=True this only reports what it WOULD do and
    changes nothing. An AI client has to be told confirm=True explicitly to
    actually push, which is a stand-in for the human-approval gate Phase 4
    is supposed to build properly — don't treat this as that gate.

    device_name must be 'CSW1' or 'CSW2'."""
    if device_name not in DEVICES:
        return {"error": f"Unknown device '{device_name}'. Valid options: {list(DEVICES.keys())}"}

    if not confirm:
        return {
            "status": "dry_run",
            "would_push": f"vlan {vlan_id} / name {vlan_name} on {device_name}",
            "note": "Nothing was changed. Call again with confirm=True to apply.",
        }

    dev = DEVICES[device_name]
    conn = ConnectHandler(device_type=dev['device_type'], host=dev['host'], **_netlab_creds())

    # send_config_set() pushes each string as a separate config-mode command,
    # the way you'd type them one by one in `conf t`.
    commands = [f"vlan {vlan_id}", f"name {vlan_name}"]
    output = conn.send_config_set(commands)
    conn.save_config()
    conn.disconnect()

    return {"status": "applied", "device": device_name, "commands": commands, "output": output}


# mcp.run() starts the server and keeps it listening for tool calls.
# This only happens when you run this file directly, same purpose as
# your other scripts' if __name__ == '__main__' blocks.
if __name__ == "__main__":
    mcp.run()
