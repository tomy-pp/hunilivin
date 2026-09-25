#!/usr/bin/env python3
"""Hunilivin site build: read the Google Sheet -> bake villa data into villas-data.js.

Runs both locally (python3) and in GitHub Actions. No third-party packages (stdlib only).
"""
import urllib.request, csv, io, json, os, re, sys

SHEET_ID = "1YXjx-jDYcppdzCFw42AZHSsIUTfbOWXIDnVe9tt762U"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "villas-data.js")

# Photos to show when a villa has no real photo yet (so the site never looks broken).
FALLBACK = [
    "https://images.unsplash.com/photo-1613490493576-7fde63acd811?auto=format&fit=crop&w=1000&q=72",
    "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1000&q=72",
    "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=1000&q=72",
]

def fetch_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (HunilivinBuild)"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8")

def split_pipe(s):
    return [x.strip() for x in (s or "").split("|") if x.strip()]

def num(s, default=0.0):
    try:
        return float(str(s).strip())
    except Exception:
        return default

def parse_photos(cell):
    out = []
    for item in split_pipe(cell):
        if item.upper().startswith("PASTE_LINK"):
            continue  # template placeholder, ignore
        if item.startswith("http://") or item.startswith("https://"):
            out.append(item)              # a full link -> use as-is
        else:
            out.append("photos/" + item)  # a bare filename -> hosted in repo
    return out or list(FALLBACK)

def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

def repo_photos(vid):
    d = os.path.join(ROOT, "photos", vid)
    if os.path.isdir(d):
        files = sorted([f for f in os.listdir(d) if f.lower().endswith(".jpg")], key=natural_key)
        return [f"photos/{vid}/{f}" for f in files]
    return []

def norm_status(s):
    s = (s or "").strip().lower()
    if s in ("available", "avail", "ready"): return "available"
    if s in ("booked", "unavailable", "full"): return "booked"
    if s in ("soon", "coming soon", "coming-soon", "segera"): return "soon"
    return "available"

def main():
    try:
        raw = fetch_csv(CSV_URL)
    except Exception as e:
        print("ERROR fetching sheet:", e, file=sys.stderr)
        sys.exit(1)
    rows = list(csv.DictReader(io.StringIO(raw)))
    villas = []
    for r in rows:
        vid = (r.get("id") or "").strip()
        name = (r.get("name") or "").strip()
        if not vid or not name:
            continue  # skip empty rows
        villas.append({
            "id": vid,
            "name": name,
            "area": (r.get("area") or "").strip(),
            "br": (r.get("bedrooms") or "").strip(),
            "ba": (r.get("bathrooms") or "").strip(),
            "price": int(num(r.get("price_idr"))),
            "lat": num(r.get("lat")),
            "lng": num(r.get("lng")),
            "near": [int(num(r.get("beach_min"))), int(num(r.get("airport_min")))],
            "status": norm_status(r.get("status")),
            "terms": split_pipe(r.get("rental_periods")) or ["Yearly"],
            "amenities": split_pipe(r.get("amenities")),
            "d_en": (r.get("description_en") or "").strip(),
            "d_id": (r.get("description_id") or "").strip(),
            "photos": repo_photos(vid) or parse_photos(r.get("photos")),
        })
    payload = "window.HUNI=" + json.dumps({"villas": villas}, ensure_ascii=False) + ";\n"
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(payload)
    print(f"OK: wrote {len(villas)} villas to {OUT} ({len(payload)} bytes)")
    for v in villas:
        print(f"  - {v['id']} | {v['name']} | {v['status']} | Rp{v['price']:,} | {'/'.join(v['terms'][:1])} | {len(v['photos'])} photo(s)")

if __name__ == "__main__":
    main()
