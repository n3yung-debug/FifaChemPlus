#!/usr/bin/env python3
"""Chem Builder (EA FC 27) -- local tool. Standard library only.

  python chem_builder.py              start the app at http://127.0.0.1:8765
  python chem_builder.py --sync       refresh cards.json from FUT.GG first (then start)
  python chem_builder.py --sync-only  refresh and exit
  options: --min-rating 75  --port 8765  --no-browser

Card data comes from FUT.GG's public JSON feed (the same one its own player list uses).
It is fetched politely (one request every ~0.4 s) and cached in cards.json next to this file.
"""
import argparse
import json
import os
import re
import socket
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chem_engine as eng

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cards.json")
UI = os.path.join(HERE, "ui.html")
API = "https://www.fut.gg/api/fut/players/v2/27/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
PSEUDO_CLUBS = {"ICON", "HERO", "HALL OF FUT"}

STATE = {"cards": [], "meta": {}, "by_slug": {}, "sync": {"running": False, "msg": "", "done": 0, "total": 0}}


# ------------------------------------------------------------------ data

def fold(s):
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch)).lower()


def normalize_card(r):
    uc = r.get("uniqueClub") or {}
    club = r.get("club") or None
    club_name = (club or {}).get("name") or ""
    pseudo = bool(uc.get("isIconClub")) or club_name in PSEUDO_CLUBS or uc.get("name") in PSEUDO_CLUBS
    ck, cn = None, None
    if club and not pseudo:
        ids = [x for x in (uc.get("eaId"), uc.get("siblingClubEaId"), uc.get("sisterClubEaId")) if x]
        ck = str(min(ids)) if ids else str(club.get("eaId"))
        cn = club_name
    rarity = r.get("rarityName") or ""
    ty = "icon" if r.get("isIcon") else "hero" if r.get("isHero") else \
        "hof" if ("Hall of FUT" in rarity or club_name == "HALL OF FUT") else ""
    nat, lg = r.get("nation") or {}, r.get("league") or {}
    return {
        "s": r["slug"], "n": r.get("cardName") or r.get("commonName") or r.get("lastName"),
        "fn": " ".join(x for x in (r.get("firstName"), r.get("lastName"), r.get("nickname")) if x),
        "ov": r["overall"], "rt": rarity, "g": r.get("gender") or 1,
        "p": r.get("position"), "a": list(r.get("alternativePositions") or []),
        "ni": nat.get("eaId"), "nn": nat.get("name"), "li": lg.get("eaId"), "ln": lg.get("name"),
        "ck": ck, "cn": cn, "ty": ty, "bp": r.get("basePlayerEaId") or r.get("eaId"),
        "gg": r.get("playerScore") or None,  # FUT.GG score; display only, never used for ranking (empty in FC 27 feed so far)
        "fc": bool(r.get("isFullChemistry")),
        "xc": int(r.get("extraClubChemistry") or 0), "xl": int(r.get("extraLeagueChemistry") or 0),
        "xn": int(r.get("extraNationChemistry") or 0),
        "xsl": bool(r.get("extraSquadLeagueChemistry")), "xsn": bool(r.get("extraSquadNationChemistry")),
    }


