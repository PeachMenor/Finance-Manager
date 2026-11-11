# Progress

Checklist for Phase 1 (see [PLAN.md](PLAN.md)). 🧑 = needs you · 🤖 = Claude.
Personal details (which banks, balances, budgets) are **not** recorded here. This file is public.

## Stage 1 — Connect accounts

- [x] 🤖 Repo, `.gitignore` for secrets/data, `.env.example`, README skeleton
- [x] 🧑 Approve Phase 1 plan
- [x] 🤖 Backend skeleton: config, database, data models, health API, tests
- [x] 🧑 List where your money lives (kept in git-ignored `data/`, not in the repo)
- [x] 🤖 Report what can be synced, imported, or not connected ([INTEGRATIONS.md](INTEGRATIONS.md))
- [x] 🧑 Sign up for Plaid (Trial plan); sandbox keys in `.env` (Splitwise: screenshot instead)
- [ ] 🧑 Link bank logins on the aggregator's own page
- [x] 🤖 Sync engine (re-runs never duplicate; balance history kept) + net-worth math, tested on fake banks
- [x] 🤖 Plaid integration: balances, transactions, holdings, tested against a fake Plaid server
- [x] 🤖 Splitwise integration: owed / owing, tested against a fake Splitwise server (API needs Pro, so unused for now)
- [x] 🤖 Weekly Splitwise screenshot import (`people-import`)
- [x] 🧑 Review the fake-data demo and approve (2026-11-10)
- [x] 🧑🤖 Live check against Plaid's sandbox: 14 accounts, transactions and 13 holdings synced; totals verified
- [x] 🤖 Plaid Link page (`/link`): link, sync now, unlink; verified against Plaid sandbox in the browser
- [x] 🤖 Sandbox and real data kept in separate databases; server only answers to localhost
- [x] 🧑 Switch to Plaid production (production secret, `PLAID_ENV=production`)
- [ ] 🧑 Link real logins (checklist kept privately in `data/my-accounts.md`)
- [x] 🤖 Clear account names: bank's product name + last 4 digits; nicknames that sync never overwrites
- [ ] 🤖 Renew-in-place for expiring bank permissions (Plaid update mode), before relinking is ever needed
- [ ] 🤖 OFX/CSV statement import for unsupported cards
- [x] 🤖 Hand-entered loans: statement balance + APR + payment, estimated after each payment, refreshed on every sync
- [x] 🤖 Hide accounts from lists (still counted in net worth)
- [ ] 🧑🤖 Enter the car loan from its statement
- [ ] 🤖 Manual accounts: cash balances, unvested RSUs
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
| 2026-11-10 | Splitwise balances come from a weekly screenshot, not the API | The API requires a paid Pro subscription |
| 2026-11-10 | Demo commands refuse to wipe any database except `data/demo.db` | A sandbox run once wrote to the real database file; guard prevents it |
| 2026-11-10 | Dashboard is one simple page; per-stock investments tab with daily prices deferred | User priority: see net worth, loans, expenses and savings at once first |
| 2026-11-10 | `PLAID_ENV` picks the database: sandbox → `sandbox.db`, production → `finance.db` | Fake test banks can never land in real data |
| 2026-11-10 | Link page offers "bank/card" and "investment" buttons | Plaid hides institutions that lack the required product; investment-only logins need their own option |
