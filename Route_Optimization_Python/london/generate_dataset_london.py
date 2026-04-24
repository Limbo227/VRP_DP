"""
Delivery Dataset Generator — DPD Hinckley Depot
------------------------------------------------
Depot   : DPD Hinckley, LE10 3BQ
Coverage: Leicestershire, Nottinghamshire, Coventry, Birmingham

Weighting logic (mimics real courier density):
    City centres  → appear 3x in outcode list (most deliveries)
    Suburbs       → appear 2x
    Outskirts     → appear 1x

No pip installs required. Uses only Python built-in libraries.
Coordinates fetched from postcodes.io free API.

    Endpoint: GET https://api.postcodes.io/random/postcodes?outcode=LE1
    Docs    : https://postcodes.io/docs/postcode/random

Run:
    python generate_dataset.py

Output:
    deliveries.csv
"""

import urllib.request
import json
import csv
import random
import time
import os

# ── Reproducibility ───────────────────────────────────────────────
random.seed(42)

# Repo root (so script works regardless of current working directory)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ── Config ────────────────────────────────────────────────────────
NUM_DELIVERIES   = 120   # increased for a richer dataset
VEHICLE_CAPACITY = 25    # parcels per vehicle

# ── Weighted outcode list ─────────────────────────────────────────
# Cities appear 3x, suburbs 2x, outskirts 1x.
# This means the random sampler naturally picks city postcodes
# more often, matching real courier delivery distribution.

OUTCODES = [

    # ── City of London & West Central (HEAVY — 3x) ───────────────
    # Highest delivery density in the UK — offices, flats, businesses
    "EC1", "EC2", "EC3", "EC4", "WC1", "WC2",
    "EC1", "EC2", "EC3", "EC4", "WC1", "WC2",
    "EC1", "EC2", "EC3", "EC4", "WC1", "WC2",

    # ── West End & Central West (HEAVY — 3x) ─────────────────────
    # W1 = Mayfair, Soho, Oxford Street — extremely dense
    # SW1 = Westminster, Victoria, Pimlico
    # SE1 = Southwark, London Bridge, Bermondsey
    # N1  = Islington, Angel
    # E1  = Whitechapel, Shoreditch, Spitalfields
    # NW1 = Camden, Regent's Park
    "W1", "SW1", "SE1", "N1", "E1", "NW1",
    "W1", "SW1", "SE1", "N1", "E1", "NW1",
    "W1", "SW1", "SE1", "N1", "E1", "NW1",

    # ── Inner West & South West (MEDIUM — 2x) ────────────────────
    # W2 = Paddington, Bayswater
    # W6 = Hammersmith   W8 = Kensington   W11 = Notting Hill
    # SW3 = Chelsea       SW6 = Fulham      SW7 = South Kensington
    # SW8 = Stockwell     SW9 = Brixton     SW10 = West Brompton
    "W2",  "W6",  "W8",  "W11",
    "SW3", "SW6", "SW7", "SW8", "SW9", "SW10",
    "W2",  "W6",  "W8",  "W11",
    "SW3", "SW6", "SW7", "SW8", "SW9", "SW10",

    # ── Inner East & North (MEDIUM — 2x) ─────────────────────────
    # E2 = Bethnal Green   E3 = Bow   E8 = Hackney   E9 = Homerton
    # N4 = Finsbury Park   N5 = Highbury   N7 = Holloway
    # NW3 = Hampstead      NW5 = Kentish Town   NW6 = Kilburn
    "E2",  "E3",  "E8",  "E9",
    "N4",  "N5",  "N7",
    "NW3", "NW5", "NW6",
    "E2",  "E3",  "E8",  "E9",
    "N4",  "N5",  "N7",
    "NW3", "NW5", "NW6",

    # ── Inner South East (MEDIUM — 2x) ───────────────────────────
    # SE5 = Camberwell   SE8 = Deptford    SE10 = Greenwich
    # SE11 = Vauxhall    SE14 = New Cross  SE15 = Peckham
    # SE16 = Rotherhithe SE17 = Walworth
    "SE5", "SE8", "SE10", "SE11", "SE14", "SE15", "SE16", "SE17",
    "SE5", "SE8", "SE10", "SE11", "SE14", "SE15", "SE16", "SE17",

    # ── Outer West (LIGHT — 1x) ───────────────────────────────────
    # W3 = Acton  W4 = Chiswick  W5 = Ealing  W7 = Hanwell
    # W12 = Shepherd's Bush  W13 = West Ealing  W14 = West Kensington
    "W3", "W4", "W5", "W7", "W12", "W13", "W14",

    # ── Outer South West (LIGHT — 1x) ────────────────────────────
    # SW11 = Battersea   SW12 = Balham    SW15 = Putney
    # SW16 = Streatham   SW17 = Tooting   SW18 = Wandsworth
    # SW19 = Wimbledon   SW20 = Raynes Park
    "SW11", "SW12", "SW15", "SW16", "SW17", "SW18", "SW19", "SW20",

    # ── Outer South East (LIGHT — 1x) ────────────────────────────
    # SE4 = Brockley  SE6 = Catford   SE12 = Lee   SE13 = Lewisham
    # SE18 = Woolwich SE19 = Crystal Palace  SE22 = East Dulwich
    # SE23 = Forest Hill  SE25 = South Norwood  SE26 = Sydenham
    "SE4", "SE6", "SE12", "SE13", "SE18", "SE19", "SE22", "SE23", "SE25", "SE26",

    # ── Outer East (LIGHT — 1x) ───────────────────────────────────
    # E6 = Beckton/East Ham  E10 = Leyton   E11 = Leytonstone
    # E13 = Plaistow  E15 = Stratford  E16 = Canning Town  E17 = Walthamstow
    "E6", "E10", "E11", "E13", "E15", "E16", "E17",

    # ── Outer North (LIGHT — 1x) ──────────────────────────────────
    # N8 = Hornsey  N10 = Muswell Hill  N11 = New Southgate
    # N15 = Seven Sisters  N16 = Stoke Newington  N17 = Tottenham
    # N22 = Wood Green
    "N8", "N10", "N11", "N15", "N16", "N17", "N22",

    # ── Outer North West (LIGHT — 1x) ────────────────────────────
    # NW2 = Cricklewood  NW4 = Hendon  NW7 = Mill Hill
    # NW9 = The Hyde     NW10 = Park Royal / Willesden
    "NW2", "NW4", "NW7", "NW9", "NW10",

]

