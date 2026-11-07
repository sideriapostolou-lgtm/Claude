# AGENTS.md: rules for any AI worker on this repo (Codex, ChatGPT, Claude)

You are a teammate on the owner's team. The owner is Sideri: he works from a phone, wants plain words, real
numbers and constant progress, and runs a small real-money trading desk from this code. On 2026-10-12 the owner
asked that every AI worker work exactly like Claude does: push to the deploy branch, which deploys automatically,
and read the live bot's Railway logs. That access comes with every rule below. Read `docs/HANDOFF.md` before
your first change, and add an entry to `docs/WORKLOG.md` at the end of every session. Codex owns integration; assigned workers and on-request Claude assistance use
`docs/COORDINATION.md` (current ownership, safe merge minutes and shared inbox) at the start of every
task and before every merge. Declare shared work there; historical ownership does not prove routine control.

**Standing release approval (owner, 2026-10-14):** deploy finished, tested improvements and verify them
without asking for another merge/deploy confirmation each time. This supersedes the earlier session's
read-only restriction for code releases. Keep safe merge minutes, required checks and deployment verification.
It does not authorize changing money limits, resetting stops/resume budgets, enabling a new real-money desk,
removing trading safeguards or changing Railway variables without the specific instructions required below.
Do not let an already-approved deployment wait for another generic approval.

**Development model workflow (owner, 2026-10-14):** follow [docs/MODEL_WORKFLOW.md](docs/MODEL_WORKFLOW.md)
and [docs/CONTINUITY_INDEX.md](docs/CONTINUITY_INDEX.md). Prefer GPT-6.1 Sol for implementation, GPT-6 Astra
for complex architecture/independent money-sensitive review, and GPT-6 Luna for bounded routine extraction.
These roles do not alter trading authority or replace deterministic order/risk/accounting code. Give each
worker exact source references, scope and a [handoff record](docs/WORKER_HANDOFF_TEMPLATE.md); preserve
originals and unresolved work. The integration owner coordinates writes and releases. State unavailable
models/fallbacks honestly; a model change does not transfer omitted context or guarantee correctness.

## Hard rules (never break these)

1. **Real money.** Real money is switched on, or made bigger, only on the owner's explicit and specific word in
   the current conversation, with the amounts or caps named. "Scale it" with no numbers is not enough: put the
   options and their risks to him and wait. Guard and learning code may switch real money **off**, never on.
   When unsure, do not.
2. **No secrets anywhere.** Never commit, print, paste or store an API key, a token, a wallet secret or a
   password. Keys live only in the Railway service's variables. Never run a tool that lists Railway variable
   values. Never create or commit a `.env` file. Before every push, scan the diff for secret-looking strings
   (long random strings, `sk-`, `jup_`, private keys) and stop if you find one.
3. **Deploys.** A push to `claude/nightcrawler-memecoin-bot-Gwnb1S` that touches `src/**`, `pyproject.toml`,
   `Dockerfile`, `railway.json` or `README.md` deploys to the live real-money bot within a minute or two. So push
   only work that is finished and tested. After every such push, check the deploy: Railway built that exact commit,
   and the logs show `polydesk_started ... (LIVE ...)` with no tracebacks. If the owner put a Railway token in your
   environment (`RAILWAY_TOKEN`), use it for logs and status only. Never print the token, never run a command that
   prints variable values, and never change a Railway variable unless the owner names the variable and value.
   Without a token, ask the owner or Claude to check the deploy.
4. **Branches.** Small, tested changes go straight to `claude/nightcrawler-memecoin-bot-Gwnb1S`, as Claude does.
   Never force-push it, never rewrite its history, and pull first so you never overwrite someone else's commit. Use
   a `codex/<short-description>` branch and a pull request when the change is big or when the owner wants to look
   first. **Real-money code** (`polydesk.py`, `polymarket_us.py`, `marcodesk.py`, `deskguard.py`, `broker/`,
   `risk.py`, `withdraw.py`, `config.py`, `speeddesk_live*.py`, `speeddesk_kalshi_client.py`) changes only on the owner's go-ahead in the current conversation.
5. **The owner's "stop".** If the owner says stop, real money must go off. With a Railway token: set
   `POLYDESK_MODE=paper` on service `bot`. Railway redeploys, and from then on the desk sends no new real orders;
   open bets still settle. Then confirm in the logs that it started in paper mode. Without a token: give him the
   emergency steps in `docs/HANDOFF.md` section 1 at once. The separate Kalshi speed desk must also stop:
   set `SPEEDDESK_KALSHI_MODE=paper`, verify cancellation of its resting bids, and reconcile remaining exposure.
   Filled bets still settle; never claim that paper mode closed them. Setting only POLYDESK_MODE does not stop Kalshi.
6. **Green before push.** Tests and mypy must pass, and ruff must pass on the Python files you changed (the repo
   has about 470 older ruff findings in untouched files; do not mass-fix them in an unrelated pull request). Any change to real-money code (`polydesk.py`,
   `polymarket_us.py`, `marcodesk.py`, `deskguard.py`, `broker/`, `risk.py`, `withdraw.py`, `config.py`,
   `speeddesk_live*.py`, `speeddesk_kalshi_client.py`) needs
   tests that pin the safety behaviour, and the pull request must say "touches real money" in its title.
7. **Honest results.** Research follows the labs' rules (pre-registered plan, TRAIN -> VAL -> one look at TEST).
   "NO EDGE" is a valid answer. Never present paper or backtest results as real money. Report real money in the
   venue's own numbers. If something failed or was skipped, say so.
8. **The owner's own bets.** The owner bets in the same Polymarket account (parlays, his own picks). Those are
   his (`rule="owner"`); never count them in the bot's caps or stops, and never touch them.
9. **Keep unfinished work.** The owner asked on October 15 that every unfinished task stay on its existing
   queue or commitment with its actual status, missing evidence and concrete next step. For deployable work,
   tests, a commit or a merged PR are not completion: verify the exact live deployment and required runtime
   evidence. Research and paper-only tasks keep their own completion requirements; this rule does not
   authorize making them live. Follow the newest owner work order in COORDINATION: October16 operating
   handoff before the next town reorganization, existing trading/recorder obligations retained, TJR/MNQ
   last. Preserve finished substeps separately from the unfinished overall task.

## Commands

```bash
pip install -e ".[dev]"            # Python 3.11+; installs pytest, mypy and the optional extras
pytest -q                          # about 3,000 tests; all must pass (a few skip without network)
pip install ruff && git diff --name-only origin/claude/nightcrawler-memecoin-bot-Gwnb1S -- '*.py' | xargs -r ruff check   # lint the files you changed
mypy src/nightcrawler              # types (also run by tests/test_typecheck.py)
python -m nightcrawler --help      # the CLI; `nightcrawler run` starts the engine in paper mode by default
```

Never set `TRADING_MODE=live`, `POLYDESK_MODE=live` or any `*_CONFIRM` variable on your machine. Paper mode
needs no keys. Network smoke tests run only with `NIGHTCRAWLER_LIVE_TESTS=1`.

## Conventions

* Conventional commits: `feat:`, `fix:`, `docs:`, `research(labN):`, `test:`, `refactor:`, `chore:`.
* Match the code around you: comment density, naming, plain-words owner-facing text.
* The full list of settings is `.env.example`; every setting is read in `src/nightcrawler/config.py`.
* Read before you edit. Make small, focused changes. One pull request per change.
