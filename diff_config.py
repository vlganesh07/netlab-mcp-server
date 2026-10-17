from dotenv import load_dotenv
import json, glob, yaml
import os
import smtplib
from email.mime.text import MIMEText

# Cisco creates these automatically on every switch, they're not something
# anyone configured and not something golden_config.yaml should ever need
# to list. Excluded so they never show up as "unexpected VLANs".
RESERVED_VLAN_IDS = {1002, 1003, 1004, 1005}


def load_latest_dump():
    files = sorted(glob.glob('state_dump_*.json'))
    latest = files[-1]
    with open (latest) as f:
        return json.load(f)


def check_vlans(expected_vlans, live_vlans):
    live_ids = {int(vlan["vlan_id"]) for vlan in live_vlans}
    return [vlan_id for vlan_id in expected_vlans if vlan_id not in live_ids]


def check_unexpected_vlans(expected_vlans, live_vlans):
    # The mirror image of check_vlans(): that one catches a VLAN that
    # SHOULD be there and isn't (e.g. someone deleted it by mistake).
    # This one catches a VLAN that showed up and ISN'T in golden_config,
    # e.g. a test VLAN that got pushed and never cleaned up.
    expected_ids = set(expected_vlans)
    live_ids = {int(vlan["vlan_id"]) for vlan in live_vlans}
    return sorted(live_ids - expected_ids - RESERVED_VLAN_IDS)


def check_portchannels(expected_portchannels, live_portchannels):
    issues = []
    for expected in expected_portchannels:
        live = None
        for entry in live_portchannels:
            if entry["bundle_name"] == expected["name"]:
                live = entry
                break
        if live is None:
            issues.append(f"{expected['name']} not found on device")
            continue
        if live["bundle_status"] != expected["status"]:
            issues.append(f"{expected['name']} status mismatch: expected {expected['status']}, got {live['bundle_status']}")
        if set(live["member_interface"]) != set(expected["members"]):
            issues.append(f"{expected['name']} member mismatch: expected {expected['members']}, got {live['member_interface']}")
    return issues

def load_golden_config():
    with open('golden_config.yaml') as f:
        return yaml.safe_load(f)

def check_svis(live_interfaces, excluded_svis):
    issues = []

    for interface in live_interfaces:
        if interface['interface'].startswith('Vlan'):
            if interface['interface'] in excluded_svis:
                continue
            if interface['status'] != 'up' or interface['proto'] != 'up':
                issues.append(
                    f"{interface['interface']} is not up: "
                    f"status={interface['status']}, proto={interface['proto']}"
                )
    return issues


def send_alert(issues):
    # Turn the list of issue strings into one multi-line body, each on its own line with a dash
    body = "\n".join(f"- {issue}" for issue in issues)

    # MIMEText builds a plain-text email object - body is the content, second arg 'plain' means plain text (not HTML)
    msg = MIMEText(body, 'plain')
    msg['Subject'] = f"Netlab: {len(issues)} anomaly(s) detected"
    msg['From'] = os.environ['ALERT_EMAIL']
    msg['To'] = os.environ['ALERT_EMAIL']  # sending it to yourself

    # Connect to Gmail's SMTP server on port 587 (the standard port for encrypted email submission)
    server = smtplib.SMTP('smtp.gmail.com', 587)

    # Upgrade the plain connection to an encrypted one - required by Gmail before you're allowed to log in
    server.starttls()

    # Log in using your Gmail address and the 16-character app password from .env
    server.login(os.environ['ALERT_EMAIL'], os.environ['ALERT_EMAIL_PASSWORD'])

    # send_message() takes the MIMEText object directly and handles the From/To/Subject headers for you
    server.send_message(msg)

    # Always close the connection when done
    server.quit()

    return issues


if __name__ == '__main__':
    load_dotenv()
    golden = load_golden_config()
    dump = load_latest_dump()
    all_issues = []

    for device_name, config in golden['devices'].items():
        live = dump[device_name]

        missing_vlans = check_vlans(config['expected_vlans'], live['vlans'])
        for vlan_id in missing_vlans:
            all_issues.append(f"{device_name}: VLAN {vlan_id} missing")

        unexpected_vlans = check_unexpected_vlans(config['expected_vlans'], live['vlans'])
        for vlan_id in unexpected_vlans:
            all_issues.append(f"{device_name}: VLAN {vlan_id} present but not in golden_config.yaml (unexpected)")

        all_issues += [f"{device_name}: {issue}" for issue in check_portchannels(config['expected_portchannels'], live['portchannels'])]
        all_issues += [f"{device_name}: {issue}" for issue in check_svis(live['interfaces'], config.get('excluded_svis', []))]

    if all_issues:
        print(f"Found {len(all_issues)} issue(s):")
        for issue in all_issues:
            print(f"  - {issue}")
        send_alert(all_issues)  # <-- new line: only fires when there are actual issues
    else:
        print("No anomalies found. All checks passed.")
