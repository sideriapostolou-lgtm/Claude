# Model roles for development

Adopted October 14, 2026 at the owner's request. This changes how we develop and review Nightcrawler;
it does not replace its services, migrate its data, or add model calls to its trading loop.
Start with [AGENTS.md](../AGENTS.md), [COORDINATION.md](COORDINATION.md), the newest
[WORKLOG.md](WORKLOG.md) entries and the [continuity index](CONTINUITY_INDEX.md).

## Assign work by consequence and complexity

| Role | Requested model | Responsibility |
| --- | --- | --- |
| Integration owner / implementer | `gpt-6.1-sol` | Own the current task, implement bounded changes, coordinate file ownership, run checks and verify authorized releases. |
| Architecture / independent reviewer | `gpt-6-astra` | Review research design, look-ahead leakage, concurrency, accounting, API failure recovery and money-sensitive changes. Findings need source references and concrete failure cases. |
| Evidence inventory / routine helper | `gpt-6-luna` | Extract already-approved facts, index files, compare bounded documents and prepare simple summaries. Every material conclusion is checked against its original source. |

These are starting assignments, not a ranking that proves correctness. A simple task does not need
three agents. Use Astra when the reasoning or consequences warrant it; give Luna small, specific tasks
with explicit paths and a required output shape. Do not give Luna trading-policy, ledger, risk or order
implementation/review responsibility, production mutation authority, or sealed research outcomes.
Model choice never changes the owner's authorization or the repository's release rules.

The lead may retain the model selected by the host/user in an already-running chat. For delegated work,
request the configured model explicitly when the host supports it; record what was requested and
whether launch succeeded. If a model is unavailable, state the limitation and the actual fallback;
do not present a different model's review as an Astra review. No benchmark or billing savings were
measured by this setup, and the model names do not establish a profitable strategy.

## Preserve the live control path

Kalshi execution stays in the existing Python controller and model, not an LLM Think/Act loop:

- [`speeddesk_live.py`](../src/nightcrawler/speeddesk_live.py) keeps one risk writer, reserves exposure,
  journals intent before send, and reconciles uncertain requests. Never blindly retry order creation.
- [`speeddesk_live_model.py`](../src/nightcrawler/speeddesk_live_model.py) keeps real venue fills and
  reservations authoritative. A cancellation request is not confirmation that liability disappeared.
- [`ledger.py`](../src/nightcrawler/ledger.py) preserves transactional accounting and receipts. Models
  may inspect authorized evidence; generated text never replaces fills, fees, balances or settlements.
- Practice, real Kalshi, real Polymarket US and the owner's own bets remain distinct. Keep every loss,
  open reservation, stop latch and consumed-resume history. Do not replay stored financial settings.

The optional Anthropic memecoin judge in [`judge.py`](../src/nightcrawler/judge.py) is an existing,
separate feature, not a GPT-powered Kalshi engine. Its synchronous timing is already documented as
delaying that engine's stop processing. This change does not modify or enable it.

Managed agents can help with offline research and coding. They are not a reason to add network model
latency, token budgets or nondeterministic model decisions to order/cancel timing. Any future model
research signal needs its own recorded experiment and version; this workflow grants no runtime access.

## One task, explicit ownership, independent verification

1. The integration owner reads current instructions, checks the queue and Git/worktree state, and
   records scope before allocating overlapping/shared files. Latest owner instructions win over stale
   handoff snapshots; an old cap or restart decision is not reusable permission.
2. Give each worker a [handoff record](WORKER_HANDOFF_TEMPLATE.md): base SHA, exact task, allowed files,
   exclusions, required source reads, data partition and acceptance criteria. Workers without inherited
   chat history receive these references explicitly. No worker can honestly claim to know omitted history.
3. Keep one writer per overlapping file set. Use isolated branches/worktrees for substantial code work;
   do not reset, clean or overwrite another worker's edits. Read-only reviewers do not commit fixes.
4. Have a reviewer inspect the actual patch and failure cases. Record the exact reviewed SHA, or the
   base SHA plus a hash of the complete uncommitted patch including new files. Any relevant later change
   needs renewed review. A review says what was checked and what remains unverified; it is not a vote.
5. Run the repository's required tests, mypy, changed-file Ruff and credential scan for code releases.
   Preserve the existing money-sensitive PR/title requirements. Configuration/docs-only work gets
   relevant parsing, loading and link/diff checks; do not pretend these rerun application behavior.
