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

Notes on scale (300 stops):
    - postcodes.io has no documented rate limit for reasonable use.
    - 0.1 s delay between calls → ~35 seconds for 300 stops on a good run.
    - max_attempts is set to 6x so transient failures and duplicates are handled.
    - Duplicate postcodes are silently skipped; the loop keeps going until
      NUM_DELIVERIES unique postcodes are collected.
"""

import urllib.request
import json
import csv
import random
import time
import os

# ── Reproducibility ───────────────────────────────────────────────
# random.seed(42): fixes Python's RNG so random.choice(OUTCODES), names, demand,
#   etc. are the same every run (reproducible thesis runs). "42" is arbitrary —
#   any fixed integer works; 42 is a common programmer joke (Hitchhiker's Guide).
random.seed(42) 

# Paths: no "return" here — these are module-level variables used later.
# REPO_ROOT: folder that contains `data/` (repo root), built from this file's
#   location so the script always writes to the same data/ no matter your cwd.
# DATA_DIR: .../data where deliveries.csv is written.
# os.makedirs(..., exist_ok=True): create data/ if missing; do nothing if it exists.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)


# ── Config ────────────────────────────────────────────────────────
NUM_DELIVERIES   = 300   # target unique delivery stops
Payload_Capacity = 1000 #in kg per vehicle
Cubic_Capacity = 10 #in cubic meters per vehicle
API_DELAY        = 0.1   # seconds between API calls — polite but not slow
MAX_RETRIES      = 3     # retries per failed API call before moving on

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

    # ── Nottinghamshire outskirts (MEDIUM — 2x) ───────────────────
    # Extended to 2x for bigger dataset coverage
    "NG10", "NG11", "NG15", "NG16", "NG6", "NG17",
    "NG10", "NG11", "NG15", "NG16", "NG6", "NG17",

    # ── Coventry city centre & inner (HEAVY — 3x) ─────────────────
    "CV1", "CV2", "CV3", "CV4", "CV5", "CV6",
    "CV1", "CV2", "CV3", "CV4", "CV5", "CV6",
    "CV1", "CV2", "CV3", "CV4", "CV5", "CV6",

    # ── Coventry & Warwickshire outskirts (LIGHT — 1x) ────────────
    "CV7", "CV8", "CV12",

    # ── Birmingham inner (MEDIUM-HEAVY — 2x) ─────────────────────
    "B1",  "B2",  "B3",  "B4",  "B5",  "B6",
    "B7",  "B8",  "B9",  "B10", "B11", "B12",
    "B1",  "B2",  "B3",  "B4",  "B5",  "B6",
    "B7",  "B8",  "B9",  "B10", "B11", "B12",

    # ── Birmingham mid-ring (MEDIUM — 2x) ────────────────────────
    "B13", "B14", "B15", "B16", "B17", "B18",
    "B13", "B14", "B15", "B16", "B17", "B18",

    # ── Birmingham outer suburbs (LIGHT — 1x) ─────────────────────
    "B90", "B91", "B92", "B73", "B74", "B75",
    "B20", "B21", "B23", "B24", "B25",

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

# ── API call ──────────────────────────────────────────────────────
def get_random_postcode(outcode, retries=MAX_RETRIES):
    """
    GET https://api.postcodes.io/random/postcodes?outcode=<outcode>
    Docs: https://postcodes.io/docs/postcode/random

    Retries up to `retries` times on network error before giving up.
    Returns (postcode, latitude, longitude) or None.
    """
    url = f"https://api.postcodes.io/random/postcodes?outcode={outcode}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            r = data.get("result")
            if r and r.get("latitude") and r.get("longitude"):
                return (r["postcode"], r["latitude"], r["longitude"])
            return None  # API responded but no usable result (outcode has no postcodes)
        except Exception:
            if attempt < retries - 1:
                time.sleep(0.3 * (attempt + 1))  # brief back-off before retry
    return None


# ── Step 1: Fetch real postcodes from the API ─────────────────────
print("  DPD Hinckley — Delivery Dataset Generator")
print(f"\n  Depot        : DPD Hinckley  LE10 3BQ")
print(f"  Target stops : {NUM_DELIVERIES}")
print(f"  Coverage     : Leicestershire, Nottinghamshire,")
print(f"                 Coventry, Birmingham + suburbs")
print(f"  API delay    : {API_DELAY}s per call  (polite rate)\n")
print("  Fetching unique postcodes from postcodes.io...")
print("  (GET /random/postcodes?outcode=XX  — duplicates skipped)\n")

collected    = []        # list of (postcode, lat, lon, quality)
seen         = set()     # set of already-collected postcodes
attempts     = 0
api_errors   = 0
max_attempts = NUM_DELIVERIES * 6   # 6x headroom for duplicates + failures

while len(collected) < NUM_DELIVERIES and attempts < max_attempts:
    outcode = random.choice(OUTCODES)   # weighted random — city outcodes appear 3x
    result  = get_random_postcode(outcode)
    if result:
        postcode, lat, lon = result
        if postcode not in seen:
            collected.append(result)
            seen.add(postcode)
            n = len(collected)
            if n % 30 == 0 or n == NUM_DELIVERIES:
                pct = n / NUM_DELIVERIES * 100
                print(f"  {n:>3}/{NUM_DELIVERIES}  ({pct:.0f}%) — latest: {postcode}")
    else:
        api_errors += 1

    attempts += 1
    time.sleep(API_DELAY)

print(f"\n  Collected : {len(collected)} unique postcodes")
print(f"  Attempts  : {attempts}  (API errors: {api_errors})\n")

if len(collected) < NUM_DELIVERIES:
    print("  WARNING: Could not reach the target number of stops.")
    print(f"  Got {len(collected)}/{NUM_DELIVERIES}.")
    print("  Check your internet connection or reduce NUM_DELIVERIES.")
    raise SystemExit(1)

def create_parcel():
    """
    Randomly select a parcel type with pre-set weight and volume:
    - 10kg, 0.050 m³
    - 20kg, 0.100 m³
    - 30kg, 0.150 m³
    """
    parcel_types = [
        {"weight": 10, "volume": 0.10},
        {"weight": 20, "volume": 0.150},
        {"weight": 30, "volume": 0.200},
    ]
    return random.choice(parcel_types)

# Example usage: attach parcels to each delivery row
parcels = [create_parcel() for _ in range(NUM_DELIVERIES)]


# ── Step 2: Build delivery rows ───────────────────────────────────
rows = []
for i, (postcode, lat, lon) in enumerate(collected):
    rows.append({
        "delivery_id":   str(i+1),
        "customer_name": f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
        "postcode":      postcode,
        "parcel":        parcels[i],
        "latitude":      round(lat, 6),
        "longitude":     round(lon, 6),
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
    "delivery_id":   "0",
    "customer_name": "DPD Hinckley Depot",
    "postcode":      "LE10 3BQ",
    "parcel":        {"weight": 0, "volume": 0},
    "latitude":      round(depot_lat, 6),
    "longitude":     round(depot_lon, 6),
}

all_rows = [depot_row] + rows


# ── Step 4: Save CSV ──────────────────────────────────────────────
output_file = os.path.join(DATA_DIR, "deliveries_withparcels.csv")
fieldnames  = ["delivery_id", "customer_name", "postcode","parcel",
               "latitude", "longitude"]

with open(output_file, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(all_rows)


# ── Step 5: Summary ───────────────────────────────────────────────
total_weight   = sum(r["parcel"]["weight"] for r in rows)
total_volume   = sum(r["parcel"]["volume"] for r in rows)

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

print("=" * 60)
print("  Dataset ready")
print("=" * 60)
print(f"  File            : {output_file}")
print(f"  Depot           : DPD Hinckley  LE10 3BQ")
print(f"  Delivery stops  : {len(rows)}")
print(f"  Total weight    : {total_weight} kg")
print(f"  Total volume    : {total_volume} m³")
print(f"  Vehicle capacity: {Payload_Capacity} kg per vehicle")
print(f"  Vehicle capacity: {Cubic_Capacity} m³ per vehicle")
print(f"  Min vehicles    : {-(-total_weight // Payload_Capacity)}"
      f"(to carry all weight)")
print(f"  Min vehicles    : {-(-total_volume // Cubic_Capacity)}"
      f"(to carry all volume)")
print()
print("  By region:")
for region, count in sorted(region_counts.items(), key=lambda x: -x[1]):
    bar = "█" * (count // 5)
    print(f"    {region:<20} {count:>3}  {bar}")
print()
print("  First 6 rows:")
print(f"  {'ID':<8} {'Postcode':<12} {'Lat':>10} {'Lon':>10} {'Weight':>5} {'Volume':>5}  Priority")
print(f"  {'-'*62}")
for r in all_rows[:6]:
    print(f"  {r['delivery_id']:<8} {r['postcode']:<12} "
          f"{r['latitude']:>10} {r['longitude']:>10} "
          f"{r['parcel']['weight']:>5} {r['parcel']['volume']:>5}")
print("=" * 60)
print()
print("  Next step: run  python cluster2.py")
print("  to partition stops into van zones.")
