"""Rule tests for chem_engine.  Run:  python test_engine.py"""
import time
import chem_builder as cb
import chem_engine as eng


def card(i, pos, ni=1, li=1, ck=None, ov=85, ty="", fc=False, g=1, alts=(), **kw):
    c = {"s": f"t{i}", "n": f"P{i}", "ov": ov, "rt": "x", "g": g, "p": pos, "a": list(alts), "ni": ni, "nn": f"N{ni}",
         "li": li, "ln": f"L{li}", "ck": ck, "cn": ck, "ty": ty, "bp": i, "fc": fc, "xc": 0, "xl": 0, "xn": 0,
         "xsl": False, "xsn": False}
    c.update(kw)
    return c


SLOTS = ["ST", "ST", "CAM", "CM", "CM", "CDM", "LB", "CB", "CB", "RB", "GK"]


def squad_of(**spec):
    return [card(i, p, **{k: v[i] if isinstance(v, list) else v for k, v in spec.items()}) for i, p in enumerate(SLOTS)]


def test_thresholds():
    # club 2/4/7, league 3/5/8, nation 2/5/8
    assert [eng.pts(n, eng.CLUB_T) for n in (1, 2, 3, 4, 6, 7)] == [0, 1, 1, 2, 2, 3]
    assert [eng.pts(n, eng.LEAGUE_T) for n in (2, 3, 4, 5, 7, 8)] == [0, 1, 1, 2, 2, 3]
    assert [eng.pts(n, eng.NATION_T) for n in (1, 2, 4, 5, 7, 8)] == [0, 1, 1, 2, 2, 3]


def test_cap_at_three():
    # 4 from one club + 8 from one nation would be 2+3=5 -> capped at 3
    sq = squad_of(ni=[1] * 8 + [2, 3, 4], li=list(range(11)), ck=["A"] * 4 + [None] * 7)
    ev = eng.evaluate(SLOTS, sq, None)
    assert ev["players"][0]["chem"] == 3, ev["players"][0]


def test_zero_when_nothing_links():
    sq = squad_of(ni=list(range(11)), li=list(range(11)), ck=[None] * 11)
    assert eng.evaluate(SLOTS, sq, None)["total"] == 0


def test_manager_counts_toward_thresholds():
    sq = squad_of(ni=list(range(11)), li=list(range(11)), ck=[None] * 11)
    # a lone player: manager makes nation count 2 (+1) and league count 2 (still 0)
    ev = eng.evaluate(SLOTS, sq, {"ni": 0, "li": 0})
    assert ev["players"][0]["chem"] == 1 and ev["total"] == 1
    # nation already on 1 point (count 2): manager -> count 3, no new threshold, so no gain
    sq = squad_of(ni=[5, 5] + list(range(20, 29)), li=list(range(11)), ck=[None] * 11)
    assert eng.evaluate(SLOTS, sq, {"ni": 5})["total"] == eng.evaluate(SLOTS, sq, None)["total"] == 2


def test_real_fc27_squad_matches_game():
    # User's in-game squad, 8 Oct 2026: 4-1-2-1-2 (2), manager Spain + Arkema Premiere Ligue, game shows 25/33.
    # Per-player badges read off the screenshot: Salma 3 (the flat "+1" rule gave her 2 -> 24).
    slots = ["GK", "RB", "CB", "CB", "LB", "CDM", "CM", "CM", "CAM", "ST", "ST"]
    spec = [("GK", "BR", "PL", "LIV"), ("RB", "ES", "LL", "ATM"), ("CB", "FR", "LL", "RMA"), ("CB", "ES", "LL", "BAR"),
            ("LB", "PT", "LL", "BAR"), ("CDM", "EN", "WSL", "ARS"), ("CM", "FR", "ARK", "PSG"), ("CM", "ES", "LIGAF", "BAR"),
            ("CAM", "BR", "NWSL", "KCC"), ("ST", "ES", "ARK", "OL"), ("ST", "BR", "LL", "RMA")]
    sq = [card(i, p, ni=n, li=l, ck=k) for i, (p, n, l, k) in enumerate(spec)]
    ev = eng.evaluate(slots, sq, {"ni": "ES", "li": "ARK", "li_free": False})
    assert [p["chem"] for p in ev["players"]] == [1, 3, 3, 3, 3, 0, 2, 3, 1, 3, 3]
    assert ev["total"] == 25


def test_off_position_gets_zero_and_does_not_count():
    sq = squad_of(ni=[1] * 11, li=[1] * 11, ck=["A"] * 11)
    base = eng.evaluate(SLOTS, sq, None)["total"]
    assert base == 33
    sq2 = list(sq)
    sq2[0] = dict(sq2[0], p="GK")  # striker slot filled by a pure GK
    ev = eng.evaluate(SLOTS, sq2, None)
    assert ev["players"][0]["chem"] == 0 and not ev["players"][0]["inpos"]
    assert ev["total"] == 30  # 10 others: club 10 (3) -> still full


