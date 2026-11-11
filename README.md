# Finance Manager

A personal finance manager that puts your net worth, accounts, shared bills, investments, expenses, budgets and monthly reports in one place. It runs on your own computer, and your data never leaves it.

_Work in progress: see [docs/PLAN.md](docs/PLAN.md) for the roadmap and [docs/PROGRESS.md](docs/PROGRESS.md) for current status._

## Requirements

- Python 3.11 or newer
- Git

## Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/PeachMenor/Finance-Manager.git
   cd Finance-Manager
   ```
2. Create your local config from the template:
   ```bash
   cp .env.example .env
   ```
3. Open `.env` and fill in your own keys and account details.
4. Install the backend:
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
5. Run the tests to check everything works:
   ```bash
   pytest
   ```
6. Try it with fake data (no keys needed). This loads demo banks and Splitwise balances into a separate `data/demo.db` and prints your "net worth" with a self-check:
   ```bash
   python -m app.cli demo
   ```
7. Optional, once you have Plaid **sandbox** keys in `.env` (`PLAID_ENV=sandbox`): link Plaid's fake test bank and sync it:
   ```bash
   python -m app.cli plaid-sandbox-check
   ```
8. Record who owes whom (Splitwise). Create `data/splitwise_balances.json` (git-ignored) from your Splitwise friends list; positive = they owe you, negative = you owe them:
   ```json
   {"as_of": "2026-11-13", "people": [{"name": "Alex", "amount": 40.00}, {"name": "Sam", "amount": -25.50}]}
   ```
   Then load it and see your totals:
   ```bash
   python -m app.cli people-import ../data/splitwise_balances.json
   python -m app.cli summary
   ```
   To give an account a clearer name (kept across syncs), list ids and rename:
   ```bash
   python -m app.cli accounts
   python -m app.cli rename 3 "Travel Card"
   ```
   Loans with no bank connection: enter the figures from a statement, and the app estimates the balance after each monthly payment (enter a newer statement any time to reset it):
   ```bash
   python -m app.cli loan-set --name "Car loan" --institution "Example Auto Finance" \
     --balance 15000.00 --as-of 2026-11-01 --apr 5.49 --payment 450.00 --day 15
   python -m app.cli loans
   ```
   If your payments to the lender show up in a linked bank account, let the app follow them (daily interest, any amount, any date) instead of assuming one payment a month:
   ```bash
   python -m app.cli loan-set ... --payment-match "Example Auto Finance" --posting-lag 1 \
     --unpaid-interest 0.00   # interest still owed on the statement date, if any
   ```
9. Start the server (from `backend/`):
   ```bash
   uvicorn app.main:app --reload
   ```
   - **Dashboard:** open http://localhost:8000/ for net worth, accounts by group, credit cards and loans, who owes whom, accounts shown but not counted, and net worth over time.
   - **Link accounts:** open http://localhost:8000/link and use the buttons. Plaid's own secure window opens and you sign in to your bank there; this app never sees your bank password.
   - **API:** http://localhost:8000/docs (`/accounts`, `/summary`, `/plaid/...`).
   - **Automatic sync:** while the server runs it syncs every login shortly after starting and then every 6 hours (`FM_AUTO_SYNC_HOURS` in `.env`; `0` turns it off). "Sync now" on the link page syncs immediately. New transactions appear once they post at the bank (usually within a day); pending charges are skipped.
   - **Keep it local:** never start the server with `--host 0.0.0.0`. It has no login and holds your financial data; it also rejects requests not addressed to `localhost`/`127.0.0.1`.

### Sandbox vs. real accounts

| `PLAID_ENV` in `.env` | Plaid secret to use | Database |
|---|---|---|
| `sandbox` | Sandbox secret | `data/sandbox.db` (fake banks; sign in with `user_good` / `pass_good`) |
| `production` | Production secret | `data/finance.db` (your real accounts) |

The two never mix. Restart the server after changing `.env`.

Some large banks and brokerages connect through their own sign-in page (OAuth). Plaid may ask you to complete your app and company profile in the Plaid Dashboard before those institutions appear, and approval can take a few days.

## Project layout

```
backend/app/
  config.py        settings from .env
  db/              database setup and tables
  integrations/    one module per data source (bank aggregator, Splitwise, CSV...)
  services/        calculations (money helpers, net worth, budgets, reports)
  main.py          API routes
backend/tests/     automated tests (use a throwaway database)
docs/              plan and progress tracker
```

## Privacy

Your API keys, passwords, and financial data stay on your machine:

- `.env` holds your secrets and is git-ignored — never commit it.
- Exported statements, spreadsheets, and local databases (`data/`, `*.csv`, `*.db`, …) are git-ignored too.
