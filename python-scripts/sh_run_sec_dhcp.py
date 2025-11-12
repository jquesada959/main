#!/usr/bin/env python3
"""
Run a show command on each host and save output to files.

Defaults to: sh run | sec dhcp
Saves outputs to ./outputs/<host>_<timestamp>.txt

Usage: python3 sh_run_sec_dhcp.py [--command "sh run | sec dhcp"] [--outdir outputs] [--debug]
"""

import argparse
import sys
import time
from pathlib import Path
from cryptography.fernet import Fernet
import paramiko


def load_creds(base: Path):
    enc = base / 'credentials.txt.enc'
    keyf = base / 'secret.key'
    if not enc.exists() or not keyf.exists():
        print('Missing credentials or key')
        sys.exit(2)
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
        sys.exit(2)
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


def run_command_on_host(host_ip, host_name, user, pwd, command, outdir: Path, debug=False):
    print(f"Connecting to {host_name} ({host_ip})...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=host_ip, username=user, password=pwd, look_for_keys=False, allow_agent=False, timeout=10)
        shell = client.invoke_shell()
        shell.settimeout(2)
        time.sleep(1)
        try:
            shell.recv(65535)
        except Exception:
            pass
        shell.send(command + '\n')
        time.sleep(0.5)
        out = ''
        prompt_patterns = ['>', '#']
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
        ts = time.strftime('%Y%m%d_%H%M%S')
        outdir.mkdir(parents=True, exist_ok=True)
        fname = outdir / f"{host_name}_{ts}.txt"
        fname.write_text(out)
        if debug:
            print(f"Wrote {fname}")
        return True
    except Exception as e:
        print(f"Failed {host_name}: {e}")
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--command', default='sh run | sec dhcp')
    parser.add_argument('--outdir', default='outputs')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    base = Path(__file__).parent
    creds = load_creds(base)
    if 'device_user' not in creds or 'device_pass' not in creds:
        print('Missing device_user/device_pass in credentials')
        sys.exit(2)
    hosts = read_hosts(base)
    outdir = base / args.outdir
    success = 0
    for ip, name in hosts:
        ok = run_command_on_host(ip, name, creds['device_user'], creds['device_pass'], args.command, outdir, debug=args.debug)
        if ok:
            success += 1
    print(f"Completed {success}/{len(hosts)} hosts")


if __name__ == '__main__':
    main()
