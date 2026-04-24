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

    # ── Leicester city centre & inner (HEAVY — 3x) ────────────────
    "LE1", "LE2", "LE3", "LE4", "LE5",
    "LE1", "LE2", "LE3", "LE4", "LE5",
    "LE1", "LE2", "LE3", "LE4", "LE5",

    # ── Leicester suburbs (MEDIUM — 2x) ──────────────────────────
    "LE6", "LE7", "LE8", "LE9", "LE18", "LE19",
    "LE6", "LE7", "LE8", "LE9", "LE18", "LE19",

    # ── Hinckley & nearby towns (LIGHT — 1x) ─────────────────────
    "LE10", "CV10", "CV11", "CV13",

    # ── Nottingham city centre & inner (HEAVY — 3x) ───────────────
    "NG1", "NG2", "NG3", "NG5", "NG7", "NG8", "NG9",
    "NG1", "NG2", "NG3", "NG5", "NG7", "NG8", "NG9",
    "NG1", "NG2", "NG3", "NG5", "NG7", "NG8", "NG9",

    # ── Nottinghamshire outskirts (LIGHT — 1x) ────────────────────
    "NG10", "NG11", "NG15", "NG16",

    # ── Coventry city centre & inner (HEAVY — 3x) ─────────────────
    "CV1", "CV2", "CV3", "CV4", "CV5", "CV6",
    "CV1", "CV2", "CV3", "CV4", "CV5", "CV6",
    "CV1", "CV2", "CV3", "CV4", "CV5", "CV6",

    # ── Birmingham inner (MEDIUM-HEAVY — 2x) ─────────────────────
    "B1",  "B2",  "B3",  "B4",  "B5",  "B6",
    "B7",  "B8",  "B9",  "B10", "B11", "B12",
    "B1",  "B2",  "B3",  "B4",  "B5",  "B6",
    "B7",  "B8",  "B9",  "B10", "B11", "B12",

    # ── Birmingham outer suburbs (LIGHT — 1x) ─────────────────────
    "B90", "B91", "B92", "B73", "B74", "B75",

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
    outcode = OUTCODES[len(collected) % len(OUTCODES)]
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
output_file = os.path.join(DATA_DIR, "deliveries.csv")
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
region_counts = {}
for r in rows:
    prefix = r["postcode"][:2].strip()
    if prefix.startswith("LE"):
        region = "Leicestershire"
    elif prefix.startswith("NG"):
        region = "Nottinghamshire"
    elif prefix.startswith("CV"):
        region = "Coventry/Nuneaton"
    elif prefix.startswith("B"):
        region = "Birmingham"
    else:
        region = "Other"
    region_counts[region] = region_counts.get(region, 0) + 1

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
print("  By region:")
for region, count in sorted(region_counts.items(),
                             key=lambda x: -x[1]):
    bar = "█" * (count // 2)
    print(f"    {region:<20} {count:>3}  {bar}")
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
