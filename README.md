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
6. Start the server (from `backend/`):
   ```bash
   uvicorn app.main:app --reload
   ```
   Open http://127.0.0.1:8000/docs to see the API. Your database is created at `data/finance.db`.

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
