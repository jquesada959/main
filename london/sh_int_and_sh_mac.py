#!/usr/bin/python3
import re
import csv
import paramiko
import sys
from pathlib import Path
from cryptography.fernet import Fernet
from datetime import datetime
import io
import argparse
try:
    import textfsm
    HAVE_TEXTFSM = True
except Exception:
    HAVE_TEXTFSM = False

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

# Read hosts file which may contain lines like: "hostname ip_address"
# We'll store a list of tuples (ip, hostname). If only an IP is provided, hostname==ip.
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

# ==== Regex patterns ====
int_pattern = re.compile(
    r"^(?P<interface>\S+)\s+"
    r"(?P<admin_status>\S+)\s+"
    r"(?P<oper_status>\S+)"
    r"(?:\s+(?P<description>.*))?$"
)
mac_pattern = re.compile(
    r"^(?P<vlan>\S+)\s+(?P<mac>[0-9a-fA-F:.\-]+)\s+\S+\s+(?P<port>\S+)"
)
# Cisco IOS-XE 'show interfaces description' commonly has: Interface  Status  Protocol  Description
cisco_int_pattern = re.compile(
    r"^(?P<interface>\S+)\s+"
    r"(?P<admin_status>\S+)\s+"
    r"(?P<oper_status>\S+)\s*"
    r"(?P<description>.*)$"
)

# ==== Collect all parsed data ====
all_data = []

