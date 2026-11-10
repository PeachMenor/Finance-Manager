# How accounts connect

The app is read-only. It never moves money, and it never sees your bank passwords: you link banks on the provider's own secure page, and the app only stores the access token the provider returns (in your local, git-ignored database or `.env`).

Each method below is a module in `backend/app/integrations/`.

| Method | Use it for | What it gives | Cost |
|---|---|---|---|
| **Plaid** (primary) | Most US banks, credit cards, brokerages, 401k/HSA, many loans | Balances, transactions, investment holdings | Free Trial plan for new teams (US/Canada): up to 10 linked logins ("Items"). Beyond that, a paid plan |
| **SimpleFIN Bridge** (backup) | Institutions Plaid can't reach | Balances, transactions, some holdings | About $15/year |
| **Splitwise screenshot** (current) | Shared bills | Who owes you, whom you owe | Free. Weekly: read balances off a Splitwise screenshot into `data/splitwise_balances.json`, then `python -m app.cli people-import data/splitwise_balances.json` |
| **Splitwise API** (optional) | Shared bills, automatically | Same, synced | Requires a Splitwise Pro subscription; code is ready if you ever enable it |
| **Statement import** (OFX/QFX/CSV) | Cards with no aggregator support (for example Apple Card, which exports from the Wallet app) | Transactions and balance from each monthly statement | Free |
| **Manual entry** | Things with no feed: cash balances, unvested RSUs, a loan with no connection | A balance you update; loans can be computed from balance, APR and payment | Free |

## Known gaps (as of November 2026)

- **Apple Card**: no aggregator support. Export each monthly statement from Wallet (Wallet → Apple Card → Card Balance → statement → Export Transactions → OFX) and import it.
- **Apple Cash**: statements are PDF only, so enter the balance manually.
- **Bilt 2.0 cards** (issued by Column N.A.): Plaid lists support, but users report missing transactions since the 2026 card switch. Fallback: manual entry.
- **Unvested RSUs**: aggregators usually show only vested shares. Enter grants and vesting dates manually; they are shown separately and excluded from net worth by default, since they aren't yours yet.

## Choosing Plaid vs. SimpleFIN

Plaid is the default because it covers investment holdings well and its Trial plan is free for a personal setup of up to 10 logins. One login can cover several accounts (for example, one bank login for checking and two cards). SimpleFIN is the fallback for anything Plaid can't connect.
