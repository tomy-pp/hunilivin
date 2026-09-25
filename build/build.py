#!/usr/bin/env python3
"""Hunilivin site build: read the Google Sheet -> bake villa data into villas-data.js.

Runs locally (python3) and in GitHub Actions. Needs Pillow (for processing photo
LINKS added in the sheet: download -> crop 4:3 -> Hunilivin logo). Photos already
processed from the Desktop batch live in photos/<id>/ and are used when the sheet's
`photos` cell is empty.
"""
import urllib.request, csv, io, json, os, re, sys, hashlib

SHEET_ID = "1YXjx-jDYcppdzCFw42AZHSsIUTfbOWXIDnVe9tt762U"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "villas-data.js")
LOGO_SRC = os.path.join(ROOT, "logo-trim.png")
W, H = 1600, 1200
LOGO_W_FRAC = 0.22

FALLBACK = [
    "https://images.unsplash.com/photo-1613490493576-7fde63acd811?auto=format&fit=crop&w=1000&q=72",
    "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1000&q=72",
]

# ---------- sheet helpers ----------
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

def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

def norm_status(s):
    s = (s or "").strip().lower()
    if s in ("available", "avail", "ready"): return "available"
    if s in ("booked", "unavailable", "full"): return "booked"
    if s in ("soon", "coming soon", "coming-soon", "segera"): return "soon"
    return "available"

def repo_photos(vid):
    d = os.path.join(ROOT, "photos", vid)
    if os.path.isdir(d):
        files = sorted([f for f in os.listdir(d) if f.lower().endswith(".jpg")], key=natural_key)
        return [f"photos/{vid}/{f}" for f in files]
    return []

# ---------- image processing (for photo LINKS in the sheet) ----------
_PIL = {}
def _pil():
    if "ok" not in _PIL:
        try:
            from PIL import Image, ImageOps, ImageFilter
            a = Image.open(LOGO_SRC).convert("RGBA").getchannel("A")
            white = Image.new("RGBA", a.size, (255, 255, 255, 255)); white.putalpha(a)
            _PIL.update(ok=True, Image=Image, ImageOps=ImageOps, ImageFilter=ImageFilter, logo=white)
        except Exception as e:
            print("  (image processing unavailable:", e, ")", file=sys.stderr)
            _PIL["ok"] = False
    return _PIL["ok"]

def _crop_logo(img):
    Image, ImageOps, ImageFilter = _PIL["Image"], _PIL["ImageOps"], _PIL["ImageFilter"]
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size; t = 4/3
    if w/h > t:
        nw = int(h*t); x = (w-nw)//2; img = img.crop((x, 0, x+nw, h))
    else:
        nh = int(w/t); y = (h-nh)//2; img = img.crop((0, y, w, y+nh))
    img = img.resize((W, H), Image.LANCZOS)
    lw = int(W*LOGO_W_FRAC); logo = _PIL["logo"]; lh = int(logo.height*lw/logo.width)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    x = (W-lw)//2; y = int(H*0.16)
    base = img.convert("RGBA")
    sh = Image.new("RGBA", logo.size, (0, 0, 0, 0)); sh.putalpha(logo.getchannel("A"))
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0)); shadow.paste(sh, (x, y+2), sh)
    shadow = shadow.filter(ImageFilter.GaussianBlur(3))
    shadow.putalpha(shadow.getchannel("A").point(lambda a: int(a*0.35)))
    base = Image.alpha_composite(base, shadow); base.paste(logo, (x, y), logo)
    return base.convert("RGB")

def _drive_url(url):
    m = re.search(r"/file/d/([\w-]+)", url) or re.search(r"[?&]id=([\w-]+)", url)
    if m and "drive.google" in url:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url

def process_url(vid, url):
    """Download a photo link, crop 4:3 + add logo, save under photos/<vid>/. Cached. Returns path or None."""
    d = os.path.join(ROOT, "photos", vid); os.makedirs(d, exist_ok=True)
    cache_path = os.path.join(d, "_sources.json")
    cache = {}
    if os.path.exists(cache_path):
        try: cache = json.load(open(cache_path))
        except Exception: cache = {}
    if url in cache and os.path.exists(os.path.join(d, cache[url])):
        return f"photos/{vid}/{cache[url]}"
    if not _pil():
        return None
    try:
        req = urllib.request.Request(_drive_url(url), headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=45).read()
        img = _PIL["Image"].open(io.BytesIO(data))
        out = _crop_logo(img)
        fname = "link-" + hashlib.md5(url.encode()).hexdigest()[:10] + ".jpg"
        out.save(os.path.join(d, fname), quality=84, optimize=True)
        cache[url] = fname
        json.dump(cache, open(cache_path, "w"))
        print(f"    processed sheet photo: {vid}/{fname}")
        return f"photos/{vid}/{fname}"
    except Exception as e:
        print(f"    !! could not process {url[:60]}: {e}", file=sys.stderr)
        return None

def resolve_photos(vid, cell):
    """Sheet `photos` cell is the source of truth when filled; empty -> use the processed batch."""
    items = [x for x in split_pipe(cell) if not x.upper().startswith("PASTE_LINK")]
    if items:
        out = []
        for it in items:
            if it.startswith("http://") or it.startswith("https://"):
                p = process_url(vid, it)
                if p: out.append(p)
            else:
                fp = f"photos/{vid}/{it}"
                if os.path.exists(os.path.join(ROOT, fp)): out.append(fp)
        if out:
            return out
    return repo_photos(vid) or list(FALLBACK)

# ---------- main ----------
def main():
    try:
        raw = fetch_csv(CSV_URL)
    except Exception as e:
        print("ERROR fetching sheet:", e, file=sys.stderr); sys.exit(1)
    rows = list(csv.DictReader(io.StringIO(raw)))
    villas = []
    for r in rows:
        vid = (r.get("id") or "").strip(); name = (r.get("name") or "").strip()
        if not vid or not name: continue
        villas.append({
            "id": vid, "name": name, "area": (r.get("area") or "").strip(),
            "br": (r.get("bedrooms") or "").strip(), "ba": (r.get("bathrooms") or "").strip(),
            "price": int(num(r.get("price_idr"))), "lat": num(r.get("lat")), "lng": num(r.get("lng")),
            "near": [int(num(r.get("beach_min"))), int(num(r.get("airport_min")))],
            "status": norm_status(r.get("status")),
            "terms": split_pipe(r.get("rental_periods")) or ["Yearly"],
            "amenities": split_pipe(r.get("amenities")),
            "d_en": (r.get("description_en") or "").strip(), "d_id": (r.get("description_id") or "").strip(),
            "photos": resolve_photos(vid, r.get("photos")),
        })
    payload = "window.HUNI=" + json.dumps({"villas": villas}, ensure_ascii=False) + ";\n"
    open(OUT, "w", encoding="utf-8").write(payload)
    print(f"OK: wrote {len(villas)} villas to {OUT} ({len(payload)} bytes)")
    for v in villas:
        print(f"  - {v['id']} | {v['name']} | {v['status']} | Rp{v['price']:,} | {len(v['photos'])} photo(s)")

if __name__ == "__main__":
    main()