# CLI args
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--debug', action='store_true', help='Write raw outputs and parse summaries to /tmp')
args, _ = parser.parse_known_args()
DEBUG_MODE = bool(getattr(args, 'debug', False))

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
        # Wait for initial prompt/banner and detect device type
        time.sleep(1)
        banner = ''
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

        # For Cisco IOS-XE, disable paging
        if is_cisco:
            shell.send('terminal length 0\n')
            shell.send('terminal width 511\n')
            time.sleep(0.5)
            try:
                shell.recv(65535)
            except Exception:
                pass

        # For Juniper, enter cli
        if is_juniper:
            shell.send('cli\n')
            time.sleep(0.5)
            try:
                shell.recv(65535)
            except Exception:
                pass

        # Get interface descriptions
        # Cisco: 'show interfaces description' ; Juniper: 'show interfaces descriptions'
        if is_cisco:
            sent_cmd = 'show interfaces description'
            shell.send(sent_cmd + '\n')
        else:
            sent_cmd = 'show interfaces description'
            shell.send(sent_cmd + '\n')
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
        # Parse interface descriptions
        interfaces = {}
        lines = int_output.splitlines()
        # If Cisco, try to find header line to compute column positions
        if is_cisco:
            # If textfsm is available, prefer structured parsing
            if HAVE_TEXTFSM:
                tpl = r"""
Value INTERFACE (\S+)
Value STATUS (.+?)
Value PROTOCOL (.+?)
Value DESCRIPTION (.*)

Start
  ^\s*Interface\s+Status\s+Protocol\s+Description -> Start
  ^\s*${INTERFACE}\s+${STATUS}\s+${PROTOCOL}\s+${DESCRIPTION} -> Record
"""
                try:
                    fsm = textfsm.TextFSM(io.StringIO(tpl))
                    parsed = fsm.ParseText(int_output)
                    for row in parsed:
                        vals = dict(zip(fsm.header, row))
                        iface = vals.get('INTERFACE')
                        interfaces[iface] = {"admin_status": vals.get('STATUS',''),
                                             "oper_status": vals.get('PROTOCOL',''),
                                             "description": (vals.get('DESCRIPTION') or '').strip()}
                    # if we parsed anything, skip further parsing
                    if interfaces:
                        # parsed via textfsm
                        pass
                except Exception:
                    # fallback to positional parsing below
                    pass

            header_idx = None
            for i, l in enumerate(lines):
                if l and 'interface' in l.lower() and 'status' in l.lower() and 'protocol' in l.lower():
                    header_idx = i
                    header_line = l
                    break
            if header_idx is not None:
                # determine column starts
                iface_start = header_line.lower().find('interface')
                status_start = header_line.lower().find('status')
                proto_start = header_line.lower().find('protocol')
                desc_start = header_line.lower().find('description')
                # debug print of header positions when DEBUG env var set
                import os as _os
                if _os.getenv('DEBUG_INT_PARSE'):
                    print(f"Header line: {repr(header_line)}")
                    print(f"Cols -> iface:{iface_start} status:{status_start} proto:{proto_start} desc:{desc_start}")
                if desc_start == -1:
                    # description may be at end; set to proto_start + 8
                    desc_start = proto_start + 8 if proto_start != -1 else None
                for l in lines[header_idx+1:]:
                    if not l:
                        continue
                    lowl = l.lower()
                    # skip paging, command echoes and error messages
                    if '--more--' in lowl or lowl.startswith('%') or lowl.strip().startswith(sent_cmd):
                        continue
                    # ensure line is long enough
                    try:
                        iface = l[iface_start:status_start].strip() if status_start != -1 else l.split()[0]
                        admin = l[status_start:proto_start].strip() if (status_start != -1 and proto_start != -1) else ''
                        oper = l[proto_start:desc_start].strip() if (proto_start != -1 and desc_start is not None) else ''
                        desc = l[desc_start:].strip() if desc_start is not None and desc_start < len(l) else ''
                    except Exception:
                        parts = re.split(r"\s+", l, maxsplit=3)
                        if len(parts) >= 3:
                            iface, admin, oper = parts[0].strip(), parts[1].strip(), parts[2].strip()
                            desc = parts[3].strip() if len(parts) > 3 else ''
                        else:
                            continue
                    if iface:
                        interfaces[iface] = {"admin_status": admin, "oper_status": oper, "description": desc}
            else:
                # no header found, fallback to regex/split per-line
                for line in lines:
                    l = line.strip()
                    lowl = l.lower()
                    # Filter out blank lines, header echoes, paging and command echo or error lines
                    if not l or lowl.startswith('interface') or '--more--' in lowl or lowl.startswith('%') or lowl.startswith('show '):
                        continue
                    cm = cisco_int_pattern.match(l)
                    if cm:
                        data = cm.groupdict()
                        interfaces[data['interface']] = {"admin_status": data.get('admin_status',''),
                                                         "oper_status": data.get('oper_status',''),
                                                         "description": (data.get('description') or '').strip()}
                        continue
                    parts = re.split(r"\s+", l, maxsplit=3)
                    if len(parts) >= 3:
                        iface, admin, oper = parts[0].strip(), parts[1].strip(), parts[2].strip()
                        desc = parts[3].strip() if len(parts) > 3 else ''
                        interfaces[iface] = {"admin_status": admin, "oper_status": oper, "description": desc}
        else:
            # Juniper or generic: try Juniper regex per line
            for line in lines:
                l = line.strip()
                if not l or l.lower().startswith('interface') or '--more--' in l.lower():
                    continue
                match = int_pattern.match(l)
                if match:
                    data = match.groupdict()
                    if data['description'] is None:
                        data['description'] = ''
                    interfaces[data['interface']] = {"admin_status": data['admin_status'],
                                                     "oper_status": data['oper_status'],
                                                     "description": data['description']}
    # Get MAC address table
        shell.send('show mac address-table\n')
        time.sleep(1)
        mac_output = ''
        prompt_found = False
        for _ in range(max_loops):
            time.sleep(0.5)
            try:
                chunk = shell.recv(65535).decode('utf-8')
            except Exception:
                break
            mac_output += chunk
            if '--More--' in chunk:
                shell.send(' ')
            if any(chunk.strip().endswith(p) for p in prompt_patterns):
                prompt_found = True
                break
        if not prompt_found:
            print(f"Warning: Prompt not detected for {host_name} (mac). Output may be incomplete.")
        # Write debug files if requested
        if DEBUG_MODE:
            safe = host_name.replace('/', '_')
            try:
                with open(f"/tmp/{safe}_int_raw.txt", 'w') as f:
                    f.write(int_output)
                with open(f"/tmp/{safe}_mac_raw.txt", 'w') as f:
                    f.write(mac_output)
                with open(f"/tmp/{safe}_parse_summary.txt", 'w') as f:
                    f.write(f"Detected: {'cisco' if is_cisco else ('juniper' if is_juniper else 'unknown')}\n")
                    f.write(f"Parsed interfaces: {len(interfaces)}\n")
                    # write sample parsed interfaces
                    for i, (k, v) in enumerate(interfaces.items()):
                        if i >= 20:
                            break
                        f.write(f"{k} -> {v}\n")
            except Exception as e:
                print(f"Failed to write debug files for {host_name}: {e}")
        # Parse MAC address table and match to interfaces
        for line in mac_output.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("vlan") or "--more--" in line.lower():
                continue
            match = mac_pattern.match(line)
            if match:
                mac_data = match.groupdict()
                port = mac_data["port"]
                if port.upper() == "CPU":
                    continue
                entry = {
                    "host": host_name,
                    "interface": port,
                    "admin_status": interfaces.get(port, {}).get("admin_status", ""),
                    "oper_status": interfaces.get(port, {}).get("oper_status", ""),
                    "description": interfaces.get(port, {}).get("description", ""),
                    "mac address": mac_data["mac"],
                    "vlan": mac_data["vlan"]
                }
                all_data.append(entry)
    except Exception as e:
        print(f"Failed to connect to {host_name}: {e}")
    finally:
        client.close()

# ==== Write data to CSV with timestamp ====
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
hour = datetime.now().hour
if hour in (0, 20):
    suffix = "_LON.BASE.csv"
elif hour in (5, 9, 10, 14):
    suffix = "_LON.DAYTIME.csv"
else:
    suffix = "_LON.csv"
csv_filename = f"interfaces_and_mac_{timestamp}{suffix}"
with open(csv_filename, mode="w", newline="") as csvfile:
    fieldnames = ["host", "interface", "admin_status", "oper_status", "description", "mac address", "vlan"]
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    for row in all_data:
        writer.writerow(row)

print(f"\nData saved to {csv_filename}")
