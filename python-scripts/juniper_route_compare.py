import paramiko
import csv
from cryptography.fernet import Fernet

# Router details
ROUTER_IP = "172.25.123.1"      # Replace with your router IP
OUTPUT_FILE = "routes_raw.csv"
CREDS_FILE = "credentials.txt.enc"
KEY_FILE = "secret.key"
AD_ROUTES_FILE = "AD_routes.csv"
COMPARISON_FILE = "route_comparison.csv"

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
    username, password = decrypt_credentials_file(CREDS_FILE, KEY_FILE)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(ROUTER_IP, username=username, password=password)
        stdin, stdout, stderr = ssh.exec_command("show route all")
        output = stdout.read().decode()
        routes = []
        for line in output.splitlines():
            line = line.strip()
            if line and line[0].isdigit() and '/' in line:
                route = line.split()[0]
                routes.append(route)
        return routes
    except Exception as e:
        print(f"Error: {e}")
        return []
    finally:
        ssh.close()

def write_to_csv(routes, filename):
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Route"])
        for route in routes:
            writer.writerow([route])

def compare_routes(routes_file, ad_routes_file, output_file):
    # Read routes from routes_file
    with open(routes_file, newline='') as f:
        reader = csv.DictReader(f)
        route_set = set(row['Route'].strip() for row in reader if row['Route'].strip())
    # Read AD_routes.csv and compare
    matches = []
    with open(ad_routes_file, newline='') as f:
        reader = csv.reader(f, delimiter='\t')
        header = next(reader)
        for row in reader:
            site = row[0].strip()
            subnets = [s.strip() for s in row[1:] if s.strip()]
            for subnet in subnets:
                if subnet in route_set:
                    matches.append((site, subnet))
    # Write matches to output_file
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['SiteName', 'MatchedRoute'])
        for site, route in matches:
            writer.writerow([site, route])
    print(f"Found {len(matches)} matching routes. Results saved to {output_file}.")

if __name__ == "__main__":
    routes = get_routes()
    if routes:
        write_to_csv(routes, OUTPUT_FILE)
        compare_routes(OUTPUT_FILE, AD_ROUTES_FILE, COMPARISON_FILE)
    else:
        print("No routes found or error occurred.")
