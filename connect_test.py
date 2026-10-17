import os
from dotenv import load_dotenv
from netmiko import ConnectHandler

load_dotenv()

device_dict = {
    'device_type': 'cisco_ios',
    'host': '10.0.0.2',
    'username': os.environ['NETLAB_USERNAME'],
    'password': os.environ['NETLAB_PASSWORD'],
}
conn = ConnectHandler(**device_dict)
print(conn.send_command('show version'))
conn.disconnect()