def explain_error(e):
    """Turn a urllib/ssl/socket exception into something that names the actual cause."""
    import ssl
    if isinstance(e, urllib.error.HTTPError):
        hint = {403: "blocked by FUT.GG or a firewall", 429: "rate limited - wait a minute and retry",
                404: "endpoint not found (FUT.GG may have changed its feed)"}.get(e.code, "")
        return f"HTTP {e.code} {e.reason}" + (f" - {hint}" if hint else "")
    r = getattr(e, "reason", e)
    if isinstance(r, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(r):
        return "TLS certificate check failed - a firewall/antivirus doing HTTPS inspection is the usual cause (" + str(r) + ")"
    if isinstance(r, socket.gaierror):
        return "DNS lookup failed - no internet, DNS filter, or fut.gg blocked (" + str(r) + ")"
    if isinstance(r, (socket.timeout, TimeoutError)):
        return "timed out - network or firewall dropping the connection"
    return f"{type(r).__name__}: {r}"


def fetch_json(url, tries=4):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                break  # 403/404 will not fix themselves on retry
            time.sleep(3 * (k + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"{explain_error(last)}  [{url}]")


def diagnose():
    """Step-by-step connection test shown by the app and by --check."""
    steps = []
    steps.append({"step": "cards.json", "ok": bool(STATE["cards"]),
                  "detail": f"{CACHE} - {len(STATE['cards'])} cards loaded" if STATE["cards"] else f"not found or empty at {CACHE}"})
    try:
        socket.getaddrinfo("www.fut.gg", 443)
        steps.append({"step": "DNS www.fut.gg", "ok": True, "detail": "resolved"})
    except Exception as e:  # noqa: BLE001
        steps.append({"step": "DNS www.fut.gg", "ok": False, "detail": explain_error(e)})
        return steps
    try:
        t = time.time()
        d = fetch_json(f"{API}?page=1&overall__gte=90", tries=1)
        steps.append({"step": "FUT.GG player feed", "ok": True,
                      "detail": f"{len(d.get('data', []))} cards in {time.time() - t:.1f}s (feed total {d.get('total')})"})
    except Exception as e:  # noqa: BLE001
        steps.append({"step": "FUT.GG player feed", "ok": False, "detail": str(e)})
    try:
        p, known = extract_price(fetch_json(PRICE_API.format(ea="37576"), tries=1))
        steps.append({"step": "FUT.GG price lookup (budget filter)", "ok": known,
                      "detail": f"works ({p if p is not None else 'no listing'})" if known else
                      "responded but format not recognised - budget will use your pasted prices only"})
    except Exception as e:  # noqa: BLE001
        steps.append({"step": "FUT.GG price lookup (budget filter)", "ok": False,
                      "detail": str(e) + " -> budget will use your pasted prices only"})
    return steps


def sync_cards(min_rating=75, status=None):
    status = status if status is not None else STATE["sync"]
    status.update(running=True, msg="starting", done=0, total=0)
    cards, page = [], 1
    try:
        while True:
            d = fetch_json(f"{API}?page={page}&overall__gte={min_rating}")
            for r in d.get("data", []):
                try:
                    cards.append(normalize_card(r))
                except Exception:  # noqa: BLE001
                    continue
            status.update(done=len(cards), total=d.get("total", 0), msg=f"page {page}")
            if not d.get("next"):
                break
            page += 1
            time.sleep(0.4)
        seen, uniq = set(), []
        for c in cards:
            if c["s"] not in seen:
                seen.add(c["s"])
                uniq.append(c)
        meta = {"synced_at": time.strftime("%Y-%m-%d %H:%M:%S"), "min_rating": min_rating,
                "source": "fut.gg", "game": "FC 27", "count": len(uniq)}
        tmp = CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"meta": meta, "cards": uniq}, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, CACHE)
        load_cache()
        status.update(running=False, msg=f"done: {len(uniq)} cards")
    except Exception as e:  # noqa: BLE001
        status.update(running=False, msg=f"failed: {e}")


def load_cache():
    if not os.path.exists(CACHE):
        STATE.update(cards=[], meta={}, by_slug={})
        return
    with open(CACHE, encoding="utf-8") as f:
        d = json.load(f)
    cards = d["cards"]
    for c in cards:
        c["_k"] = fold(c.get("fn") or c["n"]) + " " + fold(c["n"])
    STATE.update(cards=cards, meta=d.get("meta", {}), by_slug={c["s"]: c for c in cards})


def public(c):
    return {k: v for k, v in c.items() if k != "_k"}


def meta_lists():
    nations, leagues, clubs = {}, {}, {}
    for c in STATE["cards"]:
        if c["ni"] is not None:
            nations[c["ni"]] = c["nn"]
        if c["li"] is not None:
            leagues[c["li"]] = c["ln"]
        if c.get("ck"):
            clubs[c["ck"]] = c["cn"]
    srt = lambda m: sorted(([k, v] for k, v in m.items()), key=lambda kv: fold(kv[1]))  # noqa: E731
    return {"nations": srt(nations), "leagues": srt(leagues), "clubs": srt(clubs)}


# ------------------------------------------------------------------ search / pool

def search_cards(q, live=False, limit=40):
    """Returns {"hits": [...], "live_error": str|None}."""
    toks = fold(q).split()
    if not toks:
        return {"hits": [], "live_error": None}
    live_error = None
    hits = [c for c in STATE["cards"] if all(t in c["_k"] for t in toks)]
    hits.sort(key=lambda c: -c["ov"])
    out = [public(c) for c in hits[:limit]]
    if live and len(out) < limit:
        try:
            d = fetch_json(f"{API}?name={urllib.parse.quote(q)}", tries=2)
            have = {c["s"] for c in out}
            for r in d.get("data", []):
                c = normalize_card(r)
                if c["s"] not in have:
                    c["live"] = True
                    out.append(c)
        except Exception as e:  # noqa: BLE001
            live_error = str(e)
    return {"hits": out[:limit], "live_error": live_error}


