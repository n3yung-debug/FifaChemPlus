"""Chemistry rules + swap search for EA FC 27 Ultimate Team.

Pure Python, standard library only. Card format (compact dict) -- see normalize_card
in chem_builder.py:
  s  slug (unique per card version)      n  display name        ov  overall
  p  main position                       a  alternate positions g   gender (1 men, 2 women)
  ni nation id   nn nation name          li league id   ln league name
  ck club link key (None for ICON/Hero/Hall of FUT)            cn  club name
  ty 'icon' | 'hero' | 'hof' | ''        bp base player id (same player, different version)
  fc full-chemistry card                 xc/xl/xn extra club/league/nation count
  xsl/xsn extra +1 to every league / every nation in the squad

RULES (sources checked 8 Oct 2026, see README):
  * every starter earns 0-3 chem, squad max 33
  * thresholds (counts include the player): club 2/4/7, league 3/5/8, nation 2/5/8
  * the three link types add together, capped at 3
  * manager: flat +1 if manager shares the player's nation OR league (max +1)
  * the manager's LEAGUE can be changed with a League Modifier item (permanent, any league);
    there is no item for the manager's nation -> mgr = {"ni": nation id, "li": league id,
    "li_free": True} lets the engine pick the best league automatically
  * a player only earns chem and only counts for others if played in a preferred position
  * FC 27: ICON counts +1 nation and +1 to EVERY league; Hero / Hall of FUT count +1 league
    and +1 nation; ICON/Hero/Hall of FUT are full chemistry and have no club link
  * men's and women's players link through affiliated clubs (same ck), never through leagues
"""
from collections import Counter

CLUB_T = (2, 4, 7)
LEAGUE_T = (3, 5, 8)
NATION_T = (2, 5, 8)


def pts(n, thresholds):
    return sum(1 for t in thresholds if n >= t)


def prefs(card):
    return {card["p"], *card.get("a", [])}


def _counts(slots, squad):
    inpos = [c is not None and slots[i] in prefs(c) for i, c in enumerate(squad)]
    club, lg, nat = Counter(), Counter(), Counter()
    gl = gn = 0
    for ok, c in zip(inpos, squad):
        if not ok:
            continue
        if c.get("ck"):
            club[c["ck"]] += 1 + int(c.get("xc") or 0)
        lg[c["li"]] += 1 + int(c.get("xl") or 0)
        nat[c["ni"]] += 1 + int(c.get("xn") or 0)
        if c.get("ty") == "icon" or c.get("xsl"):
            gl += 1
        if c.get("xsn"):
            gn += 1
    return inpos, club, lg, nat, gl, gn


def _raw(slots, squad):
    """Per-player chemistry BEFORE the manager point. None = empty slot."""
    inpos, club, lg, nat, gl, gn = _counts(slots, squad)
    rows = []
    for i, c in enumerate(squad):
        if c is None:
            rows.append(None)
        elif not inpos[i]:
            rows.append({"state": "off", "raw": 0})
        elif c.get("fc"):
            rows.append({"state": "full", "raw": 3})
        else:
            cc = club[c["ck"]] if c.get("ck") else 0
            lc, nc = lg[c["li"]] + gl, nat[c["ni"]] + gn
            cp = pts(cc, CLUB_T) if c.get("ck") else 0
            lp, np_ = pts(lc, LEAGUE_T), pts(nc, NATION_T)
            rows.append({"state": "ok", "raw": cp + lp + np_, "club": [cc, cp], "league": [lc, lp],
                         "nation": [nc, np_]})
    return rows


def _manager(squad, rows, mgr):
    """Resolve the manager point per player. Returns (list of 0/1, league id used)."""
    mgr = mgr or {}
    ni, li = mgr.get("ni"), mgr.get("li")
    nat_hit = [bool(r and r["state"] == "ok" and ni is not None and c["ni"] == ni)
               for c, r in zip(squad, rows)]
    if mgr.get("li_free"):
        # best league = the one that lifts the most players still below 3 who the nation didn't already lift
        gain = Counter()
        for c, r, nh in zip(squad, rows, nat_hit):
            if r and r["state"] == "ok" and not nh and r["raw"] < 3:
                gain[c["li"]] += 1
        li = None
        if gain:
            best = max(gain.values())
            li = min(k for k, v in gain.items() if v == best)
    mp = []
    for c, r, nh in zip(squad, rows, nat_hit):
        hit = bool(r and r["state"] == "ok" and (nh or (li is not None and c["li"] == li)))
        mp.append(1 if hit else 0)
    return mp, li


