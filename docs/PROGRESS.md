# Progress

Checklist for Phase 1 (see [PLAN.md](PLAN.md)). 🧑 = needs you · 🤖 = Claude.
Personal details (which banks, balances, budgets) are **not** recorded here. This file is public.

## Stage 1 — Connect accounts

- [x] 🤖 Repo, `.gitignore` for secrets/data, `.env.example`, README skeleton
- [x] 🧑 Approve Phase 1 plan
- [x] 🤖 Backend skeleton: config, database, data models, health API, tests
- [x] 🧑 List where your money lives (kept in git-ignored `data/`, not in the repo)
- [x] 🤖 Report what can be synced, imported, or not connected ([INTEGRATIONS.md](INTEGRATIONS.md))
- [ ] 🧑 Sign up for Plaid (Trial plan) and Splitwise API; put keys in `.env`
- [ ] 🧑 Link bank logins on the aggregator's own page
- [x] 🤖 Sync engine (re-runs never duplicate; balance history kept) + net-worth math, tested on fake banks
- [x] 🤖 Plaid integration: balances, transactions, holdings, tested against a fake Plaid server
- [x] 🤖 Splitwise integration: owed / owing, tested against a fake Splitwise server
- [ ] 🧑 Review the fake-data demo and approve
- [ ] 🧑🤖 Live check against Plaid's sandbox (needs sandbox keys)
- [ ] 🤖 Plaid Link page so you can connect real logins
- [ ] 🤖 OFX/CSV statement import for unsupported cards
- [ ] 🤖 Manual accounts: cash balances, loans (balance/APR/payment), unvested RSUs
- [ ] 🤖 "Sync now" command + daily auto-sync
- [ ] 🧑🤖 Annual budgets questionnaire

## Stage 2 — Dashboard
- [ ] Not started

## Stage 3 — Debts and expenses
- [ ] Not started

## Stage 4 — Budgets
- [ ] Not started

## Stage 5 — Monthly reports
- [ ] Not started

---

## Decisions log

| Date | Decision | Why |
|---|---|---|
| 2026-11-10 | Repo is public; secrets in `.env`, data in git-ignored local SQLite | Keep personal data off GitHub |
| 2026-11-10 | Python/FastAPI backend, React dashboard, SQLite | Simple local setup; Python suits Phase 2 analysis |
| 2026-11-10 | Money stored as integer cents | Avoids floating-point rounding errors in sums |
| 2026-11-10 | Each data source is a separate module behind one interface | Add or swap providers (SimpleFIN, Plaid, CSV) without touching the rest |
| 2026-11-10 | Plaid is the primary aggregator; SimpleFIN is the backup | Good investment-holdings coverage; free Trial plan covers up to 10 logins |
| 2026-11-10 | Unvested RSUs are shown separately and excluded from net worth by default | They aren't owned until they vest |
