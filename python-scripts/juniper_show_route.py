
import paramiko
import csv
from cryptography.fernet import Fernet

# Router details
ROUTER_IP = "172.25.123.1"      # Replace with your router IP
OUTPUT_FILE = "routes1.csv"
CREDS_FILE = "credentials.txt.enc"
KEY_FILE = "secret.key"

def decrypt_credentials_file(enc_file_path, key_file_path):
    from pathlib import Path
    # Load key
    with open(key_file_path, "rb") as kf:
        key = kf.read()
    fernet = Fernet(key)
    # Decrypt credentials
    with open(enc_file_path, "rb") as ef:
        decrypted = fernet.decrypt(ef.read()).decode("utf-8")
    creds = {}
    for line in decrypted.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, value = line.split("=", 1)
            creds[k.strip()] = value.strip()
    required_keys = ["device_user", "device_pass"]
    for k in required_keys:
        if k not in creds:
            raise Exception(f"Missing '{k}' in credentials.txt.enc")
    return creds["device_user"], creds["device_pass"]

def get_routes():
    # Decrypt credentials
    username, password = decrypt_credentials_file(CREDS_FILE, KEY_FILE)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        # Connect to the router
        ssh.connect(ROUTER_IP, username=username, password=password)

        # Execute the command
        stdin, stdout, stderr = ssh.exec_command("show route all")
        output = stdout.read().decode()

        # Parse routes: Juniper routes usually start with an IP prefix
        routes = []
        for line in output.splitlines():
            line = line.strip()
            # Basic filter: lines starting with digits and containing '/'
            if line and line[0].isdigit() and '/' in line:
                route = line.split()[0]  # First column is the route
                routes.append(route)

        return routes

    except Exception as e:
        print(f"Error: {e}")
        return []
    finally:
        ssh.close()

def write_to_csv(routes):
    with open(OUTPUT_FILE, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Route"])  # Header
        for route in routes:
            writer.writerow([route])

if __name__ == "__main__":
    routes = get_routes()
    if routes:
        write_to_csv(routes)
        print(f"Routes saved to {OUTPUT_FILE}")
    else:
        print("No routes found or error occurred.")
