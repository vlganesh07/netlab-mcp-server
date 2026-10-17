import json, datetime, os
from dotenv import load_dotenv
from netmiko import ConnectHandler

DEVICES = [
    {'name': 'CSW1', 'host': '10.0.0.2', 'device_type': 'cisco_ios'},
    {'name': 'CSW2', 'host': '10.0.0.3', 'device_type': 'cisco_ios'}
]

def dump_device(dev, creds):
    conn = ConnectHandler(device_type=dev['device_type'], host=dev['host'], **creds)
    data = {'interfaces': conn.send_command('show ip interface brief', use_textfsm=True),
            'vlans': conn.send_command('show vlan brief', use_textfsm=True),
            'portchannels': conn.send_command('show etherchannel summary', use_textfsm=True),
            'version': conn.send_command('show version', use_textfsm=True)}
    conn.disconnect()
    return data

if __name__ == '__main__':
    load_dotenv()
    creds = {
        'username': os.environ['NETLAB_USERNAME'],
        'password': os.environ['NETLAB_PASSWORD'],
    }
    result = {dev['name']: dump_device(dev, creds) for dev in DEVICES}
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    with open(f'state_dump_{ts}.json', 'w') as f:
        json.dump(result, f, indent=2)

    print(f'Dump complete. Output written to state_dump_{ts}.json')