POS_TOKENS = {"GK", "LB", "LWB", "CB", "RB", "RWB", "CDM", "CM", "CAM", "LM", "RM", "LW", "RW", "CF", "ST"}
MONEYISH = re.compile(r"^[\d.,]+[kKmM]?$")


def parse_line(line):
    """Pull (position, name, rating) out of a pasted line. Tolerant of tabs, numbering, prices.
    Works for 'ST Mbappe 91', 'Mbappe 91 ST', 'Mbappe', and copied table rows."""
    s = re.sub(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+", "", line.strip())
    if not s:
        return None
    cols = [c.strip() for c in re.split(r"\t|\s{2,}|\|", s) if c.strip()]
    if len(cols) == 1:
        cols = s.split()
        single = True
    else:
        single = False
    pos, rating, name_cols = None, None, []
    for c in cols:
        if c.upper() in POS_TOKENS and pos is None:
            pos = c.upper()
        elif c.isdigit() and 40 <= int(c) <= 99 and rating is None:
            rating = int(c)
        elif MONEYISH.match(c) or c.upper() in POS_TOKENS:
            continue
        else:
            name_cols.append(c)
    if not name_cols:
        return None
    if single:
        name = " ".join(name_cols)
    else:
        name = name_cols[0]
    return {"pos": pos, "name": name, "rating": rating, "raw": line.strip()}


def find_cards(name, rating=None):
    toks = fold(name).split()
    if not toks:
        return []
    hits = [c for c in STATE["cards"] if all(t in c["_k"] for t in toks)]
    if rating is not None:
        exact = [c for c in hits if c["ov"] == rating]
        hits = exact or hits
    return hits


# ------------------------------------------------------------------ prices (budget filter)
# FUT.GG's card feed has no prices. Live lookup uses FUT.GG's per-player price endpoint; the path and response
# shape are NOT verified (Cloudflare blocked the test sandbox with 403) - PENDING VALIDATION from a real PC.
# Manual prices ("name price" lines) always work and take priority over live lookups.
PRICE_API = "https://www.fut.gg/api/fut/player-prices/27/{ea}/"
PRICE_TTL = 3600
LIVE_LOOKUP_CAP = 80          # max live lookups per optimize run
LIVE_PRICES = {}              # eaId -> (price|None, fetched_at)


def card_ea_id(card):
    return card["s"].split("-", 1)[-1]


def to_coins(tok):
    m = re.fullmatch(r"(\d[\d,]*(?:\.\d+)?)([kKmM]?)", tok.strip())
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    mult = {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()]
    if not m.group(2) and "." in m.group(1):
        return None  # "12.5" without a suffix is not a coin amount
    return int(round(num * mult))


def parse_price_line(line):
    """'Mbappe 91 12,500' / 'Cafu 85 8.5k' / 'ST Rodri  90  1200' -> {name, rating, pos, price} or None."""
    s = re.sub(r"^\s*(?:[-*\u2022]|\d{1,2}[.)])\s+", "", line.strip())
    toks = [t for t in re.split(r"\t|\s{2,}|\||\s", s) if t]
    price, idx = None, None
    for i in range(len(toks) - 1, -1, -1):
        v = to_coins(toks[i])
        if v is None or toks[i].upper() in POS_TOKENS:
            continue
        has_suffix = toks[i][-1] in "kKmM" or "," in toks[i]
        other_rating = any(t.isdigit() and 40 <= int(t) <= 99 for j, t in enumerate(toks) if j != i)
        if has_suffix or v >= 100 or other_rating:
            price, idx = v, i
            break
    if price is None:
        return None
    rest = " ".join(t for j, t in enumerate(toks) if j != idx)
    p = parse_line(rest)
    if not p:
        return None
    return {"name": p["name"], "rating": p["rating"], "pos": p["pos"], "price": price}


def manual_prices(text):
    """Returns ({slug: price}, [unmatched lines])."""
    out, bad = {}, []
    for ln in [x for x in (text or "").splitlines() if x.strip()]:
        p = parse_price_line(ln)
        if not p:
            bad.append(ln.strip())
            continue
        hits = find_cards(p["name"], p["rating"])
        if not hits:
            bad.append(ln.strip())
        for c in hits:
            out[c["s"]] = p["price"]
    return out, bad


def extract_price(d):
    """Pull a coin price out of the price endpoint response. Returns (price|None, recognised_shape)."""
    data = d.get("data", d) if isinstance(d, dict) else None
    if not isinstance(data, dict):
        return None, False
    cp = data.get("currentPrice")
    if isinstance(cp, dict):
        if cp.get("isExtinct") or cp.get("price") in (None, 0):
            return None, True
        return int(cp["price"]), True
    if isinstance(data.get("price"), (int, float)):
        return int(data["price"]), True
    return None, False


class Budget:
    def __init__(self, cap, manual, include_unknown=False, live=True):
        self.cap, self.manual, self.include_unknown, self.live = cap, manual, include_unknown, live
        self.seen = {}          # slug -> price|None
        self.lookups = 0
        self.live_error = None
        self.blocked = False
        self.capped = False
        self.over = set()
        self.unknown = set()
        self._last = 0.0

    def price(self, card):
        s = card["s"]
        if s in self.seen:
            return self.seen[s]
        p = self.manual.get(s)
        if p is None and self.live and not self.blocked:
            p = self._live(card)
        self.seen[s] = p
        return p

    def _live(self, card):
        ea = card_ea_id(card)
        hit = LIVE_PRICES.get(ea)
        if hit and time.time() - hit[1] < PRICE_TTL:
            return hit[0]
        if self.lookups >= LIVE_LOOKUP_CAP:
            self.capped = True
            return None
        wait = 0.25 - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        self.lookups += 1
        try:
            d = fetch_json(PRICE_API.format(ea=ea), tries=1)
            p, known = extract_price(d)
            if not known:
                raise RuntimeError("price response not recognised (top-level keys: %s)" %
                                   ", ".join(list(d)[:6] if isinstance(d, dict) else [type(d).__name__]))
        except Exception as e:  # noqa: BLE001
            self.live_error = str(e)
            self.blocked = True  # stop hammering a blocked / changed endpoint for the rest of this run
            return None
        LIVE_PRICES[ea] = (p, time.time())
        return p

    def ok(self, card):
        p = self.price(card)
        if p is None:
            if self.include_unknown:
                return True
            self.unknown.add(card["s"])
            return False
        if p > self.cap:
            self.over.add(card["s"])
            return False
        return True

    def report(self):
        return {"cap": self.cap, "lookups": self.lookups, "over": len(self.over), "unknown": len(self.unknown),
                "live_error": self.live_error, "capped": self.capped,
                "prices": {k: v for k, v in self.seen.items() if v is not None}}



def build_pool(opts):
    gender = int(opts.get("gender") or 0)
    excl = set(opts.get("exclude_types") or [])
    pool = [c for c in STATE["cards"] if (not gender or c["g"] == gender) and c["ty"] not in excl]
    unmatched = []
    lines = [ln for ln in (opts.get("club_list") or "").splitlines() if ln.strip()]
    if lines:
        chosen = {}
        for ln in lines:
            slug_hit = STATE["by_slug"].get(ln.strip())
            if slug_hit:
                chosen[slug_hit["s"]] = slug_hit
                continue
            p = parse_line(ln)
            found = find_cards(p["name"], p["rating"]) if p else []
            if not found:
                unmatched.append(ln.strip())
            for c in found:
                chosen[c["s"]] = c
        pool = [c for c in chosen.values() if (not gender or c["g"] == gender) and c["ty"] not in excl]
    return pool, unmatched


def import_squad(text, slots):
    """Turn pasted lines into a squad for the given slot positions."""
    squad = [None] * len(slots)
    notes, unmatched = [], []
    for ln in [x for x in text.splitlines() if x.strip()]:
        p = parse_line(ln)
        if not p:
            continue
        hits = find_cards(p["name"], p["rating"])
        if not hits:
            unmatched.append(ln.strip())
            continue
        free = [i for i, c in enumerate(squad) if c is None]
        if not free:
            notes.append(f"More than {len(slots)} players pasted; ignored: {ln.strip()}")
            continue

        def fits(c, i):
            return slots[i] in {c["p"], *c["a"]}
        want = p["pos"]
        # candidates ordered: playable in the requested/free slots first, then higher rating
        hits.sort(key=lambda c: (-(any(fits(c, i) for i in free)), -c["ov"]))
        card = hits[0]
        if want:
            target = next((i for i in free if slots[i] == want), None)
            if target is not None:
                alt = [c for c in hits if fits(c, target)]
                card = alt[0] if alt else card
        else:
            target = None
        if target is None:
            target = next((i for i in free if fits(card, i)), None)
        if target is None:
            target = free[0]
            notes.append(f"{card['n']} can't play {slots[target]} (preferred: {card['p']}); placed there off-position.")
        squad[target] = card
        if len(hits) > 1 and p["rating"] is None:
            notes.append(f"{p['name']}: {len(hits)} versions found, used the best fit ({card['ov']} {card['rt']}). Add the rating to pick another.")
    return {"squad": [public(c) if c else None for c in squad], "notes": notes, "unmatched": unmatched}


# ------------------------------------------------------------------ http

class Handler(BaseHTTPRequestHandler):
    server_version = "ChemBuilder/1.0"

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            with open(UI, "rb") as f:
                return self._send(200, f.read(), "text/html")
        if u.path == "/api/meta":
            return self._send(200, {"meta": STATE["meta"], "n": len(STATE["cards"]), **meta_lists()})
        if u.path == "/api/search":
            q = (qs.get("q") or [""])[0]
            return self._send(200, search_cards(q, live=(qs.get("live") or ["0"])[0] == "1"))
        if u.path == "/api/diag":
            return self._send(200, diagnose())
        if u.path == "/api/sync_status":
            return self._send(200, STATE["sync"])
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = self._body()
            if self.path == "/api/evaluate":
                return self._send(200, eng.evaluate(body["slots"], body["squad"], body.get("mgr")))
            if self.path == "/api/optimize":
                return self._send(200, self.optimize(body))
            if self.path == "/api/import_squad":
                return self._send(200, import_squad(body.get("text", ""), body["slots"]))
            if self.path == "/api/sync":
                if STATE["sync"]["running"]:
                    return self._send(200, STATE["sync"])
                threading.Thread(target=sync_cards, args=(int(body.get("min_rating") or 75),), daemon=True).start()
                return self._send(200, {"running": True})
        except Exception as e:  # noqa: BLE001
            return self._send(400, {"error": str(e)})
        self._send(404, {"error": "not found"})

    @staticmethod
    def optimize(b):
        slots, squad, locks, mgr = b["slots"], b["squad"], b["locks"], b.get("mgr")
        if any(c is None for c in squad):
            raise ValueError("Fill all 11 slots first.")
        o = b.get("opts", {})
        max_drop, min_rating = int(o.get("max_drop", 3)), int(o.get("min_rating", 0))
        pool, unmatched = build_pool(o)
        by_pos = eng.index_pool(pool)
        budget, bad_prices, ok = None, [], None
        cap = int(o.get("max_price") or 0)
        if cap > 0 and not (o.get("club_list") or "").strip():   # cards you own cost nothing -> no budget then
            manual, bad_prices = manual_prices(o.get("price_list"))
            budget = Budget(cap, manual, bool(o.get("include_unknown")), live=o.get("live_prices", True))
            ok = budget.ok
        base, singles, allr = eng.top_singles(slots, squad, locks, mgr, by_pos, max_drop, min_rating, n=30, ok=ok)
        pairs = []
        if o.get("pairs", True):
            pairs = eng.synergy_pairs(slots, squad, locks, mgr, by_pos, allr, base, max_drop, min_rating, n=15, ok=ok)
        chain, chain_total, final = eng.plan_chain(slots, squad, locks, mgr, by_pos, max_drop, min_rating,
                                                   max_steps=int(o.get("max_steps", 5)), ok=ok)
        return {"budget": budget.report() if budget else None, "bad_prices": bad_prices,"base": base, "singles": singles, "pairs": pairs, "chain": chain,
                "chain_total": chain_total, "pool": len(pool), "unmatched": unmatched,
                "mgr_now": {"li": eng.evaluate(slots, squad, mgr)["mgr_li"],
                            **eng.manager_options(slots, squad, mgr)},
                "mgr_after": {"li": eng.evaluate(slots, final, mgr)["mgr_li"],
                              **eng.manager_options(slots, final, mgr)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="test cards.json and the FUT.GG connection, then exit")
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--sync-only", action="store_true")
    ap.add_argument("--min-rating", type=int, default=75)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if a.check:
        load_cache()
        for st_ in diagnose():
            print(("OK   " if st_["ok"] else "FAIL ") + st_["step"] + ": " + st_["detail"])
        return
    if a.sync or a.sync_only or not os.path.exists(CACHE):
        print(f"Syncing FC 27 cards (rating >= {a.min_rating}) from FUT.GG ...")
        st = {}
        t = threading.Thread(target=sync_cards, args=(a.min_rating, st), daemon=True)
        t.start()
        while t.is_alive():
            time.sleep(2)
            print(f"  {st.get('done', 0)}/{st.get('total', '?')} {st.get('msg', '')}", flush=True)
        print(st.get("msg"))
        if not os.path.exists(CACHE):
            sys.exit("Sync failed and there is no cards.json. Run: python chem_builder.py --check")
        if a.sync_only:
            return
    load_cache()
    if not STATE["cards"]:
        sys.exit("No card data. Run: python chem_builder.py --sync")
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"{len(STATE['cards'])} cards loaded (synced {STATE['meta'].get('synced_at', '?')}). Open {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
