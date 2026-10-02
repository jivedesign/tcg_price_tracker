#!/usr/bin/env python3
"""TCG price collector.
  python collect.py daily                      # MTG (Scryfall) + other games (TCGCSV) + stocks
  python collect.py init-mtg                   # lock the top-N MTG cards by EDHREC rank
  python collect.py backfill-mtg               # one-off: ~90 days of history from MTGJSON
  python collect.py find GAME QUERY [SET]      # look up product/group ids for watchlist.json
"""
import gzip, json, pathlib, sys, time, datetime as dt
import requests

R = pathlib.Path(__file__).parent
DATA = R / "data"; DATA.mkdir(exist_ok=True)
UA = {"User-Agent": "tcg-price-tracker/1.0 (personal project; put your repo URL here)", "Accept": "application/json"}
TODAY = dt.datetime.now(dt.timezone.utc).date().isoformat()
CFG = json.loads((R / "watchlist.json").read_text())
T = "https://tcgcsv.com/tcgplayer"

def http(method, url, h=None, **kw):
    time.sleep(0.6)  # stay polite: Scryfall allows ~2 req/s on these endpoints
    r = requests.request(method, url, headers={**UA, **(h or {})}, timeout=90, **kw)
    r.raise_for_status()
    return r

def load(p, default):
    return json.loads(p.read_text()) if p.exists() else default

def save(p, obj):
    p.write_text(json.dumps(obj, separators=(",", ":"), sort_keys=True))

def store(game, label, rows):
    """rows: (key, meta, {date: price}). Merges into data/<game>.json, never duplicates a date."""
    f = DATA / f"{game}.json"
    o = load(f, {"label": label, "items": {}})
    for key, meta, series in rows:
        it = o["items"].setdefault(key, {**meta, "s": {}})
        it["s"].update({d: p for d, p in series.items() if p is not None})
    o["asOf"] = TODAY
    save(f, o)
    games = [{"id": g.stem, "label": load(g, {}).get("label", g.stem)}
             for g in sorted(DATA.glob("*.json")) if g.stem not in ("index", "stocks")]
    save(DATA / "index.json", {"games": games, "asOf": TODAY})

# ---- Magic: Scryfall (daily) + MTGJSON (one-off backfill) -------------------
def init_mtg():
    r = http("GET", "https://api.scryfall.com/cards/search",
             params={"q": "game:paper legal:commander", "order": "edhrec", "dir": "asc"}).json()
    cards = [c for c in r["data"] if c["prices"].get("usd")][:CFG["mtg"]["top_n"]]
    save(R / "mtg_cards.json", [{"id": c["id"], "name": c["name"], "set": c["set_name"]} for c in cards])
    print(f"Locked {len(cards)} MTG printings")

def daily_mtg():
    if not (R / "mtg_cards.json").exists():
        init_mtg()
    cards, rows = load(R / "mtg_cards.json", []), []
    for i in range(0, len(cards), 75):
        res = http("POST", "https://api.scryfall.com/cards/collection",
                   json={"identifiers": [{"id": c["id"]} for c in cards[i:i + 75]]}).json()["data"]
        for c in res:
            p = c["prices"].get("usd") or c["prices"].get("usd_foil")
            rows.append((c["id"], {"name": c["name"], "set": c["set_name"]}, {TODAY: float(p) if p else None}))
    store("mtg", "Magic: The Gathering", rows)

def backfill_mtg():
    import ijson  # streams the huge MTGJSON files so memory stays small
    want = {c["id"]: c for c in load(R / "mtg_cards.json", [])}
    def stream(name):
        r = requests.get("https://mtgjson.com/api/v5/" + name, headers=UA, stream=True, timeout=600)
        r.raise_for_status()
        return gzip.GzipFile(fileobj=r.raw)
    u2s = {u: c["identifiers"]["scryfallId"] for u, c in ijson.kvitems(stream("AllIdentifiers.json.gz"), "data")
           if c.get("identifiers", {}).get("scryfallId") in want}
    rows = []
    for u, p in ijson.kvitems(stream("AllPrices.json.gz"), "data"):
        if u in u2s:
            retail = p.get("paper", {}).get("tcgplayer", {}).get("retail", {})
            ser = retail.get("normal") or retail.get("foil") or {}
            c = want[u2s[u]]
            rows.append((u2s[u], {"name": c["name"], "set": c["set"]}, {d: float(v) for d, v in ser.items()}))
    store("mtg", "Magic: The Gathering", rows)
    print(f"Backfilled {len(rows)} printings")

# ---- Other games: TCGCSV (mirror of TCGplayer prices) ----------------------
def cat_id(name):
    res = http("GET", f"{T}/categories").json()["results"]
    hit = [c for c in res if c["name"].lower() == name.lower()] or [c for c in res if name.lower() in c["name"].lower()]
    return hit[0]["categoryId"]

def daily_tcg():
    for g, spec in CFG["games"].items():
        cards = spec.get("cards", [])
        if not cards:
            continue
        cat, rows = cat_id(spec["category"]), []
        for gid in sorted({c["group_id"] for c in cards}):
            prices = http("GET", f"{T}/{cat}/{gid}/prices").json()["results"]
            for c in (x for x in cards if x["group_id"] == gid):
                sub = c.get("sub", "Normal")
                p = next((x["marketPrice"] for x in prices
                          if x["productId"] == c["product_id"] and x["subTypeName"] == sub), None)
                rows.append((str(c["product_id"]), {"name": c["name"], "set": c.get("set", ""), "sub": sub}, {TODAY: p}))
        store(g, spec["label"], rows)

def find(game, query, group=""):
    cat = cat_id(CFG["games"][game]["category"])
    for grp in http("GET", f"{T}/{cat}/groups").json()["results"]:
        if group.lower() not in grp["name"].lower():
            continue
        for p in http("GET", f"{T}/{cat}/{grp['groupId']}/products").json()["results"]:
            if query.lower() in p["name"].lower():
                print(json.dumps({"name": p["name"], "set": grp["name"], "group_id": grp["groupId"],
                                  "product_id": p["productId"], "sub": "Normal"}))

# ---- Stocks: Yahoo's unofficial chart endpoint (may break; failures are non-fatal per ticker)
def stocks():
    rows = []
    for t in CFG["stocks"]:
        try:
            j = http("GET", f"https://query1.finance.yahoo.com/v8/finance/chart/{t}",
                     h={"User-Agent": "Mozilla/5.0"}, params={"range": "5y", "interval": "1d"}).json()["chart"]["result"][0]
            s = {dt.datetime.fromtimestamp(a, dt.timezone.utc).date().isoformat(): round(b, 2)
                 for a, b in zip(j["timestamp"], j["indicators"]["quote"][0]["close"]) if b}
            rows.append((t, {"name": t}, s))
        except Exception as e:
            print(f"stock {t} failed: {e}", file=sys.stderr)
    if rows:
        store("stocks", "Stocks", rows)

def daily():
    failed = []
    for fn in (daily_mtg, daily_tcg, stocks):
        try:
            fn()
        except Exception as e:
            failed.append(fn.__name__); print(f"{fn.__name__} failed: {e}", file=sys.stderr)
    if failed:
        sys.exit(1)  # the workflow still commits whatever succeeded, then shows red

if __name__ == "__main__":
    a = sys.argv[1:] or ["daily"]
    {"daily": daily, "init-mtg": init_mtg, "backfill-mtg": backfill_mtg}.get(a[0], lambda: find(*a[1:]))()
