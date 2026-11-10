# Finance Manager — Phase 1 Plan

**Goal:** one app that shows your whole financial picture: net worth, every account, who owes whom, investments, credit card debt, expenses against budgets, and a monthly report.

**Status:** Approved 2026-11-10. Stage 1 in progress.
**Out of scope for now:** Phase 2 (the investment strategy quiz and auto-investing).

Legend: 🧑 = needs you · 🤖 = Claude can do it alone

---

## Guiding rules

1. **Privacy first.** The app runs on your own computer. Account data lives in a local database that is never committed. Keys live in `.env`. The public repo holds only code and docs.
2. **Read-only access.** The app never moves money. Every bank and brokerage connection uses read-only access.
3. **One stage at a time.** Each stage ends with a working, demoable feature, an updated README, and a commit. The next stage starts only after you sign off.
4. **Neat code.** Clear folders, comments explaining *why*, small modules, and tests for every money calculation.

---

## Tech stack (proposed)

| Part | Choice | Why |
|---|---|---|
| Backend | Python + FastAPI | Good for finance and data work; Phase 2 analysis will be easy in Python |
| Database | SQLite, stored locally and git-ignored | Zero setup and one file; can be encrypted later |
| Frontend | React (Vite) + a charting library | Fast dashboard with tabs and charts; runs in your browser |
| Bank and card data | **SimpleFIN Bridge** (primary) and/or **Plaid** (fallback) | Read-only aggregators for US banks, cards and brokerages. Chosen in Stage 1 based on your institutions |
| Splitwise | Official Splitwise API (personal API key) | Who owes you and whom you owe |
| Stock and ETF prices | Free market-data source (for example Yahoo Finance via `yfinance`) | Daily values for holdings |
| Anything unsupported | CSV / statement import | Fallback so no account is left out |

A phone-friendly version (installable web app) can come after Phase 1 works.

---

## Folder layout

```
Finance-Manager/
├── backend/
│   ├── app/
│   │   ├── main.py           # API entry point
│   │   ├── db/               # models + database setup
│   │   ├── integrations/     # one file per data source (simplefin, plaid, splitwise, prices, csv)
│   │   ├── services/         # calculations: net worth, budgets, reports
│   │   └── api/              # routes the dashboard calls
│   └── tests/
├── frontend/                 # React dashboard
├── docs/
│   ├── PLAN.md               # this file
│   └── PROGRESS.md           # stage checklist + decisions log
├── .env.example              # placeholder keys only
└── README.md                 # setup guide for anyone cloning the repo
```

---

## Stage 1 — Connect accounts

**Outcome:** every place your money lives is either synced automatically or importable, and stored locally.

| Step | Who |
|---|---|
| Tell me where your money lives: banks, credit cards, brokerages/retirement accounts, Splitwise, cash, anything else | 🧑 |
| Check each institution and report what can be synced automatically, what needs CSV import, and what can't be connected | 🤖 |
| Sign up for the chosen aggregator (SimpleFIN / Plaid) and Splitwise API key; paste keys into `.env` (I never see or commit them) | 🧑 |
| Link your bank logins in the aggregator's own secure page (I never handle bank passwords) | 🧑 |
| Build the project skeleton, database models (institutions, accounts, balances, transactions, holdings) and the sync code | 🤖 |
| Build CSV import for anything unsupported | 🤖 |
| "Sync now" command and a daily auto-sync | 🤖 |
| Ask you about your **annual budgets** (used in Stage 4) | 🧑🤖 |

## Stage 2 — Dashboard

**Outcome:** one screen with your live numbers.

- **Net worth** = cash + investments − credit card and other debt, updated as prices change 🤖
- **Accounts:** balance per bank account 🤖
- **People:** what you owe and what you're owed (from Splitwise) 🤖
- **Investments tab:** each stock/ETF with quantity, today's price, today's change, total value, gain/loss 🤖
- Net worth history chart 🤖
- Review the look and tell me what to change 🧑

## Stage 3 — Debts and expenses

**Outcome:** you know what you owe and where the money goes.

- Credit card balances, statement due dates, utilization 🤖
- Automatic categorization of transactions (rules you can edit) 🤖
- **Monthly expenses:** recurring bills detected (rent, subscriptions, utilities) 🤖
- **Annual expenses:** yearly items (insurance, memberships, taxes), with a monthly "set aside" amount 🤖
- Confirm categories and recurring items the app finds 🧑

## Stage 4 — Budgets

**Outcome:** spending tracked against the budgets you set in Stage 1.

- Budget per category, monthly and annual 🤖
- Progress bars and alerts when you near or pass a budget 🤖
- Set or adjust budget amounts 🧑

## Stage 5 — Monthly reports

**Outcome:** a clear report every month.

- Income (salary), expenses by category, savings and savings rate, investment contributions and growth, net worth change 🤖
- Comparison with last month and with budget 🤖
- Viewable in the app and exportable as PDF (reports are saved locally, never committed) 🤖
- Tell me what you want highlighted 🧑

---

## Tracking

`docs/PROGRESS.md` will hold a checklist per stage plus a short log of decisions. It is updated with every commit, so we always know where things stand.

## Done for Phase 1 when

All five stages work on your machine with your real accounts, the README lets someone else set it up from scratch, and no personal data is in the repo.
