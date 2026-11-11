# How accounts connect

The app is read-only. It never moves money, and it never sees your bank passwords: you link banks on the provider's own secure page, and the app only stores the access token the provider returns (in your local, git-ignored database or `.env`).

Each method below is a module in `backend/app/integrations/`.

| Method | Use it for | What it gives | Cost |
|---|---|---|---|
| **Plaid** (primary) | Most US banks, credit cards, brokerages, 401k/HSA, many loans | Balances, transactions, investment holdings | Free Trial plan for new teams (US/Canada): up to 10 linked logins ("Items"). Beyond that, a paid plan |
| **SimpleFIN Bridge** (backup) | Institutions Plaid can't reach | Balances, transactions, some holdings | About $15/year |
| **Splitwise screenshot** (current) | Shared bills | Who owes you, whom you owe | Free. Weekly: read balances off a Splitwise screenshot into `data/splitwise_balances.json`, then `python -m app.cli people-import data/splitwise_balances.json` |
| **Splitwise API** (optional) | Shared bills, automatically | Same, synced | Requires a Splitwise Pro subscription; code is ready if you ever enable it |
| **Statement import** (OFX/QFX/CSV) | Cards no aggregator supports, when the issuer lets you export statements | Transactions and balance from each monthly statement | Free |
| **Manual entry** | Things with no feed: cash balances, unvested RSUs, a loan with no connection | A balance you update; loans can be computed from balance, APR and payment | Free |

## Common gaps and workarounds

- **Card not supported by any aggregator**: if the issuer lets you export monthly statements (OFX, QFX or CSV), import those. OFX is the most reliable format.
- **Balance with PDF-only statements** (some wallet or stored-value balances): enter the balance manually.
- **Card that syncs a balance but no transactions** (this can happen after an issuer changes): use manual entry until the connection catches up.
- **Unvested stock awards (RSUs)**: aggregators usually show only vested shares. Enter grants and vesting dates manually; they are shown separately and excluded from net worth by default, since they aren't yours yet.

## Choosing Plaid vs. SimpleFIN

Plaid is the default because it covers investment holdings well and its Trial plan is free for a personal setup of up to 10 logins. One login can cover several accounts (for example, one bank login for checking and two cards). SimpleFIN is the fallback for anything Plaid can't connect.
