# Chem Builder — EA FC 27

Local tool that shows how to raise squad chemistry, with lockable players.

## Run
Windows: double-click **start.bat** and keep its window open while you use the app (closing it stops the app, and the page then shows "Failed to fetch").
1. Install Python 3.9+ (standard library only, nothing else to install).
2. In this folder: `python chem_builder.py`  (opens http://127.0.0.1:8765)
3. Card data refresh: click **Update card data** in the app, or `python chem_builder.py --sync`
   (default: all cards rated 75+; `--min-rating 70` for more). cards.json here is a snapshot from 2026-10-08.

## Use
- Pick a formation (or edit any slot's position dropdown), click each slot to pick a player.
- Set the manager's nation. Tick "I can change the manager's league" (League Modifier item) and the tool picks the best league itself and tells you which one to apply. The results also list which manager nation would add the most chemistry.
- "Paste squad…" imports a squad from text (one player per line, e.g. `ST Mbappe 91`; copied FUTBIN/FUT.GG table rows work too). There is no direct EA/FUTBIN link: FUTBIN's EA import is a partner integration with no export or API, and this tool never logs in to EA.
- 🔒 locks a slot: it is never swapped, but still counts for everyone else's links.
- Results are ranked by chemistry gained, then the highest overall of the incoming card. A FUT.GG score is shown only when the feed provides one (it is empty for FC 27 so far) and is never used for ranking.
- "Find chemistry upgrades" gives a step-by-step plan, ranked single swaps, and two-swap combos.
- Type the squad chemistry your game shows into "game shows" — the tool tells you if its rules agree.
- "Only use cards I own": paste card names (one per line, optional rating: `Alisson 87`) to restrict the pool.
  Without it, the search covers every card in the database (ICONs included — tick "exclude ICONs" if you don't have any).

## Budget (max price per incoming card)
- Enter a limit in "Budget: max price per incoming card". It applies only to the card being swapped in, never to the squad total, and it is ignored when "Only use cards I own" is filled in.
- Prices: the app tries a live FUT.GG lookup (PENDING VALIDATION: the endpoint could not be tested from the build sandbox; Cloudflare returned 403 there). If that fails you get a clear message, and you can paste prices under "Prices I know" (`Mbappé 91 12,500`, `Cafu 85 8.5k`). Pasted prices always win.
- Cards with no price are hidden unless you tick "also show cards with no price data". Results still rank by chemistry gained, then highest overall.
- Prices are not platform-specific in the app; paste the ones for your platform if the live lookup is blocked.

## Rules implemented (checked 8 Oct 2026 against community guides; no EA primary source found)
- 0–3 chem per starter, max 33. Counts include the player. Club 2/4/7, league 3/5/8, nation 2/5/8; types add, capped at 3.
- Manager: flat +1 for sharing the player's nation or league (max +1). The league can be changed with a League Modifier item; the nation cannot.
- Must be in a preferred position (main + alternate) to earn chem or count for others.
- FC 27: ICON = full chem, +1 nation, +1 to every league. Hero / Hall of FUT = full chem, +1 league, +1 nation. None of them have a club link.
- Men's and women's players link through affiliated clubs, not leagues.

## Known limits
- FUT.GG's JSON feed is undocumented and could change; FUTBIN blocked automated access in testing, so it is not implemented.
- Price is not included (the feed had no usable prices). The formation presets are not checked against EA's in-game list.
- Evolved cards missing from the cache: use "also search FUT.GG live" in the picker, or add a custom card.
- Two-swap combos and the plan are heuristic searches (single swaps are exhaustive).
- `python test_engine.py` runs the rule tests.

## Troubleshooting "failed to fetch players"
1. Click **Test connection** in the app (or run `python chem_builder.py --check`). It checks cards.json, DNS, and the FUT.GG feed, and names the cause (blocked/403, rate limited/429, certificate error from a firewall doing HTTPS inspection, DNS filter, timeout).
2. Normal searching never touches the internet: it reads cards.json next to chem_builder.py. Keep all files from the zip in one folder, and start the app with `python chem_builder.py` from that folder.
3. The feed is undocumented; a 404 means FUT.GG changed it and the sync code needs updating.
