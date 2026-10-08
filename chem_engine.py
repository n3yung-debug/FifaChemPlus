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


def _best_league(squad, rows):
    """League Modifier: the league whose extra member adds the most chemistry (rows computed without a
    manager league). None if no league adds anything; ties go to the lowest league id."""
    gain = Counter()
    for c, r in zip(squad, rows):
        if r and r["state"] == "ok" and r["raw"] < 3:
            up = min(3, r["club"][1] + pts(r["league"][0] + 1, LEAGUE_T) + r["nation"][1])
            gain[c["li"]] += up - r["raw"]
    best = max(gain.values(), default=0)
    return min(k for k, v in gain.items() if v == best) if best > 0 else None


def _manager_rows(slots, squad, mgr):
    """Rows with the manager applied. Returns (rows, manager league used)."""
    mgr = mgr or {}
    ni, li = mgr.get("ni"), mgr.get("li")
    if mgr.get("li_free"):
        li = _best_league(squad, _raw(slots, squad, ni, None))
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


def total_only(slots, squad, mgr):
    rows, _ = _manager_rows(slots, squad, mgr)
    return sum(r["raw"] for r in rows if r is not None)


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
    """Manager changes that raise squad chemistry: a manager of another nation (new manager card), another
    league (League Modifier item, or a manager from that league), or both. Only nations/leagues already in
    the squad can help. With li_free the league is picked automatically, so only the nation varies."""
    mgr = dict(mgr or {})
    cur = total_only(slots, squad, mgr)
    _, cur_li = _manager_rows(slots, squad, mgr)
    nations = {c["ni"]: c.get("nn") for c in squad if c is not None}
    leagues = {c["li"]: c.get("ln") for c in squad if c is not None}
    out = []
    for ni in set(nations) | {mgr.get("ni")}:
        if ni is None:
            continue
        cands = [None] if mgr.get("li_free") else list(set(leagues) | {cur_li})
        for li in cands:
            m = dict(mgr, ni=ni) if mgr.get("li_free") else dict(mgr, ni=ni, li=li)
            t = total_only(slots, squad, m)
            if t <= cur:
                continue
            _, used = _manager_rows(slots, squad, m)
            out.append({"ni": ni, "nn": nations.get(ni), "li": used, "ln": leagues.get(used), "total": t, "d": t - cur,
                        "nation": ni != mgr.get("ni"), "league": used != cur_li and not mgr.get("li_free")})
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
                  beam=20, per_slot=15, ok=None, mgr_configs=None):
    """Best squads reachable with exactly 1..k_max swaps (beam search; k=1 is exhaustive over the shortlist).
    Every swap in a listed combo is needed: dropping any one of them loses chemistry.
    mgr_configs: extra manager settings to try (manager change + swaps); each result says which it used.
    Returns {k: [ {swaps, total, d, dr, mgr} ]}."""
    base = total_only(slots, squad, mgr)
    configs = [(None, mgr)] + [(c, dict(mgr or {}, **{k: v for k, v in c.items() if k in ("ni", "li")}))
                               for c in (mgr_configs or [])]
    best = {}  # (k, swap key) -> result
    for label, m in configs:
        _, allr = single_swaps(slots, squad, locks, m, by_pos, max_drop, min_rating)
        sl = _shortlist(slots, squad, locks, m, by_pos, max_drop, min_rating, allr, per_slot, ok)
        frontier = [((), list(squad))]
        for k in range(1, k_max + 1):
            nxt = {}
            for swaps, sq in frontier:
                used = {s for s, _ in swaps}
                bps = {c["bp"] for c in sq if c}
                for i, cands in sl.items():
                    if i in used:
                        continue
                    for c in cands:
                        if c["bp"] in bps:
                            continue
                        key = tuple(sorted(swaps + ((i, c["s"]),)))
                        if key in nxt:
                            continue
                        new = list(sq)
                        new[i] = c
                        nxt[key] = (total_only(slots, new, m), new)
            ranked = sorted(nxt.items(), key=lambda kv: (-kv[1][0], -sum(c["ov"] for c in kv[1][1] if c)))
            for key, (t, sq) in ranked:
                if t <= base:
                    break
                prev = best.get((k, key))
                if prev and prev["total"] >= t:
                    continue
                best[(k, key)] = {"key": key, "sq": sq, "total": t, "m": m, "label": label}
            frontier = [(key, sq) for key, (t, sq) in ranked[:beam]]
    out = {}
    for (k, key), r in best.items():
        out.setdefault(k, []).append(r)
    res = {}
    for k, rs in out.items():
        rs.sort(key=lambda r: (-r["total"], r["label"] is not None, -sum(c["ov"] for c in r["sq"] if c)))
        keep, seen = [], set()
        for r in rs:
            if len(keep) >= n:
                break
            players = tuple(sorted((s, r["sq"][s]["bp"]) for s, _ in r["key"]))
            if players in seen:  # same players in other card versions: keep the best-ranked one
                continue
            seen.add(players)
            # every swap must matter: undoing any single one of them must lose chemistry
            needed = True
            for slot, _ in r["key"]:
                back = list(r["sq"])
                back[slot] = squad[slot]
                if total_only(slots, back, r["m"]) >= r["total"]:
                    needed = False
                    break
            if not needed:
                continue
            swaps = [{"slot": s, "out": squad[s], "in": r["sq"][s]} for s, _ in r["key"]]
            keep.append({"swaps": swaps, "total": r["total"], "d": r["total"] - base,
                         "dr": sum(w["in"]["ov"] - w["out"]["ov"] for w in swaps), "mgr": r["label"]})
        res[k] = keep
    return {k: res.get(k, []) for k in range(1, k_max + 1)}
