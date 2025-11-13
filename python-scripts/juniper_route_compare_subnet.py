import paramiko
import csv
from cryptography.fernet import Fernet
import ipaddress

# Router details
ROUTER_IP = "172.25.123.1"      # Replace with your router IP
OUTPUT_FILE = "routes1.csv"
CREDS_FILE = "credentials.txt.enc"
KEY_FILE = "secret.key"
AD_ROUTES_FILE = "AD_routes.csv"
COMPARISON_FILE = "route_comparison_subnet.csv"

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
        print(f"Logging in to router {ROUTER_IP}...")
        ssh.connect(ROUTER_IP, username=username, password=password)
        print(f"Successfully logged in to router {ROUTER_IP}.")
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
        print(f"Logging off from router {ROUTER_IP}.")
        ssh.close()

def write_to_csv(routes, filename):
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Route"])
        for route in routes:
            writer.writerow([route])

def compare_routes_subnet(routes_file, ad_routes_file, output_file):
    # Read routes from routes_file
    with open(routes_file, newline='') as f:
        reader = csv.DictReader(f)
        router_routes = [row['Route'].strip() for row in reader if row['Route'].strip()]
    router_networks = []
    for r in router_routes:
        try:
            net = ipaddress.ip_network(r, strict=False)
            router_networks.append(net)
        except ValueError:
            # Ignore non-IPv4/IPv6 routes (e.g., ISIS, MPLS, etc.)
            continue
    # Read AD_routes.csv and compare
    # Build AD routes list
    ad_routes = []
    ad_sites = {}
    with open(ad_routes_file, newline='') as f:
        reader = csv.reader(f, delimiter='\t')
        header = next(reader)
        for row in reader:
            site = row[0].strip()
            subnets = [s.strip() for s in row[1:] if s.strip()]
            for subnet in subnets:
                try:
                    ad_net = ipaddress.ip_network(subnet, strict=False)
                    ad_routes.append(ad_net)
                    ad_sites[str(ad_net)] = site
                except Exception:
                    continue
    # Analyze router routes
    results = []
    for router_net in router_networks:
        found_exact = False
        found_subnet = None
        parent_site = None
        for ad_net in ad_routes:
            if router_net == ad_net:
                found_exact = True
                parent_site = ad_sites[str(ad_net)]
                break
            elif router_net.subnet_of(ad_net):
                found_subnet = ad_net
                parent_site = ad_sites[str(ad_net)]
        if found_exact:
            results.append((parent_site, str(router_net), 'Perfect match'))
        elif found_subnet:
            results.append((parent_site, str(router_net), f"Subnet of {found_subnet}"))
        else:
            results.append(('', str(router_net), 'No match or subnet'))
    # Write matches to output_file
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['SiteName', 'Router_Route', 'Result'])
        for site, route, note in results:
            if note != 'No match or subnet':
                writer.writerow([site, route, note])
    print(f"Comparison complete. Only matches and subnets saved to {output_file}.")

if __name__ == "__main__":
    routes = get_routes()
    if routes:
        write_to_csv(routes, OUTPUT_FILE)
        compare_routes_subnet(OUTPUT_FILE, AD_ROUTES_FILE, COMPARISON_FILE)
    else:
        print("No routes found or error occurred.")
