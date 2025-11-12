import paramiko
import csv
import re
import logging
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from cryptography.fernet import Fernet
logging.basicConfig(filename='avocent_sn.log', level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# --- Replace with your actual decryption logic ---
def decrypt_credentials_file(enc_file_path, key):
    logging.info(f"Decrypting credentials file: {enc_file_path}")
    with open(enc_file_path, 'rb') as f:
        encrypted = f.read()
    fernet = Fernet(key)
    decrypted = fernet.decrypt(encrypted).decode()
    # Expecting CSV: username,password (all plaintext after decryption, one line only)
    lines = [l for l in decrypted.strip().split('\n') if l.strip()]
    if not lines:
        raise Exception('No credentials found in decrypted file')
    parts = lines[0].strip().split(',')
    if len(parts) == 2:
        user, pw = parts
        return user, pw
    else:
        raise Exception('Credentials file must contain username,password')

def get_hosts(hosts_file):
    logging.info(f"Reading hosts from: {hosts_file}")
    hosts = []
    with open(hosts_file, 'r') as f:
        for line in f:
            if line.strip():
                parts = line.strip().split()
                if len(parts) >= 2:
                    ip = parts[1]
                    # Remove subnet mask if present
                    ip = ip.split('/')[0]
                    hosts.append((parts[0], ip))  # (device_name, ip)
    return hosts

    # (removed duplicate, unindented get_serial_number definition)
def get_serial_number(host, username, password, dry_run=False):
    if dry_run:
        msg = f"[DRY-RUN] Would connect to {host} as {username} to retrieve serial number."
        print(msg)
        logging.info(msg)
        return 'DRY_RUN', 'yes'
    logging.info(f"Connecting to {host} via SSH to retrieve serial number.")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, username=username, password=password, look_for_keys=False)
    except Exception as e:
        logging.error(f"SSH connection failed for {host}: {e}")
        # If SSH fails, run ICMP ping
        import subprocess
        try:
            ping_cmd = ["ping", "-c", "2", "-W", "2", host]
            result = subprocess.run(ping_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode == 0:
                return '', 'no SSH and yes ICMP'
            else:
                return '', 'no SSH and no ICMP'
        except Exception as e2:
            logging.error(f"ICMP ping failed for {host}: {e2}")
            return '', 'no SSH and no ICMP'
    try:
        shell = ssh.invoke_shell()
        def read_until_prompt(prompt="cli->", timeout=10):
            shell.settimeout(1)
            output = ""
            start = time.time()
            while True:
                try:
                    resp = shell.recv(2000).decode(errors='ignore')
                    output += resp
                    print(f"[DEBUG] Output: {resp}")
                    logging.debug(f"Output: {resp}")
                    if prompt in resp:
                        break
                except Exception:
                    pass
                if time.time() - start > timeout:
                    print(f"[DEBUG] Timeout waiting for prompt '{prompt}'")
                    logging.warning(f"Timeout waiting for prompt '{prompt}'")
                    break
            return output

        # Wait for initial prompt
        print(f"[DEBUG] Waiting for initial prompt on {host}")
        read_until_prompt()

        print(f"[DEBUG] Sending 'cd system/information' to {host}")
        shell.send('cd system/information\n')
        out1 = read_until_prompt()
        print(f"[DEBUG] After cd system/information: {out1}")
        logging.debug(f"After cd system/information: {out1}")

        print(f"[DEBUG] Sending 'show' to {host}")
        shell.send('show\n')
        out2 = read_until_prompt()
        print(f"[DEBUG] After show: {out2}")
        logging.debug(f"After show: {out2}")

        # Try Avocent serial extraction first
        output = out1 + out2
        match = re.search(r'serial number: (\S+)', output)
        if match:
            logging.info(f"Serial number for {host}: {match.group(1)}")
            ssh.close()
            return match.group(1), 'yes'

        # If not found, try 'show system/information' as a second option
        print(f"[DEBUG] Trying 'show system/information' for {host}")
        shell.send('show system/information\n')
        out3 = read_until_prompt()
        print(f"[DEBUG] After show system/information: {out3}")
        logging.debug(f"After show system/information: {out3}")
        match2 = re.search(r'serial number: (\S+)', out3)
        if match2:
            logging.info(f"Serial number for {host} (show system/information): {match2.group(1)}")
            ssh.close()
            return match2.group(1), 'yes'

        # If still not found, try JunOS extraction
        print(f"[DEBUG] Trying JunOS serial extraction for {host}")
        shell.send('show chassis hardware\n')
        junos_output = ''
        start = time.time()
        while True:
            try:
                chunk = shell.recv(2000).decode(errors='ignore')
                junos_output += chunk
                if 'Hardware inventory:' in chunk or 'Chassis' in chunk:
                    pass
                if '>' in chunk or '#' in chunk or time.time() - start > 10:
                    break
            except Exception:
                break
        ssh.close()
        # Parse for Chassis line
        serial = ''
        for line in junos_output.splitlines():
            line = line.strip()
            # Match line starting with 'Chassis' and having a serial number column
            if line.startswith('Chassis'):
                # Example: Chassis                                NV3620210374      EX3400-24T
                match = re.match(r'^Chassis\s+(\S+)\s+(\S+)$', line)
                if match:
                    serial = match.group(1)
                    break
                # Fallback: split and get the second non-empty value
                parts = [p for p in line.split() if p]
                if len(parts) >= 3:
                    serial = parts[-2]
                    break
        if serial:
            logging.info(f"JunOS serial number for {host}: {serial}")
            return serial, 'yes'
        else:
            logging.warning(f"Serial number not found for {host}.")
            return '', 'yes'
    except Exception as e:
        logging.error(f"Error during SSH session for {host}: {e}")
        return '', 'yes'

def main():
    parser = argparse.ArgumentParser(description="Avocent SN Collector")
    parser.add_argument('--dry-run', action='store_true', help='Only print which SSH connections would be attempted, do not connect.')
    parser.add_argument('--credentials', default='credentials.txt.OOB.enc', help='Encrypted credentials file (default: credentials.txt.OOB.enc)')
    parser.add_argument('--hosts', default='Hosts-OOB.txt', help='Hosts file (default: Hosts-OOB.txt)')
    parser.add_argument('--key', default='secret.OOB.key', help='Fernet key file (default: secret.OOB.key)')
    parser.add_argument('--output', default='avocent_serials.csv', help='Output CSV file (default: avocent_serials.csv)')
    args = parser.parse_args()

    # Read Fernet key from file
    with open(args.key, 'rb') as kf:
        key = kf.read().strip()
        username, password = decrypt_credentials_file(args.credentials, key)
    hosts = get_hosts(args.hosts)
    results = []
    def process_device(device_name, ip):
        try:
            serial, alive = get_serial_number(ip, username, password, dry_run=args.dry_run)
        except Exception as e:
            serial, alive = f'ERROR: {e}', 'no SSH and no ICMP'
        return (device_name, ip, serial, alive)

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_device = {executor.submit(process_device, device_name, ip): (device_name, ip) for device_name, ip in hosts}
        for future in as_completed(future_to_device):
            device_name, ip, serial, alive = future.result()
            results.append((device_name, ip, serial, alive))

    with open(args.output, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['device_name', 'ip_address', 'serial_number', 'alive'])
        for row in results:
            writer.writerow(row)
    logging.info(f"Serial numbers saved to {args.output}")
    print(f"Serial numbers saved to {args.output}")

if __name__ == '__main__':
    main()