# ── Name pools ────────────────────────────────────────────────────
FIRST_NAMES = [
    "James", "Emily", "Mohammed", "Sarah", "Liam", "Priya", "Oliver",
    "Fatima", "Noah", "Charlotte", "Aiden", "Amelia", "Ethan", "Zara",
    "Lucas", "Isabella", "Harry", "Sophia", "George", "Mia", "Ravi",
    "Aisha", "Daniel", "Chloe", "Aaron", "Nadia", "Leon", "Yasmin",
    "Tyler", "Simran",
]
LAST_NAMES = [
    "Smith", "Patel", "Khan", "Williams", "Brown", "Jones", "Taylor",
    "Ahmed", "Wilson", "Johnson", "Davis", "Singh", "Ali", "Thomas",
    "Roberts", "Evans", "Walker", "Hill", "Morris", "Clarke", "Begum",
    "Hussain", "Rahman", "Kaur", "Shah", "Sharma", "Iqbal", "Nwosu",
    "Osei", "Kowalski",
]

# 75% standard, 25% express — realistic courier split
PRIORITIES = ["standard", "standard", "standard", "express"]


# ── API call ──────────────────────────────────────────────────────
def get_random_postcode(outcode):
    """
    GET https://api.postcodes.io/random/postcodes?outcode=<outcode>
    Docs: https://postcodes.io/docs/postcode/random

    Returns (postcode, latitude, longitude) or None on failure.
    """
    url = f"https://api.postcodes.io/random/postcodes?outcode={outcode}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        r = data.get("result")
        if r and r.get("latitude") and r.get("longitude"):
            return (r["postcode"], r["latitude"], r["longitude"])
    except Exception:
        pass
    return None


# ── Step 1: Fetch real postcodes from the API ─────────────────────
print("=" * 56)
print("  DPD Hinckley — Delivery Dataset Generator")
print("=" * 56)
print(f"\n  Depot   : DPD Hinckley  LE10 3BQ")
print(f"  Target  : {NUM_DELIVERIES} delivery stops")
print(f"  Coverage: Leicestershire, Nottinghamshire,")
print(f"            Coventry, Birmingham\n")
print("  Fetching real postcodes from postcodes.io...")
print("  (GET /random/postcodes?outcode=...)\n")

collected    = []   # list of (postcode, lat, lon)
seen         = set()
attempts     = 0
max_attempts = NUM_DELIVERIES * 4

while len(collected) < NUM_DELIVERIES and attempts < max_attempts:
    outcode = OUTCODES[attempts % len(OUTCODES)]
    result  = get_random_postcode(outcode)

    if result:
        postcode, lat, lon = result
        if postcode not in seen:
            collected.append(result)
            seen.add(postcode)
            if len(collected) % 20 == 0:
                print(f"  {len(collected)}/{NUM_DELIVERIES} collected...")

    attempts += 1
    time.sleep(0.05)   # polite delay for free API

