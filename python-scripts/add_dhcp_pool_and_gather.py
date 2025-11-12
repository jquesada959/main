#!/usr/bin/env python3
"""
add_dhcp_pool_and_gather.py

Connect to Cisco IOS-XE devices listed in hosts.txt (hostname ip or ip),
enter configuration mode and apply:

ip dhcp pool GUEST
 vrf GUEST
 lease 0 4

Then run: show running-config | section ip dhcp pool GUEST
Collect per-host outputs and append into a combined file in the script folder.

Options: --dry-run, --debug, --out combined filename
"""

import argparse
import time
from pathlib import Path
from cryptography.fernet import Fernet
import paramiko


def load_creds(base: Path):
    enc = base / 'credentials.txt.enc'
    keyf = base / 'secret.key'
    if not enc.exists() or not keyf.exists():
        print('Missing credentials or key')
        raise SystemExit(2)
    key = keyf.read_bytes()
    f = Fernet(key)
    data = f.decrypt(enc.read_bytes()).decode('utf-8')
    creds = {}
    for l in data.splitlines():
        l=l.strip()
        if not l or l.startswith('#'):
            continue
        if '=' in l:
            k,v = l.split('=',1)
            creds[k.strip()] = v.strip()
    return creds


def read_hosts(base: Path):
    hfile = base / 'hosts.txt'
    if not hfile.exists():
        print('hosts.txt missing')
        raise SystemExit(2)
    hosts = []
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


def run_on_host(ip, name, user, pwd, dry_run=False, debug=False):
    print(f"Connecting to {name} ({ip})...")
    if dry_run:
        print("Dry-run: would configure DHCP pool on this device")
        return (True, '')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=ip, username=user, password=pwd, look_for_keys=False, allow_agent=False, timeout=10)
        shell = client.invoke_shell()
        shell.settimeout(2)
        time.sleep(1)
        try:
            shell.recv(65535)
        except Exception:
            pass
        # Enter enable/config mode. Assumes user has priv. If enable password needed, you'd send 'enable' and the pw.
        shell.send('configure terminal\n')
        time.sleep(0.5)
        shell.send('ip dhcp pool GUEST\n')
        time.sleep(0.2)
        shell.send(' vrf GUEST\n')
        time.sleep(0.2)
        shell.send(' lease 0 4\n')
        time.sleep(0.2)
        shell.send('end\n')
        time.sleep(0.5)
        # Run show
        shell.send('terminal length 0\n')
        time.sleep(0.2)
        shell.send('show running-config | section ip dhcp pool GUEST\n')
        out = ''
        prompt_patterns = ['#', '>']
        for _ in range(120):
            time.sleep(0.5)
            try:
                chunk = shell.recv(65535).decode('utf-8', errors='ignore')
            except Exception:
                break
            out += chunk
            if '--More--' in chunk:
                shell.send(' ')
            if any(chunk.strip().endswith(p) for p in prompt_patterns):
                break
        return (True, out)
    except Exception as e:
        print(f"Failed {name}: {e}")
        return (False, str(e))
    finally:
        try:
            client.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--out', default='combined_dhcp_pool_GUEST.txt')
    args = parser.parse_args()

    base = Path(__file__).parent
    creds = load_creds(base)
    if 'device_user' not in creds or 'device_pass' not in creds:
        print('Missing device_user/device_pass')
        raise SystemExit(2)
    hosts = read_hosts(base)
    combined = base / args.out
    combined.write_text('')
    successes = 0
    for ip, name in hosts:
        ok, out = run_on_host(ip, name, creds['device_user'], creds['device_pass'], dry_run=args.dry_run, debug=args.debug)
        header = f"--- {name} ({ip}) ---\n"
        if ok:
            combined.write_text(combined.read_text() + header + out + "\n\n")
            successes += 1
        else:
            combined.write_text(combined.read_text() + header + "ERROR: " + out + "\n\n")

    print(f"Completed {successes}/{len(hosts)}")


if __name__ == '__main__':
    main()