6. The integration owner alone combines changes and performs already-authorized releases, using safe
   merge minutes and exact-commit production verification when a watched path changes. A failed check
   is not waived because a stronger model recommended the patch. Do not add another generic approval
   step to releases already covered by the owner's standing approval.
7. Append results and next actions to WORKLOG newest-first; update the existing queue item. Keep blocked
   distinct from complete. Record the evidence timestamp in Pacific and the source's original timezone.

Role prompts are instructions, not a security boundary. A shared workspace or inherited connector can
expose more capability than the role needs. Do not claim read-only enforcement without verifying actual
tool/host restrictions. No global approval, sandbox, connector, hook or credential setting is changed here.

## Configuration and portability

Project configuration lives under `.codex/`; its exact supported layout and parser checks are recorded
in the setup entry in WORKLOG. The installed CLI during setup was **0.159.2**. Only use files accepted
by that CLI's strict loader; the chat host may use its own agent configuration instead.

The project files set the default developer/spawned model to Sol and cap spawned concurrency at three
(the primary thread is separate). Named roles are `astra_architect` (Astra/high), `sol_implementer`
(Sol/medium) and `luna_extractor` (Luna/medium), in `.codex/agents/`. Their prompts require the common
handoff and prohibit workers from independently committing, deploying or changing financial settings.
They do not run continuously or create new Railway services. Available roles still need a task from
the lead; concurrency is a limit, not a requirement to spawn three workers for every request.

For an explicit interactive model choice, the installed CLI accepts:

```bash
codex -m gpt-6.1-sol
codex -m gpt-6-astra
codex -m gpt-6-luna
```

Run from the intended checkout and supply the bounded task. These commands choose a model; they do
not transfer account permissions, preserve an omitted conversation, or configure the Railway bot.
Do not launch multiple writers on the same checkout. Resume an existing task with the host's session
continuation facility and the saved handoff rather than reconstructing it from memory.

The installed `--profile` help uses `$CODEX_HOME/<name>.config.toml`; do not copy legacy nested-profile
examples into this project without checking the actual version. Project settings can also depend on
host trust/loading policy. No global model default is overwritten, and an already-running chat does
not automatically switch its root model when a repository file changes.

**Setup receipt in this managed shell:** the loader initially marked this checkout untrusted. The
owner explicitly authorized the repository permission change. After a non-mutating check proved the
effective user configuration layer was empty, the supported version-guarded configuration writer
created only `projects."/workspace/nightcrawler".trust_level = "trusted"`. Re-reading showed the
project layer enabled with the Sol default and three-worker limit. Root independently verified the
user file has only the project trust setting, with no global model, approval or sandbox override.
The earlier missing-file check was resolved through that supported API, not by replacing unknown
settings. The named-role discovery result is recorded in WORKLOG. Other machines/checkouts need their
own normal host trust/configuration setup; no permission setting is exported in this repository.
All three requested models also successfully received work directly in this chat. Its existing root
model is unchanged; project defaults apply when the relevant host loads them for a new session.

The standalone role files passed TOML/schema/catalog checks, but automatic role application in the
local CLI is **not yet verified**. A bounded read-only, ephemeral role-launch smoke check on October 14
failed before model generation: the CLI access token could not refresh because its account had been
logged out or changed. The process exited 1; no custom worker was started. That CLI session needs the
normal sign-in refresh before repeating the smoke check. Do not ask for credential values in chat or
confuse this separate CLI login with the working ChatGPT/GitHub connections. Until verified, use the
already-working explicit model delegation in this chat rather than asserting local role discovery.

## Measure whether this helps

For meaningful tasks, keep requested model/effort, scope, elapsed time, available usage/cost receipts,
defects caught, test results and rework in the handoff. Compare like-for-like tasks without disclosing
held-out strategy outcomes. Do not invent token costs when the host does not expose them. Prefer fewer
agents if extra coordination costs more than it saves. Model quality cannot replace missing market data.

Official references checked October 14, 2026:

- [Model selection](https://developers.openai.com/api/docs/guides/model-selection): starting guidance;
  actual usefulness needs task-specific evaluation.
- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) and
  [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference): verify against
  the installed CLI rather than assuming old configuration examples still apply.
- [Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview): managed development
  sessions are available, but moving this bot into them is neither needed nor performed. API/tools/
  sandbox billing is separate from evidence that a trading strategy works.