def test_icon_and_hero_rules_fc27():
    # ICON: full chem, counts +1 nation and +1 to EVERY league, no club link
    sq = squad_of(ni=list(range(11)), li=[10, 10] + list(range(2, 11)), ck=[None] * 11)
    sq[2] = dict(sq[2], ty="icon", fc=True, li=2118)
    ev = eng.evaluate(SLOTS, sq, None)
    assert ev["players"][2]["chem"] == 3
    # two league-10 players + icon bonus = league count 3 -> +1 each
    assert ev["players"][0]["chem"] == 1 and ev["players"][1]["chem"] == 1
    # Hero: full chem; counts as an ordinary league/nation member (+1,+1) in FC 27
    sq = squad_of(ni=[5, 5] + list(range(2, 11)), li=[10, 10, 10] + list(range(3, 11)), ck=[None] * 11)
    sq[2] = dict(sq[2], ty="hero", fc=True, ni=5, li=10)
    ev = eng.evaluate(SLOTS, sq, None)
    # league: 3 members (2 normal + hero) -> +1 ; nation: 3 members -> +1 ; (player 0)
    assert ev["players"][0]["chem"] == 2, ev["players"][0]


def test_men_women_link_through_club_not_league():
    men = card(0, "ST", ni=1, li=53, ck="243", g=1)
    wom = card(1, "ST", ni=2, li=2222, ck="243", g=2)  # same club link key, different league
    sq = [men, wom] + [card(i, p, ni=100 + i, li=100 + i) for i, p in enumerate(SLOTS[2:], start=2)]
    ev = eng.evaluate(SLOTS, sq, None)
    assert ev["players"][0]["club"] == [2, 1] and ev["players"][1]["chem"] == 1
    assert ev["players"][0]["league"][1] == 0


def test_real_data_sibling_clubs():
    cb.load_cache()
    cards = cb.STATE["cards"]
    groups = {}
    for c in cards:
        if c["ck"]:
            groups.setdefault(c["ck"], set()).add(c["g"])
    both = [k for k, v in groups.items() if v == {1, 2}]
    assert len(both) >= 5, f"expected linked men/women club groups, got {len(both)}"


def test_swap_search_respects_locks_and_duplicates():
    cb.load_cache()
    by_slug = cb.STATE["cards"]
    pool = [c for c in by_slug if c["ov"] >= 80]
    by_pos = eng.index_pool(pool)
    pick = lambda pos, k=0: [c for c in pool if c["p"] == pos][k]  # noqa: E731
    squad = [pick(p, i) for i, p in enumerate(SLOTS)]
    locks = [True] * 11
    base, top, _ = eng.top_singles(SLOTS, squad, locks, None, by_pos, 3, 0)
    assert top == []  # everything locked -> no suggestions
    locks[3] = False
    base, top, _ = eng.top_singles(SLOTS, squad, locks, None, by_pos, 3, 0, only_positive=False)
    assert top and all(r["slot"] == 3 for r in top)
    names = {c["bp"] for i, c in enumerate(squad) if i != 3}
    assert all(r["in"]["bp"] not in names for r in top)


def test_performance_and_plan():
    cb.load_cache()
    pool = [c for c in cb.STATE["cards"] if c["ov"] >= 78]
    by_pos = eng.index_pool(pool)
    pick = lambda pos, k: [c for c in pool if c["p"] == pos][k]  # noqa: E731
    squad = [pick(p, 5 + 3 * i) for i, p in enumerate(SLOTS)]
    locks = [False] * 11
    t = time.time()
    base, singles, allr = eng.top_singles(SLOTS, squad, locks, None, by_pos, 4, 0)
    t1 = time.time() - t
    t = time.time()
    pairs = eng.synergy_pairs(SLOTS, squad, locks, None, by_pos, allr, base, 4, 0)
    t2 = time.time() - t
    t = time.time()
    chain, total, _final = eng.plan_chain(SLOTS, squad, locks, None, by_pos, 4, 0, 5)
    t3 = time.time() - t
    print(f"  base {base}; singles {len(singles)} ({t1:.2f}s); pairs {len(pairs)} ({t2:.2f}s); chain {len(chain)} steps -> {total} ({t3:.2f}s)")
    assert total >= base
    # replaying the chain through the full evaluator must give the same total
    cur = list(squad)
    for st in chain:
        for s in st["swaps"]:
            cur[s["slot"]] = s["in"]
    assert eng.evaluate(SLOTS, cur, None)["total"] == total


