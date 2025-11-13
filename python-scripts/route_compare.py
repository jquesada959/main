import csv

# Read routes from routes.csv
with open('routes1.csv', newline='') as f:
    reader = csv.DictReader(f)
    route_set = set(row['Route'].strip() for row in reader if row['Route'].strip())

# Read AD_routes.csv and compare
matches = []
with open('AD_routes.csv', newline='') as f:
    reader = csv.reader(f, delimiter='\t')
    header = next(reader)
    site_col = header[0]
    for row in reader:
        site = row[0].strip()
        # Subnets may be separated by tabs or spaces
        subnets = [s.strip() for s in row[1:] if s.strip()]
        for subnet in subnets:
            # Some subnets may have extra spaces
            if subnet in route_set:
                matches.append((site, subnet))

# Write matches to route_comparison.csv
with open('route_comparison1.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['SiteName', 'MatchedRoute'])
    for site, route in matches:
        writer.writerow([site, route])

print(f"Found {len(matches)} matching routes. Results saved to route_comparison.csv.")
