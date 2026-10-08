# Chem Builder — EA FC 27

Local tool that shows how to raise squad chemistry, with lockable players.

## Run
Windows: double-click **start.bat**. The app opens in your browser with no console window to keep open.
It stops by itself about 30 seconds after you close its tab (or press **Stop app**). Double-clicking
start.bat while it's already running just opens the page again. For a desktop icon: right-click
start.bat → Send to → Desktop (create shortcut).
If something goes wrong, run **start_console.bat** instead (it shows the messages) or read `chem_builder.log`.
1. Install Python 3.9+ (standard library only, nothing else to install).
2. Or in this folder: `python chem_builder.py`  (opens http://127.0.0.1:8765; `--stay` keeps it running after the tab closes)
3. Card data refresh: click **Update card data** in the app, or `python chem_builder.py --sync`
   (default: all cards rated 75+; `--min-rating 70` for more). cards.json here is a snapshot from 2026-10-08.

## Use
- Pick a formation (all 29 FC 27 Ultimate Team formations, taken from FUT.GG's squad builder), or edit any slot's position dropdown.
- Click an empty slot to start **fill mode**: type a name, press Enter, and the picker moves to the next empty slot (↑↓ to choose, Esc to stop). Chemistry updates live as you add players.
- Drag a card onto another slot to swap them. **Undo / Redo** (Ctrl+Z / Ctrl+Y) cover every change.
- Changing formation re-seats your players into the best-fitting slots instead of dropping them.
- **Saved squads** keeps several squads in this browser. **Share link** copies a link that opens the squad in Chem Builder (the person opening it needs the app running).
- Set the manager's nation. Tick "I can change the manager's league" (League Modifier item) and the tool picks the best league itself and tells you which one to apply. The results also list which manager nation would add the most chemistry.
- **Import squad…** shows a preview (slot by slot, with a dropdown to pick a different version) before anything changes:
  - **FUT.GG link**: link your EA account on FUT.GG, load your squad in its Squad Builder, press Share, paste the link. Formation and manager come across too. (Reads FUT.GG's public squad endpoint; checked against FUT.GG's site code, Oct 2026.)
  - **FUTBIN**: drag the "→ Chem Builder" bookmark to your bookmarks bar, open your squad on FUTBIN, click it. FUTBIN blocks programs (Cloudflare), so the bookmark reads the card ids from the page in your own browser. PENDING VALIDATION: FUTBIN's squad page couldn't be loaded from the build machine; the bookmark was tested on a page using FUTBIN's card-image naming.
  - **Paste text**: one player per line, e.g. `ST Mbappe 91`.
- EA's FC Community API (the official club import used by FUTBIN, FUT.GG and FUTWIZ) is only open to those approved sites, so this tool goes through them and never logs in to EA.
- 🔒 locks a slot: it is never swapped, but still counts for everyone else's links.
- Results are ranked by chemistry gained, then the highest overall of the incoming card. A FUT.GG score is shown only when the feed provides one (it is empty for FC 27 so far) and is never used for ranking.
- "Find chemistry upgrades" gives a step-by-step plan, ranked single swaps, and two-swap combos.
- Type the squad chemistry your game shows into "game shows" — the tool tells you if its rules agree.
- "Only use cards I own": paste card names (one per line, optional rating: `Alisson 87`) to restrict the pool.
  Without it, the search covers every card in the database (ICONs included — tick "exclude ICONs" if you don't have any).

## Budget (max price per incoming card)
- Enter a limit in "Budget: max price per incoming card". It applies only to the card being swapped in, never to the squad total, and it is ignored when "Only use cards I own" is filled in.
- Prices: paste them under "Prices I know" (`Mbappé 91 12,500`, `Cafu 85 8.5k`). FUT.GG serves prices behind a Cloudflare browser check (403 `cf-mitigated: challenge`, confirmed 8 Oct 2026 from a user PC), so the live lookup normally fails; the app tries it once per run in case FUT.GG opens it again. Pasted prices always win.
- Cards with no price are hidden unless you tick "also show cards with no price data". Results still rank by chemistry gained, then highest overall.
- Prices are not platform-specific in the app; paste the ones for your platform if the live lookup is blocked.

## Rules implemented (checked 8 Oct 2026 against community guides; no EA primary source found)
- 0–3 chem per starter, max 33. Counts include the player. Club 2/4/7, league 3/5/8, nation 2/5/8; types add, capped at 3.
- Manager: counts as one more player of its nation and of its league toward those thresholds (so it only helps when that crosses a threshold). Guides describe a flat "+1 if nation or league matches", but a real FC 27 squad checked on 8 Oct 2026 (25/33 in game) only adds up under the threshold rule; it is a test in test_engine.py. The league can be changed with a League Modifier item; the nation cannot.
- Must be in a preferred position (main + alternate) to earn chem or count for others.
- FC 27: ICON = full chem, +1 nation, +1 to every league. Hero / Hall of FUT = full chem, +1 league, +1 nation. None of them have a club link.
- Men's and women's players link through affiliated clubs, not leagues.

## Known limits
- FUT.GG's JSON feed is undocumented and could change; FUTBIN blocked automated access in testing, so it is not implemented.
- Price is not included (the feed had no usable prices). Formations come from FUT.GG's data and match FIFPlay's FC 27 list; not checked against EA's in-game screen directly.
- Evolved cards missing from the cache: use "also search FUT.GG live" in the picker, or add a custom card.
- Two-swap combos and the plan are heuristic searches (single swaps are exhaustive).
- `python test_engine.py` runs the rule tests.

## Troubleshooting "failed to fetch players"
1. Click **Test connection** in the app (or run `python chem_builder.py --check`). It checks cards.json, DNS, and the FUT.GG feed, and names the cause (blocked/403, rate limited/429, certificate error from a firewall doing HTTPS inspection, DNS filter, timeout).
2. Normal searching never touches the internet: it reads cards.json next to chem_builder.py. Keep all files from the zip in one folder, and start the app with `python chem_builder.py` from that folder.
3. The feed is undocumented; a 404 means FUT.GG changed it and the sync code needs updating.
