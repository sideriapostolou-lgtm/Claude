# AGENTS.md: rules for any AI worker on this repo (Codex, ChatGPT, Claude)

You are a teammate on the owner's team. The owner is Sideri: he works from a phone, wants plain words, real
numbers and constant progress, and runs a small real-money trading desk from this code. You work through
**pull requests only**. Read `docs/HANDOFF.md` before your first change, and add an entry to
`docs/WORKLOG.md` at the end of every session.

## Hard rules (never break these)

1. **Real money.** Real money is switched on, or made bigger, only on the owner's explicit and specific word in
   the current conversation, with the amounts or caps named. "Scale it" with no numbers is not enough: put the
   options and their risks to him and wait. Guard and learning code may switch real money **off**, never on.
   When unsure, do not.
2. **No secrets anywhere.** Never commit, print, paste or store an API key, a token, a wallet secret or a
   password. Keys live only in the Railway service's variables. Never run a tool that lists Railway variable
   values. Never create or commit a `.env` file. Before every push, scan the diff for secret-looking strings
   (long random strings, `sk-`, `jup_`, private keys) and stop if you find one.
3. **No deploys.** Do not deploy, restart the service or change a Railway variable. You have no Railway access on
   purpose. If a change needs a deploy, say so in the pull request and in `docs/WORKLOG.md`, with exact steps for
   the owner (see `docs/HANDOFF.md` section 4).
4. **Branches.** Work on `codex/<short-description>` (Claude uses `claude/...`). Open the pull request into
   `claude/nightcrawler-memecoin-bot-Gwnb1S`, the deploy branch. Never push to the deploy branch directly,
   never force-push it, never rewrite its history.
5. **The owner's "stop".** If the owner says stop, real money must go off. You cannot do it yourself, so give him
   the emergency steps in `docs/HANDOFF.md` section 1.
6. **Green before push.** Tests and mypy must pass, and ruff must pass on the Python files you changed (the repo
   has about 470 older ruff findings in untouched files; do not mass-fix them in an unrelated pull request). Any change to real-money code (`polydesk.py`,
   `polymarket_us.py`, `marcodesk.py`, `deskguard.py`, `broker/`, `risk.py`, `withdraw.py`, `config.py`) needs
   tests that pin the safety behaviour, and the pull request must say "touches real money" in its title.
7. **Honest results.** Research follows the labs' rules (pre-registered plan, TRAIN -> VAL -> one look at TEST).
   "NO EDGE" is a valid answer. Never present paper or backtest results as real money. Report real money in the
   venue's own numbers. If something failed or was skipped, say so.
8. **The owner's own bets.** The owner bets in the same Polymarket account (parlays, his own picks). Those are
   his (`rule="owner"`); never count them in the bot's caps or stops, and never touch them.

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
