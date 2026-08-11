# Prop Engine board — refresh runbook

This is the full procedure the twice-daily refresh routine follows (routine
`trig_01SZiPNmpDxwse413xijMZfu`, cron `0 16,22 * * *` UTC, fires into the
build session). Whenever that routine fires, follow ALL steps below — the
site-update steps (6–8) are part of the procedure even if the routine's
prompt text only mentions the artifact.

## 1. Rebuild the board

```bash
cd /home/user/Claude/prop-engine
python3 web/build_phone_demo.py
```

This fetches today's MLB slate, prices every market, grades yesterday's
board from `data/demo_history/`, settles the $10-flat P&L, and writes
`web/phone_demo_built.html` plus today's history snapshot.

## 2. Republish the Claude artifact

Copy `web/phone_demo_built.html` over the artifact source at
`<scratchpad>/prop-engine-demo.html` and call the Artifact tool with that
same file path (same path ⇒ same URL). Favicon stays `⚡`.

## 3. Commit + push to GitHub

Commit `web/phone_demo_built.html` and `data/demo_history/` on branch
`claude/prop-engine-v1-3w6jvf`, push with `git push -u origin`.

## 4–5. Sanity

Spot-check the built page: today's date in the header, a non-empty board,
and the "Yesterday, graded" section present when history exists.

## 6. Update The 99 Community site copy of the app

The site serves the same file at
`https://sage-frost-842.higgsfield.app/apps/prop-engine`.

```bash
SITE=/tmp/claude-0/-home-user-Claude/0dc93e53-73a9-5a39-848b-35b01401f677/scratchpad/site
# if the clone is gone (fresh container), re-clone:
#   get a token via Higgsfield MCP: select_workspace, then
#   website_repo_access(website_id=189ca5a3-54e1-452a-aea4-420cf9594ad8)
#   git -c http.extraHeader="Authorization: token <TOKEN>" clone \
#     https://apps-repos.higgsfield.ai/hfu-user37raYK73mveR4zPEdz9xgOVsef4/sage-frost-842-189ca5a3-54e1-452a-aea4-420cf9594ad8.git $SITE
cp /home/user/Claude/prop-engine/web/phone_demo_built.html \
   $SITE/app/public/apps/prop-engine/index.html
```

## 7. Push the site repo

```bash
cd $SITE
git add app/public/apps/prop-engine/index.html
git commit -m "chore: refresh prop engine board"
git -c http.extraHeader="Authorization: token <TOKEN>" push origin main
```

(Fetch a fresh token via `website_repo_access` each time; tokens are
short-lived. Never print the token.)

## 8. Deploy

Call Higgsfield MCP `deploy_website` for website_id
`189ca5a3-54e1-452a-aea4-420cf9594ad8`, then poll `website_status` until
`production.status == "deployed"`. A 60s timeout on the deploy call is
normal — the deploy continues server-side.

## Skip rule

If the rebuilt board is byte-identical to the previous one (no games, same
slate), skip steps 6–8.

## Standing intent

A dedicated second routine for steps 6–8 ("The99 site: refresh Prop Engine
board", cron `15 16,22 * * *`) could not be created due to a transient
MCP permission failure — retry creating it on a future firing; until it
exists, steps 6–8 ride along with the main routine.