def test_ranking_is_chem_then_overall():
    r = [{"d": 2, "dr": 5, "in": {"ov": 80}}, {"d": 2, "dr": -1, "in": {"ov": 90}}, {"d": 3, "dr": -9, "in": {"ov": 70}}]
    r.sort(key=eng._rank_key)
    assert [x["in"]["ov"] for x in r] == [70, 90, 80]


def test_manager_free_league_picks_best():
    # 3 players share league 7 but sit on 2 league pts (count 3 -> 1)... build: manager nation matches nobody
    sq = squad_of(ni=list(range(11)), li=[7, 7] + list(range(20, 29)), ck=[None] * 11)
    ev = eng.evaluate(SLOTS, sq, {"ni": 99, "li": None, "li_free": True})
    assert ev["mgr_li"] == 7 and ev["players"][0]["chem"] == 1 and ev["players"][1]["chem"] == 1
    ev2 = eng.evaluate(SLOTS, sq, {"ni": 99, "li": 20, "li_free": False})
    assert ev2["total"] == 0  # fixed league 20: a lone player + manager = 2, below the 3 needed


def test_manager_nation_options():
    sq = squad_of(ni=[5] * 4 + list(range(20, 27)), li=list(range(11)), ck=[None] * 11)
    o = eng.manager_options(SLOTS, sq, {"ni": None, "li": None, "li_free": False})
    assert o["options"][0]["ni"] == 5 and o["options"][0]["d"] == 4  # Spain-style 4 -> 5: each of 4 goes 1 -> 2


def test_manager_suggestions_cover_nation_and_league():
    # 4 from nation 5 (league 9 x2 + others); manager nation 1 / league 0 helps nobody
    sq = squad_of(ni=[5] * 4 + list(range(20, 27)), li=[9, 9] + list(range(30, 39)), ck=[None] * 11)
    s = eng.manager_suggestions(SLOTS, sq, {"ni": 1, "li": 0, "li_free": False})
    best = s[0]
    assert best["ni"] == 5 and best["li"] == 9 and best["nation"] and best["league"]
    assert best["d"] == 4 + 2  # nation 4->5: four players +1; league 2->3: two players +1
    league_only = [o for o in s if not o["nation"]]
    assert league_only and league_only[0]["li"] == 9 and league_only[0]["d"] == 2
    assert eng.manager_suggestions(SLOTS, sq, {"ni": 5, "li": 9, "li_free": False}) == []  # already best


def test_parse_line():
    assert cb.parse_line("1. ST Mbappe 91")["name"] == "Mbappe"
    p = cb.parse_line("Mbappe 91 ST")
    assert p["rating"] == 91 and p["pos"] == "ST"
    assert cb.parse_line("Kylian Mbappé\t91\t12,500")["rating"] == 91
    assert cb.parse_line("   ") is None


def test_import_preview_text():
    cb.load_cache()
    r = cb.preview_text("ST Mbappe 91\nGK Alisson\nnot a real playerzzz", ["GK", "ST"])
    assert r["rows"][0]["card"]["p"] == "GK" and r["rows"][1]["card"]["n"].startswith("Mbapp")
    assert r["unmatched"] == ["not a real playerzzz"]
    assert any(a["bp"] == r["rows"][1]["card"]["bp"] for a in r["rows"][1]["alts"])  # other Mbappé versions offered


def test_seat_puts_everyone_in_position():
    slots = ["GK", "ST", "CB", "LB"]
    entries = [(card(1, "ST"), None), (card(2, "LB", alts=("CB",)), None), (card(3, "CB"), None), (card(4, "GK"), None)]
    picks = cb.seat(entries, slots)
    assert [slots[j] for j in picks] == ["ST", "LB", "CB", "GK"]
    # asked-for position wins a tie between two valid slots
    picks = cb.seat([(card(1, "CB", alts=("LB",)), "LB"), (card(2, "CB", alts=("LB",)), None)], ["CB", "LB"])
    assert picks == [1, 0]


def test_formations_table():
    assert len(cb.FORMATIONS) == 29
    for f in cb.FORMATIONS.values():
        assert len(f["slots"]) == 11 and f["slots"][0] == "GK" and f["slots"].count("GK") == 1
        assert not {"LWB", "RWB", "CF"} & set(f["slots"])
    assert sorted(cb.FORMATIONS["4-2-1-3"]["slots"]) == sorted(["GK", "RB", "CB", "CB", "LB", "CDM", "CDM", "CAM", "RW", "ST", "LW"])