print(f"\n  Done. {len(collected)} unique postcodes fetched.\n")

if len(collected) < NUM_DELIVERIES:
    print("  WARNING: Could not collect enough postcodes.")
    print("  Check your internet connection or reduce NUM_DELIVERIES.")
    raise SystemExit(1)


# ── Step 2: Build delivery rows ───────────────────────────────────
rows = []
for i, (postcode, lat, lon) in enumerate(collected):
    rows.append({
        "delivery_id":   f"D{i+1:03d}",
        "customer_name": f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
        "postcode":      postcode,
        "latitude":      round(lat, 6),
        "longitude":     round(lon, 6),
        "demand":        random.randint(1, 5),
        "priority":      random.choice(PRIORITIES),
    })


# ── Step 3: Depot row first ───────────────────────────────────────
# DPD Hinckley depot — LE10 3BQ
# Verified via: GET https://api.postcodes.io/postcodes/LE103BQ
print("  Verifying depot postcode LE10 3BQ...")
depot_data = get_random_postcode("LE10")
try:
    with urllib.request.urlopen(
        "https://api.postcodes.io/postcodes/LE103BQ", timeout=10
    ) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    depot_lat = d["result"]["latitude"]
    depot_lon = d["result"]["longitude"]
    print(f"  Depot confirmed: {depot_lat}, {depot_lon}\n")
except Exception:
    # Fallback coordinates if API is unreachable
    depot_lat = 52.538069
    depot_lon = -1.357398
    print("  Using fallback depot coordinates.\n")

depot_row = {
    "delivery_id":   "DEPOT",
    "customer_name": "DPD Hinckley Depot",
    "postcode":      "LE10 3BQ",
    "latitude":      round(depot_lat, 6),
    "longitude":     round(depot_lon, 6),
    "demand":        0,
    "priority":      "depot",
}

all_rows = [depot_row] + rows


# ── Step 4: Save CSV ──────────────────────────────────────────────
output_file = os.path.join(DATA_DIR, "deliveries_london.csv")
fieldnames  = ["delivery_id", "customer_name", "postcode",
               "latitude", "longitude", "demand", "priority"]

with open(output_file, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(all_rows)


# ── Step 5: Summary ───────────────────────────────────────────────
total_demand   = sum(r["demand"] for r in rows)
express_count  = sum(1 for r in rows if r["priority"] == "express")
standard_count = sum(1 for r in rows if r["priority"] == "standard")

# Count by rough region based on postcode prefix
# region_counts = {}
# for r in rows:
#     prefix = r["postcode"][:2].strip()
#     if prefix.startswith("LE"):
#         region = "Leicestershire"
#     elif prefix.startswith("NG"):
#         region = "Nottinghamshire"
#     elif prefix.startswith("CV"):
#         region = "Coventry/Nuneaton"
#     elif prefix.startswith("B"):
#         region = "Birmingham"
#     else:
#         region = "Other"
#     region_counts[region] = region_counts.get(region, 0) + 1

print("=" * 56)
print("  Dataset ready")
print("=" * 56)
print(f"  File            : {output_file}")
print(f"  Depot           : DPD Hinckley  LE10 3BQ")
print(f"  Delivery stops  : {NUM_DELIVERIES}")
print(f"  Total parcels   : {total_demand}")
print(f"  Vehicle capacity: {VEHICLE_CAPACITY} parcels each")
print(f"  Min vehicles    : {-(-total_demand // VEHICLE_CAPACITY)} "
      f"(to carry all parcels)")
print()
print("  By priority:")
print(f"    Standard : {standard_count}")
print(f"    Express  : {express_count}")
print()
# print("  By region:")
# for region, count in sorted(region_counts.items(),
#                              key=lambda x: -x[1]):
#     bar = "█" * (count // 2)
#     print(f"    {region:<20} {count:>3}  {bar}")
print()
print("  First 6 rows:")
print(f"  {'ID':<8} {'Postcode':<10} {'Lat':>10} "
      f"{'Lon':>10} {'Dmnd':>5}  Priority")
print(f"  {'-'*58}")
for r in all_rows[:6]:
    print(f"  {r['delivery_id']:<8} {r['postcode']:<10} "
          f"{r['latitude']:>10} {r['longitude']:>10} "
          f"{r['demand']:>5}  {r['priority']}")
print("=" * 56)
print()
print("  Next step: run  python visualize_map.py")
print("  to see all stops plotted on an interactive map.")