def evaluate(slots, squad, mgr):
    """Full breakdown. squad: list of card-or-None aligned with slots."""
    rows = _raw(slots, squad)
    mp, mli = _manager(squad, rows, mgr)
    players, total = [], 0
    for r, m in zip(rows, mp):
        if r is None:
            players.append(None)
        elif r["state"] == "off":
            players.append({"chem": 0, "inpos": False, "full": False})
        elif r["state"] == "full":
            total += 3
            players.append({"chem": 3, "inpos": True, "full": True})
        else:
            chem = min(3, r["raw"] + m)
            total += chem
            players.append({"chem": chem, "inpos": True, "full": False, "club": r["club"],
                            "league": r["league"], "nation": r["nation"], "mgr": m})
    return {"total": total, "players": players, "mgr_li": mli}


def total_only(slots, squad, mgr):
    rows = _raw(slots, squad)
    mp, _ = _manager(squad, rows, mgr)
    total = 0
    for r, m in zip(rows, mp):
        if r is None or r["state"] == "off":
            continue
        total += 3 if r["state"] == "full" else min(3, r["raw"] + m)
    return total


def manager_options(slots, squad, mgr, top=8):
    """What a manager of each nation would give this squad (league still follows mgr settings).
    Nation can only change by using a different manager card; the league has an item."""
    mgr = dict(mgr or {})
    cur = total_only(slots, squad, mgr)
    nations = {}
    for c in squad:
        if c is not None:
            nations[c["ni"]] = c.get("nn")
    out = []
    for ni, nn in nations.items():
        t = total_only(slots, squad, dict(mgr, ni=ni))
        out.append({"ni": ni, "nn": nn, "total": t, "d": t - cur})
    out.sort(key=lambda r: (-r["total"], r["nn"] or ""))
    none_total = total_only(slots, squad, dict(mgr, ni=None))
    return {"current": cur, "no_nation": none_total, "options": out[:top]}


# --------------------------------------------------------------------------- search

def index_pool(pool):
    by_pos = {}
    for c in pool:
        for p in prefs(c):
            by_pos.setdefault(p, []).append(c)
    return by_pos


def _slot_candidates(i, slots, squad, by_pos, max_drop, min_rating):
    cur = squad[i]
    floor = max(min_rating, cur["ov"] - max_drop)
    others = {c["bp"] for j, c in enumerate(squad) if j != i and c}
    for cand in by_pos.get(slots[i], ()):
        if cand["ov"] < floor or cand["bp"] in others or cand["s"] == cur["s"]:
            continue
        yield cand


def single_swaps(slots, squad, locks, mgr, by_pos, max_drop=3, min_rating=0):
    base = total_only(slots, squad, mgr)
    out = []
    for i, cur in enumerate(squad):
        if locks[i] or cur is None:
            continue
        for cand in _slot_candidates(i, slots, squad, by_pos, max_drop, min_rating):
            new = list(squad)
            new[i] = cand
            t = total_only(slots, new, mgr)
            out.append({"slot": i, "out": cur, "in": cand, "total": t, "d": t - base,
                        "dr": cand["ov"] - cur["ov"]})
    return base, out


def _rank_key(r):
    return (-r["d"], -r["in"]["ov"], -r["dr"])  # most chem first, then highest overall


def top_singles(slots, squad, locks, mgr, by_pos, max_drop, min_rating, n=30, only_positive=True, ok=None):
    """ok(card) -> bool is an optional affordability check on the INCOMING card only. It is called lazily,
    walking down the ranked list, so price lookups happen only for cards that would otherwise be shown."""
    base, allr = single_swaps(slots, squad, locks, mgr, by_pos, max_drop, min_rating)
    res = [r for r in allr if (r["d"] > 0 or not only_positive)]
    res.sort(key=_rank_key)
    if ok is not None:
        keep = []
        for r in res:
            if len(keep) >= n:
                break
            if ok(r["in"]):
                keep.append(r)
        res = keep
    return base, res[:n], allr


