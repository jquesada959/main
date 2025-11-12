#!/usr/bin/python3
import paramiko
import sys
from pathlib import Path
from cryptography.fernet import Fernet
import time

# ==== Load and decrypt credentials from credentials.txt.enc ====
enc_path = Path(__file__).parent / "credentials.txt.enc"
key_path = Path(__file__).parent / "secret.key"
if not enc_path.is_file():
    print(f"Error: credentials.txt.enc not found in {enc_path.parent}")
    sys.exit(1)
if not key_path.is_file():
    print(f"Error: secret.key not found in {key_path.parent}")
    sys.exit(1)

with open(key_path, "rb") as kf:
    key = kf.read()
fernet = Fernet(key)
with open(enc_path, "rb") as ef:
    decrypted = fernet.decrypt(ef.read()).decode("utf-8")

creds = {}
for line in decrypted.splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    if "=" in line:
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip()

required_keys = ["device_user", "device_pass"]
for key in required_keys:
    if key not in creds:
        print(f"Error: Missing '{key}' in credentials.txt")
        sys.exit(1)

device_user = creds["device_user"]
device_pass = creds["device_pass"]

# ==== hosts-dhcp.txt file in same folder as script ====
hosts_path = Path(__file__).parent / "hosts.txt"
if not hosts_path.is_file():
    print(f"Error: hosts-dhcp.txt not found in {hosts_path.parent}")
    sys.exit(1)

# Read IPs from file (strip whitespace, skip empty lines)
with open(hosts_path) as f:
    hosts = [line.strip() for line in f if line.strip()]

for host in hosts:
    print(f"\nConnecting to {host}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            username=device_user,
            password=device_pass,
            look_for_keys=False,
            allow_agent=False,
            timeout=10
        )
        shell = client.invoke_shell()
        shell.settimeout(2)
        time.sleep(1)
        shell.recv(65535)
        shell.send('cli\n')
        time.sleep(1)
        shell.recv(65535)
        shell.send('clear ip dhcp binding vrf GUEST *\n')
        time.sleep(2)
        output = ''
        max_loops = 10
        for _ in range(max_loops):
            time.sleep(0.5)
            try:
                chunk = shell.recv(65535).decode('utf-8')
            except Exception:
                break
            output += chunk
            if '>' in chunk or '#' in chunk:
                break
        print(f"Output from {host}:\n{output}")
    except Exception as e:
        print(f"Failed to connect to {host}: {e}")
    finally:
        client.close()
