# Finance Manager — Phase 1 Plan

**Goal:** one app that shows your whole financial picture: net worth, every account, who owes whom, investments, credit card debt, expenses against budgets, and a monthly report.

**Status:** Approved 2026-11-10. Stage 1 in progress.
**Out of scope for now:** Phase 2 (the investment strategy quiz and auto-investing), and the per-stock investments tab with daily prices (added after Phase 1 works).

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

**Outcome:** one simple screen showing everything at once. These are must-haves:

- **Net worth** = cash + savings + investment account balances − credit cards − loans ± Splitwise 🤖
- **Accounts:** balance per bank, savings and investment account (investment accounts as one total each, as reported on each sync) 🤖
- **Loans and card debt:** what's owed on each card and loan 🤖
- **Expenses:** this month's spending, monthly and annual expenses (filled in by Stage 3) 🤖
- **Savings:** savings balances and how much you saved this month 🤖
- **People:** what you owe and what you're owed (from Splitwise screenshots) 🤖
- **Shown but not counted in net worth:** retirement accounts (401k), unvested stock awards and the HSA each appear with their current value in their own section, so they're visible without inflating net worth. Which accounts count is a per-account switch (`exclude` / `include`) 🤖
- Net worth history chart 🤖
- Review the look and tell me what to change 🧑

**Later (not Phase 1 must-have):** a separate investments tab with each stock/ETF, daily prices, daily change and gain/loss. Holdings already sync, so it can be added without rework.

## Stage 3 — Debts and expenses

**Outcome:** you know what you owe and where the money goes.

- Credit card balances, statement due dates, utilization 🤖
- Automatic categorization of transactions (rules you can edit) 🤖
- **Monthly expenses:** recurring bills detected (rent, subscriptions, utilities) 🤖
- **Annual expenses:** yearly items (insurance, memberships, taxes), with a monthly "set aside" amount 🤖
- Confirm categories and recurring items the app finds 🧑

**Counting only YOUR share of spending** (must-have):

| Money movement | Counted as |
|---|---|
| Card or bank purchase, not shared | Your expense (full amount) |
| Purchase you paid for and split on Splitwise | Your expense = **your share only**; the rest is money owed to you, not spending |
| Expense someone else paid, split with you on Splitwise | Your expense = your share (even though no card charge) |
| Paying a credit card bill from checking | Transfer, **not** an expense (the card purchases already counted) |
| Splitwise settle-up you send or receive (Venmo, Zelle, ...) | Transfer, not an expense or income |
| Loan payment | Interest = expense; principal = transfer (reduces the loan) |
| Moving money between your own accounts | Transfer |

- Splitwise expenses are matched to card/bank transactions by date (± a few days) and the amount you paid 🤖
- Needs the Splitwise **expense list** (who paid, total, your share), not only the friends balances: share screenshots of the activity/expense list weekly 🧑
- Anything that can't be matched automatically is listed for you to confirm 🧑

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
