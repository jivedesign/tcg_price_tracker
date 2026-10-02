# TCG price tracker

Daily prices for Magic (Scryfall), plus Pokémon / One Piece (TCGCSV) and stocks, stored as JSON in `data/` and charted by `index.html`.

## Setup (about 10 minutes)
1. Create a **public** GitHub repo and push this folder to it.
2. Edit the User-Agent in `collect.py` to include your repo URL (Scryfall and TCGCSV both ask for this).
3. Repo Settings > Actions > General > Workflow permissions: choose **Read and write**.
4. Settings > Pages: deploy from branch `main`, folder `/ (root)`.
5. Actions tab > **collect** > Run workflow: run `init-mtg`, then `backfill-mtg` (one-off, takes a few minutes), then `daily`.
6. The job now runs every day at 21:30 UTC. Your app is at `https://<user>.github.io/<repo>/`.

## Adding Pokémon / One Piece cards
Locally run `pip install requests` then, for example:
`python collect.py find pokemon "Charizard ex" "Obsidian"` (the last argument narrows to matching sets and makes it much faster).
Paste the JSON lines it prints into the `cards` list for that game in `watchlist.json`. Use `"sub"` to pick a printing type (Normal, Holofoil, Reverse Holofoil...).

## Adding another game
Add an entry under `games` in `watchlist.json` with the TCGplayer category name. The app picks it up automatically.

## Notes
- Credit Scryfall and MTGJSON as data sources. Keep request volume low.
- Stock data uses an unofficial Yahoo endpoint and may need replacing.
- If the daily job stops running after a quiet spell, re-enable it in the Actions tab.
