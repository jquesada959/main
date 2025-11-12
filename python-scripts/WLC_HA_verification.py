
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import pexpect
import json
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
    username = creds.get("user") or creds.get("username")
    password = creds.get("password")
    if not username or not password:
        raise Exception("Missing username or password in decrypted credentials.")
    return username, password

def analyze_wlc(ip, username, password):
    try:
        logging.info(f"Connecting to {ip} ...")
        ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {ip}"
        child = pexpect.spawn(ssh_cmd, encoding='utf-8', timeout=20)
        logfile = open('wlc_ha_verification.log', 'a')
        child.logfile = logfile





        # Wait for prompts and send carriage return after each
        prompts = ["User:", "Password:"]
        responses = [username, password]
        for prompt, response in zip(prompts, responses):
            idx = child.expect([prompt, pexpect.EOF, pexpect.TIMEOUT], timeout=20)
            if idx == 0:
                logging.info(f"'{prompt}' prompt received, sending response.")
                child.sendline(response)
            else:
                raise Exception(f"Did not receive expected prompt: {prompt}")

        # 4. Wait for shell prompt (could be '>', '#', etc.)
        idx = child.expect([">", "#", pexpect.EOF, pexpect.TIMEOUT], timeout=20)
        if idx in [0, 1]:
            logging.info("Shell prompt received after login.")
        else:
            raise Exception("Did not receive shell prompt after login.")

        def run_command(cmd):
            child.sendline(cmd)
            child.expect([">", "#"], timeout=20)
            output = child.before
            logging.info(f"Command '{cmd}' output: {output}")
            return output


        # Identify model and serial from 'show inventory'
        inventory_output = run_command("show inventory")
        import re
        pid_match = re.search(r"PID:\s*([\w-]+)", inventory_output)
        sn_match = re.search(r"SN:\s*([\w-]+)", inventory_output)
        if pid_match:
            pid = pid_match.group(1)
            if "5520" in pid:
                model = "5520"
            elif "5508" in pid:
                model = "5508"
            else:
                model = pid
        else:
            pid = "Unknown"
            model = "Unknown"
        serial = sn_match.group(1) if sn_match else "Unknown"

        # Run HA and anchor commands
        ha_summary = run_command("show redundancy summary")
        ha_state = run_command("show redundancy detail")
        mobility_summary = run_command("show mobility summary")
        mobility_anchor = run_command("show mobility anchor")

        child.sendline("exit")
        child.close()
        logfile.close()

        # Normalize output
        result = {
            "ip": ip,
            "model": model,
            "pid": pid,
            "serial": serial,
            "ha_summary": ha_summary.strip(),
            "ha_state": ha_state.strip(),
            "mobility_summary": mobility_summary.strip(),
            "mobility_anchor": mobility_anchor.strip(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        # Save to JSON log
        filename = f"wlc_log_{ip.replace('.', '_')}_{int(time.time())}.json"
        with open(filename, "w") as f:
            json.dump(result, f, indent=4)

        print(f"Analysis complete. Log saved to {filename}")
        logging.info(f"Analysis complete. Log saved to {filename}")

    except Exception as e:
        print(f"Error: {e}")
        logging.error(f"Error: {e}")

def main():
    # Read hosts from Hosts-WLCs.txt
    hosts = []
    try:
        with open("Hosts-WLCs.txt", "r") as f:
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
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_ip = {executor.submit(analyze_wlc, ip, username, password): ip for ip in hosts}
        for idx, future in enumerate(as_completed(future_to_ip), 1):
            ip = future_to_ip[future]
            try:
                future.result()
            except Exception as exc:
                print(f"{idx}: {ip} generated an exception: {exc}")
            else:
                print(f"{idx}: {ip}")

        # Consolidate all per-device JSON outputs into one file
        import glob
        all_json = []
        for json_file in glob.glob("wlc_log_*.json"):
            try:
                with open(json_file, "r") as f:
                    data = json.load(f)
                    all_json.append(data)
            except Exception as e:
                print(f"Could not read {json_file}: {e}")
        with open("wlc_ha_all_results.json", "w") as f:
            json.dump(all_json, f, indent=4)
        print("Consolidated all JSON outputs into wlc_ha_all_results.json")

if __name__ == "__main__":
    main()