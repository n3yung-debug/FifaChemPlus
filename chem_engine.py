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
  * manager: counts as one more member of its nation and of its league toward those thresholds
    (it lifts a player only when that crosses a threshold). Guides describe a flat "+1 if nation or
    league matches", but a real FC 27 squad (8 Oct 2026) only adds up under the threshold rule: a
    Spain/Arkema player with Spain 4->5 and Arkema 2->3 showed 3 chem in game, the flat rule gives 2.
  * the manager's LEAGUE can be changed with a League Modifier item (permanent, any league);
    there is no item for the manager's nation -> mgr = {"ni": nation id, "li": league id,
    "li_free": True} lets the engine pick the best league automatically
  * a player only earns chem and only counts for others if played in a preferred position
  * FC 27: ICON counts +1 nation and +1 to EVERY league; Hero / Hall of FUT count +1 league
    and +1 nation; ICON/Hero/Hall of FUT are full chemistry and have no club link
  * men's and women's players link through affiliated clubs (same ck), never through leagues
"""
import time
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


def _raw(slots, squad, mni=None, mli=None):
    """Per-player chemistry; mni/mli = manager nation/league, each counted as one more member of that
    nation/league toward the thresholds. None = empty slot."""
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
            lc = lg[c["li"]] + gl + (1 if mli is not None and c["li"] == mli else 0)
            nc = nat[c["ni"]] + gn + (1 if mni is not None and c["ni"] == mni else 0)
            cp = pts(cc, CLUB_T) if c.get("ck") else 0
            lp, np_ = pts(lc, LEAGUE_T), pts(nc, NATION_T)
            rows.append({"state": "ok", "raw": min(3, cp + lp + np_), "club": [cc, cp], "league": [lc, lp],
                         "nation": [nc, np_]})
    return rows


def _choose_league(gain, cur):
    """League Modifier choice: the league adding the most chemistry. Keeps the current league when it is
    as good as any other (no item needed); otherwise ties go to the lowest league id."""
    best = max(gain.values(), default=0)
    if cur is not None and gain.get(cur, 0) >= best:
        return cur
    return min(k for k, v in gain.items() if v == best) if best > 0 else cur


def _best_league(squad, rows, cur=None):
    """rows computed without a manager league."""
    gain = Counter()
    for c, r in zip(squad, rows):
        if r and r["state"] == "ok" and r["raw"] < 3:
            up = min(3, r["club"][1] + pts(r["league"][0] + 1, LEAGUE_T) + r["nation"][1])
            gain[c["li"]] += up - r["raw"]
    return _choose_league(gain, cur)


def _manager_rows(slots, squad, mgr):
    """Rows with the manager applied. Returns (rows, manager league used)."""
    mgr = mgr or {}
    ni, li = mgr.get("ni"), mgr.get("li")
    if mgr.get("li_free"):
        li = _best_league(squad, _raw(slots, squad, ni, None), li)
    return _raw(slots, squad, ni, li), li


def evaluate(slots, squad, mgr):
    """Full breakdown. squad: list of card-or-None aligned with slots."""
    rows, mli = _manager_rows(slots, squad, mgr)
    bare = _raw(slots, squad)
    players, total = [], 0
    for r, r0 in zip(rows, bare):
        if r is None:
            players.append(None)
        elif r["state"] == "off":
            players.append({"chem": 0, "inpos": False, "full": False})
        elif r["state"] == "full":
            total += 3
            players.append({"chem": 3, "inpos": True, "full": True})
        else:
            total += r["raw"]
            players.append({"chem": r["raw"], "inpos": True, "full": False, "club": r["club"],
                            "league": r["league"], "nation": r["nation"], "mgr": r["raw"] - r0["raw"]})
    return {"total": total, "players": players, "mgr_li": mli}


_CP = [pts(n, CLUB_T) for n in range(64)]
_LP = [pts(n, LEAGUE_T) for n in range(64)]
_NP = [pts(n, NATION_T) for n in range(64)]


def _t(c):
    """Compact read-only view of a card for the search hot path."""
    if c is None:
        return None
    return (c["p"], frozenset(c.get("a") or ()), c.get("ck") or None, c["li"], c["ni"], c.get("xc") or 0,
            c.get("xl") or 0, c.get("xn") or 0, c.get("ty") == "icon" or bool(c.get("xsl")), bool(c.get("xsn")),
            bool(c.get("fc")))


def _ttotal(slots, ts, mni, mli, free):
    """Squad chemistry from _t() tuples. Same rules as evaluate(); the manager league is folded in as a
    per-league gain so a free league (League Modifier) costs nothing extra."""
    club, lg, nat = {}, {}, {}
    gl = gn = 0
    live = []
    for i, t in enumerate(ts):
        if t is None:
            continue
        pos = slots[i]
        if pos != t[0] and pos not in t[1]:
            continue
        live.append(t)
        if t[2]:
            club[t[2]] = club.get(t[2], 0) + 1 + t[5]
        lg[t[3]] = lg.get(t[3], 0) + 1 + t[6]
        nat[t[4]] = nat.get(t[4], 0) + 1 + t[7]
        if t[8]:
            gl += 1
        if t[9]:
            gn += 1
    total, gain = 0, {}
    for t in live:
        if t[10]:
            total += 3
            continue
        base = (_CP[club[t[2]]] if t[2] else 0) + _NP[nat[t[4]] + gn + (1 if t[4] == mni and mni is not None else 0)]
        lc = lg[t[3]] + gl
        r0 = base + _LP[lc]
        if r0 >= 3:
            total += 3
            continue
        total += r0
        r1 = base + _LP[lc + 1]
        up = (3 if r1 > 3 else r1) - r0
        if up:
            gain[t[3]] = gain.get(t[3], 0) + up
    li = _choose_league(gain, mli) if free else mli
    return total + (gain.get(li, 0) if li is not None else 0)


def total_only(slots, squad, mgr):
    """Squad chemistry only (the search hot path)."""
    mgr = mgr or {}
    return _ttotal(slots, [_t(c) for c in squad], mgr.get("ni"), mgr.get("li"), mgr.get("li_free"))


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


def manager_suggestions(slots, squad, mgr, top=6):
    """Manager changes that raise squad chemistry, measured against the current manager as it is:
    a League Modifier (another league), a manager of another nation (new manager card), or both.
    Only nations/leagues already in the squad can help."""
    mgr = dict(mgr or {})
    cur_ni, cur_li = mgr.get("ni"), mgr.get("li")
    cur = total_only(slots, squad, {"ni": cur_ni, "li": cur_li})
    nations = {c["ni"]: c.get("nn") for c in squad if c is not None}
    leagues = {c["li"]: c.get("ln") for c in squad if c is not None}
    out = []
    for ni in set(nations) | {cur_ni}:
        for li in set(leagues) | {cur_li}:
            if ni is None and li is None:
                continue
            t = total_only(slots, squad, {"ni": ni, "li": li})
            if t <= cur:
                continue
            out.append({"ni": ni, "nn": nations.get(ni), "li": li, "ln": leagues.get(li), "total": t, "d": t - cur,
                        "nation": ni != cur_ni, "league": li != cur_li})
    # drop options a simpler change already matches (e.g. new nation + new league = new nation alone)
    def simpler(o, p):
        return (p["nation"] <= o["nation"] and p["league"] <= o["league"] and (p["nation"], p["league"]) != (o["nation"], o["league"])
                and (not p["nation"] or p["ni"] == o["ni"]) and (not p["league"] or p["li"] == o["li"]))
    out = [o for o in out if not any(simpler(o, p) and p["total"] >= o["total"] for p in out)]
    # most chemistry first; on a tie the cheaper change (league item only < new manager < both)
    key = lambda o: (-o["total"], o["nation"] * 2 + o["league"], str(o["nn"]), str(o["ln"]))  # noqa: E731
    out.sort(key=key)
    # always show the best of each kind (league item only / new manager only / both), then the rest
    firsts = [next(o for o in out if (o["nation"], o["league"]) == k) for k in ((False, True), (True, False), (True, True))
              if any((o["nation"], o["league"]) == k for o in out)]
    rest = [o for o in out if all(o is not f for f in firsts)]
    return sorted(firsts + rest[:max(0, top - len(firsts))], key=key)


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
    mgr = mgr or {}
    mni, mli, free = mgr.get("ni"), mgr.get("li"), mgr.get("li_free")
    ts = [_t(c) for c in squad]
    base = _ttotal(slots, ts, mni, mli, free)
    out = []
    for i, cur in enumerate(squad):
        if locks[i] or cur is None:
            continue
        keep = ts[i]
        for cand in _slot_candidates(i, slots, squad, by_pos, max_drop, min_rating):
            ts[i] = _t(cand)
            t = _ttotal(slots, ts, mni, mli, free)
            out.append({"slot": i, "out": cur, "in": cand, "total": t, "d": t - base,
                        "dr": cand["ov"] - cur["ov"]})
        ts[i] = keep
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
    t0 = [_t(c) for c in squad]
    ts = list(t0)
    tc = {c["s"]: _t(c) for lst in shortlist.values() for c in lst}
    out = []
    for a in range(len(idx)):
        for b in range(a + 1, len(idx)):
            i, j = idx[a], idx[b]
            excl = {c["bp"] for k, c in enumerate(squad) if c and k not in (i, j)}
            for ci in shortlist[i]:
                for cj in shortlist[j]:
                    if ci["bp"] == cj["bp"]:
                        continue
                    if ci["bp"] in excl or cj["bp"] in excl:
                        continue
                    ts[i], ts[j] = tc[ci["s"]], tc[cj["s"]]
                    t = _ttotal(slots, ts, mg.get("ni"), mg.get("li"), mg.get("li_free"))
                    ts[i], ts[j] = t0[i], t0[j]
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


def _shortlist(slots, squad, locks, mgr, by_pos, max_drop, min_rating, allsingles, per_slot, ok=None):
    """Per unlocked slot: the best single swaps plus the cards with the most link potential
    (same club/league/nation as the rest of the squad, manager, ICONs)."""
    single_d = {(r["slot"], r["in"]["s"]): r["d"] for r in allsingles}
    mg = mgr or {}
    leagues = Counter(c["li"] for c in squad if c)
    nations = Counter(c["ni"] for c in squad if c)
    out = {}
    for i, cur in enumerate(squad):
        if locks[i] or cur is None:
            continue
        clubs = Counter(c["ck"] for j, c in enumerate(squad) if c and c.get("ck") and j != i)
        cands = [c for c in _slot_candidates(i, slots, squad, by_pos, max_drop, min_rating)]

        def potential(c):
            return (leagues[c["li"]] + nations[c["ni"]] + 2 * clubs.get(c.get("ck"), 0)
                    + (0 if mg.get("li_free") else (1 if c["li"] == mg.get("li") else 0))
                    + (1 if c["ni"] == mg.get("ni") else 0) + (3 if c.get("ty") == "icon" else 0))
        by_pot = sorted(cands, key=lambda c: (potential(c), c["ov"]), reverse=True)
        by_single = sorted(cands, key=lambda c: (single_d.get((i, c["s"]), -99), c["ov"]), reverse=True)
        seen, merged = set(), []
        for c in by_single[:per_slot] + by_pot[:per_slot]:
            if c["s"] not in seen and (ok is None or ok(c)):
                seen.add(c["s"])
                merged.append(c)
        out[i] = merged
    return out


def k_swap_combos(slots, squad, locks, mgr, by_pos, max_drop=3, min_rating=0, k_max=3, n=25,
                  beam=24, per_slot=15, ok=None, mgr_change=False, base=None, time_limit=8.0):
    """Best squads reachable with exactly 1..k_max player swaps (beam search over a per-slot shortlist).
    The manager league is always free (League Modifier); each result says which league it uses.
    mgr_change=True also lets the search switch the manager's nation (a new manager card): every candidate
    nation gets its own seed and keeps a few states in the beam, so changes that only pay off after some
    swaps survive. Every swap in a listed combo is needed (undoing any one loses chemistry), and other
    versions of the same players are collapsed. Stops expanding after time_limit seconds.
    Returns {"by_k": {k: [ {swaps, total, d, dr, li, league, mgr} ]}, "timed_out": bool}."""
    started = time.time()
    mgr = dict(mgr or {}, li_free=True)
    cur_li = mgr.get("li")
    if base is None:
        base = total_only(slots, squad, dict(mgr, li_free=False))
    _, allr = single_swaps(slots, squad, locks, mgr, by_pos, max_drop, min_rating)
    sl = _shortlist(slots, squad, locks, mgr, by_pos, max_drop, min_rating, allr, per_slot, ok)
    configs = [mgr]
    if mgr_change:
        seen_n = Counter(c["ni"] for c in squad if c)
        for cands in sl.values():
            seen_n.update(c["ni"] for c in cands)
        configs += [dict(mgr, ni=ni) for ni, _ in seen_n.most_common() if ni != mgr.get("ni")][:12]
    nations = {}
    for c in squad:
        if c:
            nations[c["ni"]] = c.get("nn")
    for cands in sl.values():
        for c in cands:
            nations.setdefault(c["ni"], c.get("nn"))
    tc = {c["s"]: _t(c) for cands in sl.values() for c in cands}
    t0 = [_t(c) for c in squad]
    cfg = [(m.get("ni"), m.get("li")) for m in configs]
    best = {}  # (k, swap key, config) -> (total, squad)
    frontier = [((), list(squad), t0, ci) for ci in range(len(configs))]
    timed_out = False
    for k in range(1, k_max + 1):
        if time.time() - started > time_limit:
            timed_out = True
            break
        nxt = {}
        for swaps, sq, ts, ci in frontier:
            used = {s for s, _ in swaps}
            mni, mli = cfg[ci]
            for i, cands in sl.items():
                if i in used:
                    continue
                bps = {c["bp"] for j, c in enumerate(sq) if c and j != i}
                for c in cands:
                    if c["bp"] in bps:
                        continue
                    key = tuple(sorted(swaps + ((i, c["s"]),)))
                    if (key, ci) in nxt:
                        continue
                    nts = list(ts)
                    nts[i] = tc[c["s"]]
                    nxt[(key, ci)] = (_ttotal(slots, nts, mni, mli, True), sq, nts, i, c)
        ranked = sorted(nxt.items(), key=lambda kv: (-kv[1][0], kv[0][1] != 0, -kv[1][4]["ov"]))
        materialise = {}

        def squad_of(entry):
            _, sq, _, i, c = entry
            new = list(sq)
            new[i] = c
            return new
        for (key, ci), entry in ranked:
            if entry[0] <= base or len(materialise) >= 6 * n:
                break
            materialise[(key, ci)] = squad_of(entry)
            best[(k, key, ci)] = (entry[0], materialise[(key, ci)], entry[2])
        keep, per_cfg = [], Counter()
        for (key, ci), entry in ranked:
            if len(keep) < beam or per_cfg[ci] < 3:
                sq = materialise.get((key, ci)) or squad_of(entry)
                keep.append((key, sq, entry[2], ci))
                per_cfg[ci] += 1
            elif len(keep) >= beam + 3 * len(configs):
                break
        frontier = keep
    out = {k: [] for k in range(1, k_max + 1)}
    order = sorted(best.items(), key=lambda kv: (kv[0][0], -kv[1][0], kv[0][2] != 0, -sum(c["ov"] for c in kv[1][1] if c)))
    seen = set()
    for (k, key, ci), (t, sq, ts) in order:
        if len(out[k]) >= n:
            continue
        players = (k, tuple(sorted((s, sq[s]["bp"]) for s, _ in key)))
        if players in seen:  # same players (other card versions / other manager): keep the best-ranked one
            continue
        m = configs[ci]
        needed = True
        for slot, _ in key:
            back = list(ts)
            back[slot] = t0[slot]
            if _ttotal(slots, back, cfg[ci][0], cfg[ci][1], True) >= t:
                needed = False
                break
        if not needed:
            continue
        seen.add(players)
        _, li = _manager_rows(slots, sq, m)
        swaps = [{"slot": s, "out": squad[s], "in": sq[s]} for s, _ in key]
        out[k].append({"swaps": swaps, "total": t, "d": t - base,
                       "dr": sum(w["in"]["ov"] - w["out"]["ov"] for w in swaps),
                       "li": li, "league": li != cur_li,
                       "mgr": None if ci == 0 else {"ni": m["ni"], "nn": nations.get(m["ni"]), "nation": True}})
    return {"by_k": out, "timed_out": timed_out}
