# 🤖 Hummingbot + Strike v2 Setup Guide

This guide shows you how to properly set up a Hummingbot bot account with Strike v2 using **API endpoints** (not direct Redis manipulation).

## Prerequisites

- Strike v2 backend running (`docker-compose up`)
- Admin API key configured in backend
- Bot API key created and associated with your account

## Architecture Overview

Strike v2 has three main services for Hummingbot:

```
Port 8080: Trading API     → Orders, account, positions
Port 8082: Price Service   → Market data, depth, tickers
Port 8083: UserStream      → WebSocket user events
```

## Step 1: Account Creation

Accounts must be created via the API (not Redis). You have two options:

### Option A: Using Wallet Authentication (Production)

```bash
# 1. Request signature challenge
curl -X POST http://localhost:8080/auth/request-signature \
  -H "Content-Type: application/json" \
  -d '{
    "blockchain": "cardano",
    "blockchain_address": "addr_test1qz2fxv2umyhttkxyxp8x0dlpdt3k6cwng5pxj3jhsydzer3jcu5d8ps7zex2k2xt3uqxgjqnnj83ws8lhrn493lzs9nqy3yqnz"
  }'

# Response: { "challenge": "...", "expires_at": "..." }

# 2. Sign the challenge with your Cardano wallet
# (Use your wallet to sign the challenge message)

# 3. Verify signature and get JWT token
curl -X POST http://localhost:8080/auth/verify-signature \
  -H "Content-Type: application/json" \
  -d '{
    "blockchain": "cardano",
    "blockchain_address": "addr_test1qz...",
    "signature": "YOUR_WALLET_SIGNATURE",
    "challenge": "CHALLENGE_FROM_STEP_1"
  }'

# Response: { "token": "eyJhbGc...", "account_id": "..." }

# 4. Create account using JWT token
curl -X POST http://localhost:8080/v2/account \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "blockchain": "cardano",
    "blockchain_address": "addr_test1qz...",
    "type": "normal",
    "fee_bracket_id": 0
  }'
```

### Option B: Direct Account Creation (Testing/Development)

For testing, if you have direct access to the engines service or database, you can create accounts directly. Contact your system administrator.

## Step 2: Fund the Account

Once the account exists, use the admin API to deposit initial funds:

```bash
# Fund account with $10,000 USDT
curl -X POST http://localhost:8080/admin/deposit \
  -H "Content-Type: application/json" \
  -H "X-API-Key: admin-dev-key-12345" \
  -d '{
    "account_id": "0199f06b-911f-7ce8-987d-c2ff4798a06c",
    "usd_value": "10000.00",
    "note": "Initial funding for Hummingbot MM"
  }'
```

## Step 3: Create Bot API Key

Bot API keys should be created in the backend configuration (`config.local.toml`):

```toml
# services/api/config/config.local.toml
[[admin.api_keys]]
key = "hummingbot-mm-key-67890"
scope = "bot"
account_id = "0199f06b-911f-7ce8-987d-c2ff4798a06c"
```

**Scopes:**
- `bot`: Can trade (create/cancel orders, view positions)
- `admin`: Can do admin operations (deposits, market updates)
- `both`: Full access

Restart the API service after adding the key:
```bash
docker-compose restart api
```

## Step 4: Verify Setup

```bash
# Check account balance
curl -H "X-API-Key: hummingbot-mm-key-67890" \
  "http://localhost:8080/v2/account?account_id=0199f06b-911f-7ce8-987d-c2ff4798a06c"

# Check positions
curl -H "X-API-Key: hummingbot-mm-key-67890" \
  "http://localhost:8080/v2/positions?symbol=ADA-USDT"

# Test market data (no auth needed)
curl "http://localhost:8082/v2/depth?symbol=ADA-USDT&limit=10"
```

## Step 5: Connect Hummingbot

```bash
cd /Users/hoangvu/hade/strike/hummingbot
./bin/hummingbot.py
```

In Hummingbot CLI:
```
>>> connect strike_perpetual
```

**Enter credentials:**
- Strike account ID: `0199f06b-911f-7ce8-987d-c2ff4798a06c`
- Strike API key: `hummingbot-mm-key-67890`
- Strike API base URL: `http://localhost:8080` (press Enter for default)
- Strike WebSocket URL: `ws://localhost:8083/ws` (press Enter for default)
- Strike Price URL: `http://localhost:8082` (press Enter for default)

**Verify connection:**
```
>>> status
>>> balance
```

## Automated Setup Script

We provide a helper script that automates the funding step (assumes account already exists):

```bash
cd /Users/hoangvu/hade/strike/strike-v2-backend

# Make script executable
chmod +x scripts/setup-hummingbot-account.sh

# Run setup (funds existing account)
./scripts/setup-hummingbot-account.sh
```

The script will:
1. Check if account exists
2. Fund it with $10,000 via admin deposit API
3. Verify the balance

## API Key Authentication Flow

When Hummingbot makes requests:

```
Trading Requests (Port 8080):
  POST /v2/order
  Headers: X-API-Key: hummingbot-mm-key-67890

  → API checks key in config
  → Finds account_id: 0199f06b-911f-7ce8-987d-c2ff4798a06c
  → Executes order for that account

Market Data (Port 8082):
  GET /v2/depth?symbol=ADA-USDT
  No auth required - public data

User Events (Port 8083):
  WebSocket: ws://localhost:8083/ws
  Subscribe with account_id in message
```

## Troubleshooting

### Account not found
- Make sure account was created via `/v2/account` endpoint
- Check account exists: `curl -H "X-API-Key: ..." http://localhost:8080/v2/account?account_id=...`

### API key not working
- Verify key is in `services/api/config/config.local.toml`
- Restart API service: `docker-compose restart api`
- Check scope is `bot` or `both`

### Balance is zero
- Run admin deposit: `POST /admin/deposit` with admin API key
- Wait 1-2 seconds for engines to process
- Check again: `GET /v2/account`

### Market data not loading
- Verify price service is running: `curl http://localhost:8082/healthz`
- Check market exists: `curl http://localhost:8082/v2/exchangeInfo`

## Important Notes

✅ **DO**: Use API endpoints for all operations
✅ **DO**: Keep API keys in configuration files
✅ **DO**: Use admin deposit API for funding
✅ **DO**: Verify setup before running strategies

❌ **DON'T**: Write directly to Redis (bypasses validation)
❌ **DON'T**: Share API keys (each bot should have its own)
❌ **DON'T**: Use admin keys for trading (use bot scope)

## Next Steps

Once connected, you can:

1. **Create a strategy:**
   ```
   >>> create
   Strategy: perpetual_market_making
   Exchange: strike_perpetual
   Trading pair: ADA-USDT
   ```

2. **Start trading:**
   ```
   >>> start
   >>> status
   ```

3. **Monitor performance:**
   ```
   >>> balance
   >>> orders
   >>> pnl
   ```

For more help, see `STRIKE_QUICKSTART.md` in this directory.
