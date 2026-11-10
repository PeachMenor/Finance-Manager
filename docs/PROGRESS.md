# Progress

Checklist for Phase 1 (see [PLAN.md](PLAN.md)). 🧑 = needs you · 🤖 = Claude.
Personal details (which banks, balances, budgets) are **not** recorded here. This file is public.

## Stage 1 — Connect accounts

- [x] 🤖 Repo, `.gitignore` for secrets/data, `.env.example`, README skeleton
- [x] 🧑 Approve Phase 1 plan
- [x] 🤖 Backend skeleton: config, database, data models, health API, tests
- [ ] 🧑 List where your money lives (in chat, not in the repo)
- [ ] 🤖 Report what can be synced, imported, or not connected
- [ ] 🧑 Sign up for the chosen aggregator and Splitwise API; put keys in `.env`
- [ ] 🧑 Link bank logins on the aggregator's own page
- [ ] 🤖 Sync code for each integration
- [ ] 🤖 CSV import for unsupported accounts
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
