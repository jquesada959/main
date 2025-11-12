#!/usr/bin/env python3
"""
banner.py

Usage: python3 banner.py [--banner banner.txt] [--dry-run] [--debug]

Reads credentials from credentials.txt.enc (uses secret.key), reads hosts.txt (hostname ip),
reads a banner file (default: banner.txt in the same folder), and updates Juniper devices by
loading configuration via 'load merge terminal' with a 'system {
  login {
    message "...";
  }
}' block. Commits the change.

This script connects via paramiko invoke_shell and sends the commands interactively.
"""

import argparse
import sys
import time
from pathlib import Path
from cryptography.fernet import Fernet
import paramiko


def load_credentials(base_path: Path):
    enc = base_path / "credentials.txt.enc"
    keyf = base_path / "secret.key"
    if not enc.exists() or not keyf.exists():
        print(f"Missing {enc} or {keyf}")
        sys.exit(2)
    key = keyf.read_bytes()
    f = Fernet(key)
    data = f.decrypt(enc.read_bytes()).decode('utf-8')
    creds = {}
    for line in data.splitlines():
        line=line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k,v = line.split('=',1)
            creds[k.strip()] = v.strip()
    return creds


def read_hosts(base_path: Path):
    hosts = []
    hfile = base_path / 'hosts.txt'
    if not hfile.exists():
        print(f"hosts.txt not found in {base_path}")
        sys.exit(2)
    for l in hfile.read_text().splitlines():
        l=l.strip()
        if not l or l.startswith('#'):
            continue
        parts = l.split()
        if len(parts) >= 2:
            hosts.append((parts[1], parts[0]))
        else:
            hosts.append((parts[0], parts[0]))
    return hosts


def build_junos_config_block(banner_text: str) -> str:
    # We'll create a 'system login message' block using 'load merge terminal' with the
    # following snippet:
    # system {
    #   login {
    #     message "line1\nline2";
    #   }
    # }
    # Need to escape double quotes and backslashes in banner_text
    esc = banner_text.replace('\\', '\\\\').replace('"', '\\"')
    # Represent newlines as \n inside the quoted string
    esc = esc.replace('\n', '\\n')
    snippet = 'system {\n  login {\n    message "' + esc + '";\n  }\n}\n'
    return snippet


def run_on_host(host_ip, host_name, user, pwd, config_block, dry_run=False, debug=False):
    print(f"Connecting to {host_name} ({host_ip})...")
    if dry_run:
        print("Dry-run mode: would load the following configuration:\n")
        print(config_block)
        return True
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=host_ip, username=user, password=pwd, look_for_keys=False, allow_agent=False, timeout=10)
        shell = client.invoke_shell()
        shell.settimeout(2)
        time.sleep(1)
        # Drain banner
        try:
            shell.recv(65535)
        except Exception:
            pass
        # Enter configuration mode via 'configure' and then 'load merge terminal'
        shell.send('configure\n')
        time.sleep(0.5)
        shell.send('load merge terminal\n')
        time.sleep(0.5)
        # Send the config block, terminated by a blank line and a single '.' on a line (JunOS expects EOF via Ctrl-D usually)
        # We'll send the block followed by ctrl+d (ASCII 4)
        shell.send(config_block + '\n')
        time.sleep(0.2)
        shell.send('\x04')
        time.sleep(1)
        # Commit
        shell.send('commit and-quit\n')
        # Wait for commit to finish
        out = ''
        for _ in range(40):
            try:
                chunk = shell.recv(65535).decode('utf-8', errors='ignore')
            except Exception:
                break
            out += chunk
            if 'commit complete' in chunk.lower() or 'error:' in chunk.lower() or 'configuration check' in chunk.lower():
                break
            time.sleep(0.5)
        if debug:
            with open(f"/tmp/{host_name}_banner_debug.txt", 'w') as f:
                f.write(out)
        if 'commit complete' in out.lower():
            print(f"{host_name}: commit complete")
            return True
        else:
            print(f"{host_name}: commit may have failed, check /tmp/{host_name}_banner_debug.txt")
            return False
    except Exception as e:
        print(f"Failed to connect/update {host_name}: {e}")
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--banner', help='Banner file to use', default='banner.txt')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    base = Path(__file__).parent
    creds = load_credentials(base)
    required = ['device_user', 'device_pass']
    for r in required:
        if r not in creds:
            print(f"Missing {r} in credentials")
            sys.exit(2)
    user = creds['device_user']
    pwd = creds['device_pass']

    hosts = read_hosts(base)
    banner_file = base / args.banner
    if not banner_file.exists():
        print(f"Banner file {banner_file} not found")
        sys.exit(2)
    banner_text = banner_file.read_text()
    config_block = build_junos_config_block(banner_text)

    successes = 0
    for ip, name in hosts:
        ok = run_on_host(ip, name, user, pwd, config_block, dry_run=args.dry_run, debug=args.debug)
        if ok:
            successes += 1

    print(f"Completed: {successes}/{len(hosts)} updated successfully")


if __name__ == '__main__':
    main()
