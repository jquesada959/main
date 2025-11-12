#!/usr/bin/python3
import re
import csv
import paramiko
import sys
from pathlib import Path
from cryptography.fernet import Fernet
from datetime import datetime
import argparse
import io


def main():
    # ==== Load and decrypt credentials ====
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
            k, value = line.split("=", 1)
            creds[k.strip()] = value.strip()
    required_keys = ["user", "password"]
    for k in required_keys:
        if k not in creds:
            print(f"Error: Missing '{k}' in credentials.txt")
            sys.exit(1)
    device_user = creds["user"]
    device_pass = creds["password"]

    # ==== hosts.txt file in same folder as script ====
    hosts_path = Path(__file__).parent / "hosts.txt"
    if not hosts_path.is_file():
        print(f"Error: hosts.txt not found in {hosts_path.parent}")
        sys.exit(1)
    # Read hosts file which may contain lines like: "hostname ip_address"
    hosts = []
    with open(hosts_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                hostname = parts[0]
                ip = parts[1]
            else:
                ip = parts[0]
                hostname = ip
            hosts.append((ip, hostname))

    # CLI args
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--debug', action='store_true', help='Write raw outputs and parse summaries to /tmp')
    args, _ = parser.parse_known_args()
    DEBUG_MODE = bool(getattr(args, 'debug', False))

    # ==== Regex pattern for interface description ====
    int_pattern = re.compile(
        r"^(?P<interface>\S+)\s+"
        r"(?P<admin_status>\S+)\s+"
        r"(?P<oper_status>\S+)"
        r"(?:\s+(?P<description>.*))?$"
    )

    all_data = []

    for host_ip, host_name in hosts:
        print(f"\nConnecting to {host_name} ({host_ip})...")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=host_ip,
                username=device_user,
                password=device_pass,
                look_for_keys=False,
                allow_agent=False,
                timeout=10
            )
            shell = client.invoke_shell()
            shell.settimeout(2)
            import time
            time.sleep(1)
            try:
                banner = shell.recv(65535).decode('utf-8', errors='ignore')
            except Exception:
                banner = ''
            is_juniper = False
            is_cisco = False
            low = banner.lower()
            if 'junos' in low or 'juniper' in low:
                is_juniper = True
            elif 'ios' in low or 'cisco' in low or 'ios-xe' in low:
                is_cisco = True

            if is_cisco:
                shell.send('terminal length 0\n')
                shell.send('terminal width 511\n')
                time.sleep(0.5)
                try:
                    shell.recv(65535)
                except Exception:
                    pass
            if is_juniper:
                shell.send('cli\n')
                time.sleep(0.5)
                try:
                    shell.recv(65535)
                except Exception:
                    pass

            shell.send('show interfaces description\n')
            time.sleep(1)
            int_output = ''
            prompt_found = False
            max_loops = 20
            prompt_patterns = ['>', '#']
            for _ in range(max_loops):
                time.sleep(0.5)
                try:
                    chunk = shell.recv(65535).decode('utf-8')
                except Exception:
                    break
                int_output += chunk
                if '--More--' in chunk:
                    shell.send(' ')
                if any(chunk.strip().endswith(p) for p in prompt_patterns):
                    prompt_found = True
                    break
            if not prompt_found:
                print(f"Warning: Prompt not detected for {host_name} (interfaces). Output may be incomplete.")

            lines = int_output.splitlines()
            for line in lines:
                l = line.strip()
                lowl = l.lower()
                if not l or lowl.startswith('interface') or '--more--' in lowl or lowl.startswith('%') or lowl.startswith('show '):
                    continue
                cm = int_pattern.match(l)
                if cm:
                    data = cm.groupdict()
                    if data['description'] is None:
                        data['description'] = ''
                    entry = {
                        "host": host_name,
                        "interface": data['interface'],
                        "admin_status": data['admin_status'],
                        "oper_status": data['oper_status'],
                        "description": data['description']
                    }
                    all_data.append(entry)
        except Exception as e:
            print(f"Failed to connect to {host_name}: {e}")
        finally:
            client.close()

    # ==== Write data to CSV with timestamp ====
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"interfaces_description_{timestamp}.csv"
    with open(csv_filename, mode="w", newline="") as csvfile:
        fieldnames = ["host", "interface", "admin_status", "oper_status", "description"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_data:
            writer.writerow(row)

    print(f"\nData saved to {csv_filename}")

if __name__ == "__main__":
    main()