def synergy_pairs(slots, squad, locks, mgr, by_pos, allsingles, base, max_drop, min_rating,
                  per_slot=35, n=20, ok=None):
    """Two swaps that only pay off together (each alone is worse than the pair)."""
    single_d = {(r["slot"], r["in"]["s"]): r["d"] for r in allsingles}
    mg = mgr or {}
    shortlist = {}
    for i, cur in enumerate(squad):
        if locks[i] or cur is None:
            continue
        cands = list(_slot_candidates(i, slots, squad, by_pos, max_drop, min_rating))
        leagues = Counter(c["li"] for c in squad if c)
        nations = Counter(c["ni"] for c in squad if c)
        clubs = Counter(c["ck"] for j, c in enumerate(squad) if c and c.get("ck") and j != i)

        def potential(c):
            return (leagues[c["li"]] + nations[c["ni"]] + 2 * clubs.get(c.get("ck"), 0)
                    + (0 if mg.get("li_free") else (1 if c["li"] == mg.get("li") else 0))
                    + (1 if c["ni"] == mg.get("ni") else 0)
                    + (3 if c.get("ty") == "icon" else 0))
        cands.sort(key=lambda c: (potential(c), c["ov"]), reverse=True)
        top_pot = cands[:per_slot]
        top_single = sorted(cands, key=lambda c: single_d.get((i, c["s"]), -99), reverse=True)[:per_slot // 2]
        seen, merged = set(), []
        for c in top_pot + top_single:
            if c["s"] not in seen:
                seen.add(c["s"])
                merged.append(c)
        shortlist[i] = merged
    idx = sorted(shortlist)
    out = []
    for a in range(len(idx)):
        for b in range(a + 1, len(idx)):
            i, j = idx[a], idx[b]
            for ci in shortlist[i]:
                for cj in shortlist[j]:
                    if ci["bp"] == cj["bp"]:
                        continue
                    new = list(squad)
                    new[i], new[j] = ci, cj
                    if len({c["bp"] for c in new if c}) < len([c for c in new if c]):
                        continue
                    t = total_only(slots, new, mgr)
                    d = t - base
                    if d <= 0:
                        continue
                    if d > single_d.get((i, ci["s"]), -99) and d > single_d.get((j, cj["s"]), -99):
                        out.append({"swaps": [
                            {"slot": i, "out": squad[i], "in": ci},
                            {"slot": j, "out": squad[j], "in": cj}],
                            "total": t, "d": d,
                            "dr": ci["ov"] + cj["ov"] - squad[i]["ov"] - squad[j]["ov"]})
    out.sort(key=lambda r: (-r["d"], -sum(w["in"]["ov"] for w in r["swaps"]), -r["dr"]))
    if ok is not None:
        keep = []
        for r in out:
            if len(keep) >= n:
                break
            if all(ok(w["in"]) for w in r["swaps"]):
                keep.append(r)
        out = keep
    return out[:n]


def plan_chain(slots, squad, locks, mgr, by_pos, max_drop=3, min_rating=0, max_steps=5, ok=None):
    """Greedy path: repeatedly apply the best swap (or best synergy pair)."""
    steps, cur, locks = [], list(squad), list(locks)
    total = total_only(slots, cur, mgr)
    for _ in range(max_steps):
        base, top, allr = top_singles(slots, cur, locks, mgr, by_pos, max_drop, min_rating, n=1, ok=ok)
        if top:
            best = top[0]
            cur[best["slot"]] = best["in"]
            locks[best["slot"]] = True
            total = best["total"]
            steps.append({"swaps": [{"slot": best["slot"], "out": best["out"], "in": best["in"]}],
                          "total": total})
            continue
        pairs = synergy_pairs(slots, cur, locks, mgr, by_pos, allr, base, max_drop, min_rating, n=1, ok=ok)
        if not pairs:
            break
        best = pairs[0]
        for s in best["swaps"]:
            cur[s["slot"]] = s["in"]
            locks[s["slot"]] = True
        total = best["total"]
        steps.append({"swaps": best["swaps"], "total": total})
    return steps, total, cur
