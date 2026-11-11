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
- [x] 🧑🤖 Enter the car loan from its statement
- [x] 🤖 Loan payment tracking: payments found in bank transactions, daily interest, unpaid interest carried; verified privately against a real statement
- [ ] 🤖 Manual accounts: cash balances, unvested RSUs
- [x] 🤖 Automatic sync while the server runs (on start + every 6 hours, configurable), plus "Sync now"; status shown on the link page
- [x] 🤖 Exclude accounts from net worth (`exclude` / `include`), e.g. unvested stock awards
- [ ] 🧑🤖 Annual budgets questionnaire

## Stage 2 — Dashboard
- [x] 🤖 One-page dashboard at `/`: net worth (assets, liabilities, Splitwise), cash & savings, investments, credit cards, loans with terms, people, shown-not-counted, spending placeholder
- [x] 🤖 Net worth over time (daily, from balance history; today always matches the headline), hover tooltip and table view
- [x] 🤖 Light/dark, works at phone width; Sync now on the dashboard
- [x] 🤖 Redesign ("Ledger"): KPI strip (net worth, spent this month, savings rate, debts), monthly spending bars with savings rate per month, category donut for the selected month, accounts ledger
- [x] 🤖 Transaction categories stored from the bank feed; spending/income/transfer rules (card and loan payments, transfers never count as spending)
- [x] 🧑 Review the look (approved 2026-11-10; further tweaks as they come)

## Stage 3 — Debts and expenses
- [x] 🤖 Shared expenses count only your share: Splitwise expenses matched to bank/card charges (same amount, up to 31 days before / 7 after); expenses others paid add your share; settle-ups stay transfers
- [x] 🧑 First Splitwise exports and balances imported (November)
- [x] 🤖 Rent payments split into base rent and utilities billed with it (`rent_base`)
- [x] 🤖 Weekly settle-up nudge (`nudge` command; scheduled phone notification)
- [ ] 🧑 Earlier months' Splitwise exports (so earlier rent and shared costs count only your share)
- [x] 🤖 Recurring monthly bills detection (steady price, one price change allowed; habits excluded) + hand-added bills; dashboard section
- [x] 🤖 Loan payments and steady investing transfers shown as their own recurring groups (not spending)
- [x] 🧑 Phone-plan share confirmed and added by hand
- [ ] 🧑 Apple Card statements (purchases currently missing: only card payments are visible)
- [ ] 🤖 Annual expenses with monthly set-aside
- [ ] 🤖 Credit card due dates and utilization
- [x] 🧑🤖 Category corrections you can make (`txn-find`, `categorize` with notes); Education category added
- [x] 🤖 Household rent rule: fixed rent share every month; utilities billed with rent at your share; unexplained extras flagged
- [ ] 🧑 Explain the flagged extra on one rent payment

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
| 2026-11-10 | Hand-entered loans follow actual payments from bank transactions with daily interest | Payments are irregular; simple-interest lenders accrue daily |
| 2026-11-10 | Expenses count only your share; card bill payments, settle-ups and loan principal are transfers | Shared purchases on a card would otherwise inflate spending |
| 2026-11-10 | 401k and unvested stock awards are shown on the dashboard but not counted in net worth | Net worth should reflect money available outside retirement and unvested awards |
| 2026-11-10 | Dashboard is plain HTML/JS served by the backend, not React | Simpler setup (no Node build), nothing external to load; enough for one page |
| 2026-11-10 | Categories: Rent, Food, Shopping, Transport, Entertainment, Travel, Bills & utilities, Other, in a fixed order with fixed colours | Colour follows the category across months; validated colour-blind-safe palette |
| 2026-11-10 | Headline savings rate uses the last complete month | The current month is still in progress |
| 2026-11-10 | Splitwise balances stay in net worth (owed to you − you owe) | User's choice: money owed to you counts as yours |
| 2026-11-10 | Rent = fixed monthly share, regardless of who paid the landlord | Rent payments and housemate settle-ups move irregularly between people |
| 2026-11-10 | Private settings (labels, household rule) live in the data folder; tests use an empty temp one | Tests must never read real personal files |
| 2026-11-10 | `PLAID_ENV` picks the database: sandbox → `sandbox.db`, production → `finance.db` | Fake test banks can never land in real data |
| 2026-11-10 | Link page offers "bank/card" and "investment" buttons | Plaid hides institutions that lack the required product; investment-only logins need their own option |
