
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import pexpect
import csv
import time
import os
from cryptography.fernet import Fernet

def load_encrypted_creds():
    key_path = os.path.join(os.path.dirname(__file__), "secret.key")
    enc_path = os.path.join(os.path.dirname(__file__), "credentials.txt.enc")
    with open(key_path, "rb") as kf:
        key = kf.read()
    fernet = Fernet(key)
    with open(enc_path, "rb") as ef:
        decrypted = fernet.decrypt(ef.read()).decode("utf-8")
    creds = {}
    for line in decrypted.splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        if "=" in line:
            k, v = line.split("=", 1)
            creds[k.strip().lower()] = v.strip()
    # Accept both 'user'/'username' and 'password' keys
    username = creds.get("user") or creds.get("username")
    password = creds.get("password")
    if not username or not password:
        raise Exception("Missing username or password in decrypted credentials.")
    return username, password

def analyze_wlc(ip, username, password):
    result = {
        "ip": ip,
        "model": "",
        "serial_number": "",
        "ha_summary": "",
        "wireless_state": "",
        "mobility_summary": "",
        "mobility_anchor": "",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "error": ""
    }

    try:
        logging.info(f"Connecting to {ip} ...")
        ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {username}@{ip}"
        child = pexpect.spawn(ssh_cmd, encoding='utf-8', timeout=20)
        logfile = open('wlc_ha_verification-1.log', 'a')
        child.logfile = logfile

        # Expect password prompt and send password (do not log password)
        idx = child.expect(["[Pp]assword:", pexpect.EOF, pexpect.TIMEOUT], timeout=20)
        if idx == 0:
            logging.info("'Password:' prompt received, sending password (not logged).")
            child.logfile = None  # Temporarily disable logging to avoid logging password
            child.sendline(password)
            child.logfile = logfile  # Re-enable logging
        else:
            raise Exception("Did not receive 'Password:' prompt.")

        idx = child.expect([">", "#", pexpect.EOF, pexpect.TIMEOUT], timeout=20)
        if idx in [0, 1]:
            logging.info("Shell prompt received after login.")
        else:
            raise Exception("Did not receive shell prompt after login.")

        # Set terminal length to 0 to avoid paginated output
        child.sendline("ter len 0")
        child.expect([">", "#"], timeout=10)

        def run_command(cmd):
            child.sendline(cmd)
            child.expect([">", "#"], timeout=20)
            output = child.before
            logging.info(f"Command '{cmd}' output: {output}")
            return output

        version_output = run_command("show version")
        # Extract model from 'Model Number' line
        import re
        model_match = re.search(r"Model Number\s*:\s*(\S+)", version_output)
        if model_match:
            result["model"] = model_match.group(1)
        else:
            result["model"] = "Unknown"
        # Extract serial number from 'System Serial Number' line
        serial_match = re.search(r"System Serial Number\s*:\s*(\S+)", version_output)
        if serial_match:
            result["serial_number"] = serial_match.group(1)
        else:
            result["serial_number"] = "Unknown"

        result["ha_summary"] = run_command("show redundancy").strip()
        result["wireless_state"] = run_command("show wireless summary").strip()
        result["mobility_summary"] = run_command("sh wireless  mobility controller ap").strip()
        result["mobility_anchor"] = run_command("sh wireless  mobility controller client summary").strip()

        child.sendline("exit")
        child.close()
        logfile.close()
    except Exception as e:
        print(f"Error: {e}")
        logging.error(f"Error: {e}")
        result["error"] = str(e)
    return result

def main():
    # Read hosts from Hosts-WLCs.txt
    hosts = []
    try:
        with open("Hosts-WLCs-3800.txt", "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 2:
                    hosts.append(parts[1])
    except Exception as e:
        print(f"Could not read Hosts-WLCs.txt: {e}")
        return

    if not hosts:
        print("No hosts found in Hosts-WLCs.txt.")
        return

    print("Running analysis for all WLC IPs (up to 4 in parallel):")
    try:
        username, password = load_encrypted_creds()
    except Exception as e:
        print(f"Failed to load encrypted credentials: {e}")
        return
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_ip = {executor.submit(analyze_wlc, ip, username, password): ip for ip in hosts}
        for idx, future in enumerate(as_completed(future_to_ip), 1):
            ip = future_to_ip[future]
            try:
                result = future.result()
            except Exception as exc:
                print(f"{idx}: {ip} generated an exception: {exc}")
                result = {"ip": ip, "error": str(exc)}
            print(f"{idx}: {ip}")
            results.append(result)

    # Save all results to a single CSV file (overwrite each run)
    csv_fields = ["ip", "model", "serial_number", "ha_summary", "wireless_state", "mobility_summary", "mobility_anchor", "timestamp", "error"]
    with open("wlc_ha_results.csv", "w", newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_fields)
        writer.writeheader()
        for row in results:
            for field in csv_fields:
                if field not in row:
                    row[field] = ""
            writer.writerow(row)
    print("Analysis complete. Results saved to wlc_ha_results.csv")

    # Save all results to a single JSON file (overwrite each run)
    import json
    with open("wlc_ha_all_results-1.json", "w", encoding="utf-8") as jsonfile:
        json.dump(results, jsonfile, indent=4)
    print("Analysis complete. Results also saved to wlc_ha_all_results-1.json")

if __name__ == "__main__":
    main()
