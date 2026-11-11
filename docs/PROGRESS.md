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
- [x] 🤖 Weekly settle-up nudge (`nudge` command); Friday 6 PM phone reminder to pay one person (`--pay-one`, biggest first)
- [x] 🤖 Reminder asks "Did you pay?"; only an explicit yes records it (`people-settle`), updating balances and logging the payment
- [x] 🧑 Splitwise: weekly Friday screenshots of balances (earlier months not needed; rent handled by the household rule)
- [x] 🤖 Recurring monthly bills detection (steady price, one price change allowed; habits excluded) + hand-added bills; dashboard section
- [x] 🤖 Loan payments and steady investing transfers shown as their own recurring groups (not spending)
- [x] 🧑 Phone-plan share confirmed and added by hand
- [x] 🧑 Apple Card statements: not needed (no recurring charges on it); its purchases stay out of spending
- [x] 🧑🤖 Annual / periodic expenses: added by hand as they come (tuition, bonus etc.)
- [x] Credit card due dates and utilization: dropped (optional, not needed)
- [x] 🧑🤖 Category corrections you can make (`txn-find`, `categorize` with notes); Education category added
- [x] 🤖 Household rent rule: fixed rent share every month; utilities billed with rent at your share; unexplained extras flagged
- [x] 🧑🤖 Flagged rent extra explained and split (`split-txn`)
- [x] 🤖 Upcoming periodic expenses (semester / quarterly / yearly) with monthly set-aside ("Coming up")
- [x] 🤖 Categories: "Other" broken out into Health & care, Bills & subscriptions (insurance, software); Transport & travel merged
- [x] 🤖 Recurring income: paychecks (biweekly), interest; expected bonuses; bills marked paid this month
- [x] 🤖 Dashboard: selected month drives the headline figures; owed in green / owe in red; tabs between Ledger and Linked accounts
- [x] 🧑 Tuition and bonus: added when they arrive, not estimated ahead (placeholders removed)

## Stage 4 — Budgets
- [x] 🧑 Budget year set: Nov 10 to Nov 9 (first year: Nov 10, 2026 – Nov 9, 2027)
- [x] 🧑 Budgets given: eating out, groceries, fuel, subscriptions (monthly); travel, personal care & shopping, health care, education (yearly)
- [x] 🤖 Categories reshaped around the budgets (Food & groceries, Personal care & shopping, Health care) with finer lines (groceries, fuel)
- [x] 🤖 Budget tracking: monthly caps (first month pro-rated), yearly pace, statuses; dashboard section and `budgets` command
- [x] 🤖 Budget year so far: income, expenses, saved, invested; month-by-month table with biggest swings
- [x] 🤖 Deposits that need explaining (e.g. employer reimbursements) listed; reimbursements reduce their expense category
- [x] 🧑 Tracking starts Nov 1, 2026: the dashboard shows nothing earlier
- [ ] 🤖 Alerts when a budget is near or over (e.g. in the weekly nudge)

## Stage 5 — Monthly reports
- [x] 🤖 Monthly PDF report: income, expenses, saved, net worth, chosen account values; vs previous month and season; spending by category; budgets; highlights
- [x] 🧑 Accounts in the report and delivery email chosen (private)
- [x] 🤖 Scheduled on the 1st of every month: PDF to phone (Remote Control) and email, plus a notification; first run Dec 1, 2026 for November
- [ ] 🧑 Review the first real report (Dec 1)

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
| 2026-11-10 | 8 coloured categories + Other (Transport & travel merged; Health & care added) | The validated palette has 8 distinguishable colours |
| 2026-11-10 | Stage 3 closed without card due dates, Apple Card import or earlier Splitwise months | Not needed: no recurring charges on Apple Card; Splitwise kept current weekly |
| 2026-11-10 | Budget year runs Nov 10 – Nov 9 | Starts from the day budgets are set up |
| 2026-11-10 | Budget lines are finer slices of the 8 chart categories (e.g. groceries inside Food & groceries) | Budgets need more detail than a readable chart can colour |
| 2026-11-10 | Superstores (e.g. warehouse clubs) count as groceries; their fuel counts as fuel | Mostly food staples; changeable per transaction |
| 2026-11-10 | Budget year counts 12 rent months (those starting inside the year) | A year starting mid-month shouldn't include that month's rent |
| 2026-11-10 | Employer reimbursements reduce the expense they repay, not counted as income | Keeps both income and spending honest |
| 2026-11-10 | Dashboard starts at a tracking start date (Nov 1, 2026); older data kept but hidden | Easier to track going forward; bill detection still needs past charges |
| 2026-11-11 | Report net worth includes latest Splitwise balances | Matches the dashboard's net worth formula |
| 2026-11-11 | Seasons: Winter Dec–Feb, Spring Mar–May, Summer Jun–Aug, Fall Sep–Nov | Compares like-for-like quarters of the year |
| 2026-11-10 | `PLAID_ENV` picks the database: sandbox → `sandbox.db`, production → `finance.db` | Fake test banks can never land in real data |
| 2026-11-10 | Link page offers "bank/card" and "investment" buttons | Plaid hides institutions that lack the required product; investment-only logins need their own option |
