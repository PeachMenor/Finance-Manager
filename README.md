# Finance Manager

A personal finance manager. _(Work in progress — features will be listed here as they are built.)_

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

_(Install and run steps will be added as the project grows.)_

## Privacy

Your API keys, passwords, and financial data stay on your machine:

- `.env` holds your secrets and is git-ignored — never commit it.
- Exported statements, spreadsheets, and local databases (`data/`, `*.csv`, `*.db`, …) are git-ignored too.
