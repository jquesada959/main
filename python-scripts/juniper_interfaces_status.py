#!/usr/bin/python3
# ...existing code...
import re
import csv
import paramiko
import sys
from pathlib import Path
from cryptography.fernet import Fernet
from datetime import datetime
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
        key, value = line.split("=", 1)
        creds[key.strip()] = value.strip()

required_keys = [
    "device_user", "device_pass"
]
for key in required_keys:
    if key not in creds:
        print(f"Error: Missing '{key}' in credentials.txt")
        sys.exit(1)

device_user = creds["device_user"]
device_pass = creds["device_pass"]

# ==== hosts.txt file in same folder as script ====
hosts_path = Path(__file__).parent / "hosts.txt"
if not hosts_path.is_file():
    print(f"Error: hosts.txt not found in {hosts_path.parent}")
    sys.exit(1)

# Read IPs from file (strip whitespace, skip empty lines)
with open(hosts_path) as f:
    hosts = [line.strip() for line in f if line.strip()]

# ==== Regex pattern (robust) ====
pattern = re.compile(
    r"^(?P<interface>\S+)\s+"
    r"(?P<admin_status>\S+)\s+"
    r"(?P<oper_status>\S+)"
    r"(?:\s+(?P<description>.*))?$"
)

# ==== Collect all parsed data ====
all_data = []

# ==== Loop over switches ====
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
        import time
        # Wait for initial prompt/banner
        time.sleep(1)
        shell.recv(65535)
        shell.send('cli\n')
        time.sleep(1)
        shell.recv(65535)  # Clear any output from cli command
        shell.send('show interfaces description\n')
        time.sleep(1)
        output = ''
        prompt_found = False
        max_loops = 20
        prompt_patterns = ['>', '#']  # Juniper prompt usually ends with '>' or '#'
        for _ in range(max_loops):
            time.sleep(0.5)
            try:
                chunk = shell.recv(65535).decode('utf-8')
            except Exception:
                break
            output += chunk
            # Handle paging (e.g., '--More--')
            if '--More--' in chunk:
                shell.send(' ')
            # Check for prompt at end of output
            if any(chunk.strip().endswith(p) for p in prompt_patterns):
                prompt_found = True
                break
        if not prompt_found:
            print(f"Warning: Prompt not detected for {host}. Output may be incomplete.")

        # Parse output
        for line in output.splitlines():
            line = line.strip()
            # Skip headers, empty lines, and paging prompts
            if not line or line.lower().startswith("interface") or "--more--" in line.lower():
                continue
            match = pattern.match(line)
            if match:
                data = match.groupdict()
                if data["description"] is None:
                    data["description"] = ""
                data["host"] = host
                all_data.append(data)
    except Exception as e:
        print(f"Failed to connect to {host}: {e}")
    finally:
        client.close()

# ==== Write data to CSV with timestamp ====
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
csv_filename = f"interfaces_descriptions_{timestamp}.csv"
with open(csv_filename, mode="w", newline="") as csvfile:
    fieldnames = ["host", "interface", "admin_status", "oper_status", "description"]
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    for row in all_data:
        writer.writerow(row)

print(f"\nData saved to {csv_filename}")