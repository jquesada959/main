#!/usr/bin/env python3
"""
nb_devices_filter.py
Pull NetBox devices by filters (role, status, site, location, device-type, tags).

Usage examples:
  # All "core-switch" role devices at site "dc1" that are active
  python nb_devices_filter.py --role core-switch --site dc1 --status active

  # Devices at a specific location by name, with OR across status values
  python nb_devices_filter.py --location "Room 101" --status active --status offline
  # Filter by multiple device types (slug) and tags (tags are ANDed by NetBox REST)
  python nb_devices_filter.py --device-type c9300-48p --device-type c9500-40x --tag prod --tag campus

Environment:
  NETBOX_URL   e.g. https://netbox.example.com
  NETBOX_TOKEN Your NetBox API token (read permissions)
"""

import os
import sys
import argparse
import pynetbox

def env(name: str, required=True):
    val = os.getenv(name)
    if required and not val:
        print(f"Missing env var {name}", file=sys.stderr)
        sys.exit(2)
    return val

def connect():
    url = env("NETBOX_URL")
    token = env("NETBOX_TOKEN")
    # threading=True speeds up large queries when MAX_PAGE_SIZE is set sensibly server-side
    api = pynetbox.api(url, token=token, threading=True)
    # Disable SSL verification (for self-signed certs; not recommended for production)
    try:
        import requests
        api.http_session.verify = False
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    return api

def find_site_id(nb, site_slug_or_name):
    # Accept 3-letter code and match to slug or name starting with those letters (case-insensitive)
    if len(site_slug_or_name) == 3:
        # Try to find a site whose slug or name starts with the 3 letters
        for s in nb.dcim.sites.all():
            if s.slug.lower().startswith(site_slug_or_name.lower()) or s.name.lower().startswith(site_slug_or_name.lower()):
                return s.id
        return None
    # Otherwise, try slug first, then name
    site = nb.dcim.sites.get(slug=site_slug_or_name) or nb.dcim.sites.get(name=site_slug_or_name)
    return site.id if site else None

def find_role_id(nb, role_slug_or_name):
    role = nb.dcim.device_roles.get(slug=role_slug_or_name) or nb.dcim.device_roles.get(name=role_slug_or_name)
    return role.id if role else None

def find_location_id(nb, location_slug_or_name):
    # Location filtering is disabled in this version
    return None

def find_device_type_id_by_slug(nb, dt_slug):
    # Device type filtering is disabled in this version
    return None

def build_filters(nb, args):
    f = {}

    # Status (choice field). You can pass multiple values (OR).
    if args.status:
        # e.g. ["active","offline"]
        f["status"] = args.status

    # Device Role: prefer role_id for compatibility
    if args.role:
        rid = find_role_id(nb, args.role)
        if not rid:
            print(f"Warning: Device role not found: {args.role}. Continuing without role filter.", file=sys.stderr)
        else:
            f["role_id"] = [rid]  # list -> OR if you later add more

    # Site: prefer site_id for compatibility
    if args.site:
        sid = find_site_id(nb, args.site)
        if not sid:
            sys.exit(f"Site not found: {args.site}")
        f["site_id"] = [sid]

    # Location filtering is disabled in this version

    # Device type filtering is disabled in this version

    # Tag filtering is disabled in this version
    # Tenants / Platforms / Manufacturers could be added similarly (resolve to *_id lists).
    # Free-text search is disabled in this version

    return f


def main():
    import getpass

    parser = argparse.ArgumentParser(description="Filter NetBox devices")
    parser.add_argument("--fields", default="name,primary_ip.address",
                        help="Comma-separated fields to print")
    args = parser.parse_args([])  # ignore CLI args, use only prompts below

    def prompt(msg, allow_empty=True):
        val = input(msg).strip()
        if not allow_empty and not val:
            print("This field is required.")
            sys.exit(1)
        return val if val else None

    import re
    while True:
        site = prompt("Enter site (3-letter code) [optional]: ", allow_empty=True)
        if not site:
            args.site = None
            break
        if re.fullmatch(r"[A-Za-z]{3}", site):
            args.site = site
            break
        print("Site must be exactly 3 letters or left blank.")
    device_role_input = prompt("Enter device role (slug or name) [optional]: ")
    args.role = device_role_input.strip() if device_role_input else None

    args.status = ["active"]  # always filter by active status
    has_primary_ip = prompt("Only devices with a primary IP? (y/n): ", allow_empty=False).lower()
    args.has_primary_ip = has_primary_ip.startswith('y')

    include_manufacturer = prompt("Do you want to include the manufacturer field? (y/n): ", allow_empty=False).lower().startswith('y')

    nb = connect()
    filters = build_filters(nb, args)

    # Query devices
    devices = nb.dcim.devices.filter(**filters)  # generator

    # Output file
    out_filename = f"Hosts-{site}.txt"
    fields = [f.strip() for f in args.fields.split(",")]

    def pick(obj, dotted):
        cur = obj
        for part in dotted.split("."):
            cur = getattr(cur, part, None)
            if cur is None:
                return None
        return cur

    count = 0
    with open(out_filename, "w") as outf:
        for d in devices:
            if args.has_primary_ip and not getattr(d, "primary_ip", None):
                continue
            # Filter by device role if specified
            if args.role:
                dr_slug = getattr(getattr(d, "device_role", None), "slug", None)
                dr_name = getattr(getattr(d, "device_role", None), "name", None)
                if not dr_slug and not dr_name:
                    continue
                if dr_slug != args.role and dr_name != args.role:
                    continue
            name = pick(d, "name")
            ip = pick(d, "primary_ip.address")
            if args.has_primary_ip and not ip:
                continue
            # Remove subnet mask if present
            ip_clean = ip.split('/')[0] if ip else ''
            line = f"{name} {ip_clean}"
            if include_manufacturer:
                manufacturer = getattr(getattr(d, "device_type", None), "manufacturer", None)
                manufacturer_name = getattr(manufacturer, "name", "") if manufacturer else ""
                line += f" {manufacturer_name}"
            outf.write(line + "\n")
            count += 1
    print(f"Wrote {count} devices to {out_filename}")

if __name__ == "__main__":
    main()