def test_fgg_squad_import():
    cb.load_cache()
    ids = {0: "212831", 9: "231747", 10: "37576"}  # Alisson GK, Mbappé ST, Ronaldo (ICON) ST in 4-4-2
    fake_resp = {"data": {"uuid": "x", "data": {"activeFormationId": "16", "managerNationId": 18, "managerLeagueId": 53,
                 "gameSlug": "27", "title": "Weekend League", "activeGroupPositions":
                 [{"group": "FIELD", "positionIdx": k, "playerEaId": int(v)} for k, v in ids.items()] +
                 [{"group": "SUBSTITUTE", "positionIdx": 0, "playerEaId": 1}]}}}
    real = cb.fetch_json
    calls = []
    cb.fetch_json = lambda url, tries=4: calls.append(url) or (fake_resp if "/squads/" in url else {"data": []})
    try:
        r = cb.preview_fgg("https://www.fut.gg/27/squad-builder/0a1b2c3d-1111-2222-3333-444455556666/")
    finally:
        cb.fetch_json = real
    assert calls[0] == "https://www.fut.gg/api/squads/0a1b2c3d-1111-2222-3333-444455556666/"
    assert r["formation"] == "4-4-2" and r["mgr"] == {"ni": 18, "li": 53} and r["title"] == "Weekend League"
    assert r["rows"][9]["card"]["s"] == "27-231747" and r["rows"][10]["card"]["s"] == "27-37576"
    assert r["rows"][1]["card"] is None  # empty slot stays empty
    try:
        cb.preview_fgg("https://www.fut.gg/27/squad-builder/")
        assert False
    except ValueError:
        pass


def test_ids_import_dedupes_and_seats():
    cb.load_cache()
    real = cb.fetch_json
    cb.fetch_json = lambda url, tries=4: {"data": []}  # unknown id: live lookup finds nothing
    try:
        r = cb.preview_ids(["231747", "231747", "37576", "999999999"], ["ST", "GK"])
    finally:
        cb.fetch_json = real
    assert [x["card"]["s"] for x in r["rows"]] == ["27-231747", "27-37576"]  # duplicate id placed once
    assert r["unmatched"] == ["card id 999999999"]


def _opt_body(**opts):
    cb.load_cache()
    pool = [c for c in cb.STATE["cards"] if c["ov"] >= 80]
    pick = lambda pos, k: [c for c in pool if c["p"] == pos][k]  # noqa: E731
    squad = [cb.public(pick(p, 5 + 3 * i)) for i, p in enumerate(SLOTS)]
    for c in squad:
        c["_k"] = ""
    return {"slots": SLOTS, "squad": squad, "locks": [False] * 11, "mgr": None,
            "opts": dict({"max_drop": 4, "pairs": False, "max_steps": 3}, **opts)}


def test_budget_hides_expensive_incoming_cards():
    real = cb.fetch_json
    def fake(url, tries=1):  # price = 1000 for even ea ids, 50000 for odd
        ea = int(url.rstrip("/").split("/")[-1])
        return {"data": {"currentPrice": {"price": 1000 if ea % 2 == 0 else 50000}}}
    cb.fetch_json = fake
    try:
        r = cb.Handler.optimize(_opt_body(max_price=5000))
    finally:
        cb.fetch_json = real
    assert r["budget"]["over"] > 0 and r["singles"], r["budget"]
    for s in r["singles"]:
        assert r["budget"]["prices"][s["in"]["s"]] <= 5000
    for st in r["chain"]:
        for w in st["swaps"]:
            assert r["budget"]["prices"][w["in"]["s"]] <= 5000


def test_budget_blocked_endpoint_and_manual_fallback():
    real = cb.fetch_json
    def blocked(url, tries=1):
        raise RuntimeError("HTTP 403 Forbidden - blocked")
    cb.fetch_json = blocked
    try:
        r = cb.Handler.optimize(_opt_body(max_price=5000))
        assert r["singles"] == [] and "403" in r["budget"]["live_error"] and r["budget"]["lookups"] == 1
        r2 = cb.Handler.optimize(_opt_body(max_price=5000, include_unknown=True))
        assert r2["singles"]  # unknown-price cards allowed
        top = r2["singles"][0]["in"]
        manual = f"{top['n']} {top['ov']} 900000"
        r3 = cb.Handler.optimize(_opt_body(max_price=5000, include_unknown=True, price_list=manual))
        assert all(s["in"]["s"] != top["s"] for s in r3["singles"])  # manual price puts it over budget
    finally:
        cb.fetch_json = real


def test_budget_ignored_when_owned_list_used():
    r = cb.Handler.optimize(_opt_body(max_price=5000, club_list="Mbappe\nHaaland\nRodri"))
    assert r["budget"] is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    print("ALL PASSED")
