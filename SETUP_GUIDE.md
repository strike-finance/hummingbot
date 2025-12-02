# Strike Perpetual + Hummingbot Setup Guide

Complete guide to set up Strike V2 backend with Hummingbot market making bot.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Backend Setup](#backend-setup)
3. [Account Creation](#account-creation)
4. [API Key Configuration](#api-key-configuration)
5. [Account Funding](#account-funding)
6. [Order Book Initialization](#order-book-initialization)
7. [Hummingbot Connection](#hummingbot-connection)
8. [Verification](#verification)
9. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- Docker and Docker Compose installed
- Python 3.10+ installed
- Strike V2 backend repository cloned
- Hummingbot repository cloned

---

## Backend Setup

### 1. Start Strike V2 Services

```bash
cd /path/to/strike-v2-backend

# Start all services
docker-compose -f docker-compose.local.yml up -d

# Wait for services to initialize (health checks)
sleep 15

# Verify all services are running
docker-compose ps
```

**Expected Services:**
- `strike-api-local` (port 8080) - Trading API
- `strike-price-local` (port 8082) - Market data
- `strike-userstream-local` (port 8083) - WebSocket events
- `strike-engines-local` (port 8081) - Matching engine
- `strike-postgres-local` (port 5432) - Database
- `strike-redis-local` (port 6379) - Cache

---

## Account Creation

### Option A: Using Database (Development/Testing)

For testing, you can use a pre-configured account:

```bash
ACCOUNT_ID="0199f06b-911f-7ce8-987d-c2ff4798a06c"
```

This account is already configured in the local development environment.

### Option B: Wallet Authentication (Production)

For production, create an account with Cardano wallet authentication:

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
# (Use your wallet software to sign the challenge message)

# 3. Verify signature and get JWT token
curl -X POST http://localhost:8080/auth/verify-signature \
  -H "Content-Type: application/json" \
  -d '{
    "blockchain": "cardano",
    "blockchain_address": "addr_test1qz...",
    "signature": "YOUR_WALLET_SIGNATURE",
    "challenge": "CHALLENGE_FROM_STEP_1"
  }'

# Response: { "token": "eyJhbGc...", "account_id": "019xxx..." }

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

---

## API Key Configuration

Strike V2 uses API key authentication for bot trading. There are three key types:

### API Key Scopes

| Scope | Access | Use Case |
|-------|--------|----------|
| `admin` | Admin endpoints only | Deposits, market management |
| `bot` | Trading endpoints only | **Hummingbot market making** |
| `both` | All endpoints | Superuser access |

### Current Test Credentials

For development/testing, use these pre-configured credentials:

```bash
# Account ID
ACCOUNT_ID="0199f06b-911f-7ce8-987d-c2ff4798a06c"

# Bot API Key (for Hummingbot trading)
BOT_API_KEY="sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o"

# Admin API Key (for deposits)
ADMIN_API_KEY="sk_admin_6zPzQvcvafME2P83Tk7BRvtc_e6n5X064OHibc317sY"
```

### Adding New API Keys

To create a new API key, add it to the database:

```bash
# Generate a new key
NEW_KEY="sk_bot_$(openssl rand -base64 32 | tr -d /=+ | cut -c1-40)"

# Insert into database
docker exec strike-postgres-local psql -U strike -d strike_db -c "
INSERT INTO api_keys (key, scope, account_id, name, created_at)
VALUES (
  '$NEW_KEY',
  'bot',
  '0199f06b-911f-7ce8-987d-c2ff4798a06c',
  'My Hummingbot Bot',
  NOW()
);"

# Restart API service to load the key
docker-compose -f docker-compose.local.yml restart api engines

echo "New API Key: $NEW_KEY"
```

---

## Account Funding

Fund your account using the admin deposit API:

```bash
# Using admin API key
curl -X POST http://localhost:8080/admin/deposit \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk_admin_6zPzQvcvafME2P83Tk7BRvtc_e6n5X064OHibc317sY" \
  -d '{
    "account_id": "0199f06b-911f-7ce8-987d-c2ff4798a06c",
    "usd_value": "1000000.00",
    "note": "Initial funding for Hummingbot market maker"
  }'

# Wait 2 seconds for processing
sleep 2

# Verify balance
curl -H "X-API-Key: sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o" \
  "http://localhost:8080/v2/account?account_id=0199f06b-911f-7ce8-987d-c2ff4798a06c"
```

---

## Order Book Initialization

Strike V2 creates a synthetic order book, but you can add real orders for testing:

```bash
cd /path/to/strike-v2-backend

# Run order book initialization script
./scripts/init_orderbook.sh
```

This script:
- Places 10 limit orders (5 buy + 5 sell) for each symbol
- Uses mark price ± 0.2% spread
- Supports ADA-USD and BTC-USD
- Increasing order sizes

**Manual Order Placement:**

```bash
BOT_API_KEY="sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o"

# Place buy order
curl -X POST http://localhost:8080/v2/order \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $BOT_API_KEY" \
  -d '{
    "symbol": "ADA-USD",
    "side": "buy",
    "type": "limit",
    "price": "0.45",
    "size": "100",
    "time_in_force": "GTC"
  }'

# Place sell order
curl -X POST http://localhost:8080/v2/order \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $BOT_API_KEY" \
  -d '{
    "symbol": "ADA-USD",
    "side": "sell",
    "type": "limit",
    "price": "0.46",
    "size": "100",
    "time_in_force": "GTC"
  }'
```

---

## Hummingbot Connection

### 1. Start Hummingbot

```bash
cd /path/to/hummingbot

# Optional: Set password environment variable
export CONFIG_PASSWORD="your_password"

# Start Hummingbot
./bin/hummingbot.py
```

### 2. Connect to Strike

In Hummingbot CLI:

```
>>> connect strike_perpetual
```

**Enter these credentials when prompted:**

```
Strike account ID: 0199f06b-911f-7ce8-987d-c2ff4798a06c
Strike API key: sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o
Strike API base URL: http://localhost:8080
Strike WebSocket URL: ws://localhost:8083/ws
Strike Price URL: http://localhost:8082
```

*(Press Enter to use defaults for URLs)*

### 3. Create Strategy

```
>>> create

What is your market making strategy?
>>> perpetual_market_making

Enter your maker derivative connector:
>>> strike_perpetual

Enter the trading pair:
>>> ADA-USD

Enter leverage (1-100):
>>> 20

Enter bid spread (%):
>>> 1.0

Enter ask spread (%):
>>> 1.0

Enter order amount:
>>> 100

Enter order refresh time (seconds):
>>> 30
```

### 4. Start Trading

```
>>> start
>>> status
```

---

## Verification

### Check Connection

```bash
BOT_API_KEY="sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o"
ACCOUNT_ID="0199f06b-911f-7ce8-987d-c2ff4798a06c"

# 1. Check account balance
curl -H "X-API-Key: $BOT_API_KEY" \
  "http://localhost:8080/v2/account?account_id=$ACCOUNT_ID"

# 2. Check positions
curl -H "X-API-Key: $BOT_API_KEY" \
  "http://localhost:8080/v2/positions?symbol=ADA-USD"

# 3. Check open orders
curl -H "X-API-Key: $BOT_API_KEY" \
  "http://localhost:8080/v2/openOrders?symbol=ADA-USD"

# 4. Check market data (no auth required)
curl "http://localhost:8080/v2/markets"
```

### Check Hummingbot Status

In Hummingbot CLI:

```
>>> status      # Overall bot status
>>> balance     # Account balance
>>> orders      # Open orders
>>> pnl         # Profit and loss
```

---

## Troubleshooting

### Services Not Starting

```bash
# Check service logs
docker-compose -f docker-compose.local.yml logs api
docker-compose -f docker-compose.local.yml logs engines

# Restart specific service
docker-compose -f docker-compose.local.yml restart api
```

### API Key Not Working

```bash
# Verify API key is in database
docker exec strike-postgres-local psql -U strike -d strike_db -c \
  "SELECT key, scope, account_id, name FROM api_keys;"

# Restart API service to reload keys
docker-compose -f docker-compose.local.yml restart api engines

# Wait for services to be ready
sleep 10
```

### Balance Shows Zero

```bash
# Run deposit again
curl -X POST http://localhost:8080/admin/deposit \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk_admin_6zPzQvcvafME2P83Tk7BRvtc_e6n5X064OHibc317sY" \
  -d '{
    "account_id": "0199f06b-911f-7ce8-987d-c2ff4798a06c",
    "usd_value": "1000000.00",
    "note": "Retry funding"
  }'

# Check engines logs for deposit processing
docker-compose logs engines | grep -i deposit
```

### Empty Bid/Ask Prices

```bash
# Initialize order book
cd /path/to/strike-v2-backend
./scripts/init_orderbook.sh

# Verify orders were created
curl -H "X-API-Key: sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o" \
  "http://localhost:8080/v2/openOrders?symbol=ADA-USD"
```

### "No order book exists for 'ADA-USDT'"

This error is already fixed in the connector. The connector automatically converts USDT-based pairs to USD-based pairs.

**Note:** Strike uses:
- Trading Pairs: **ADA-USD**, **BTC-USD** (USD quote)
- Collateral: **USDT** (actual balance currency)
- The connector handles this conversion automatically

### Hummingbot Connection Issues

```bash
cd /path/to/hummingbot

# Clear connector cache
rm -rf conf/connectors/strike_perpetual*.yml

# Clear Python cache
find hummingbot/connector/derivative/strike_perpetual -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Reinstall
pip3 install -e .

# Restart Hummingbot
./bin/hummingbot.py
```

### Check Service Health

```bash
# API health
curl http://localhost:8080/healthz

# Price service health
curl http://localhost:8082/healthz

# Check all services
docker-compose -f docker-compose.local.yml ps
```

---

## Quick Reference

### Trading Pairs

| Symbol | Description |
|--------|-------------|
| ADA-USD | Cardano perpetual (USD quote) |
| BTC-USD | Bitcoin perpetual (USD quote) |

### Service Ports

| Service | Port | Purpose |
|---------|------|---------|
| Trading API | 8080 | Orders, account, positions |
| Price Service | 8082 | Market data, tickers |
| UserStream | 8083 | WebSocket events |
| Engines | 8081 | Matching engine |
| Postgres | 5432 | Database |
| Redis | 6379 | Cache |

### Authentication

| Method | Use Case | Header |
|--------|----------|--------|
| API Key (Bot) | Hummingbot trading | `X-API-Key: sk_bot_...` |
| API Key (Admin) | Deposits, admin ops | `X-API-Key: sk_admin_...` |
| JWT Token | Wallet users | `Authorization: Bearer eyJ...` |

### Important Notes

✅ **DO:**
- Use API key authentication for bots
- Use USD-based trading pairs (ADA-USD, BTC-USD)
- Initialize order book before testing
- Restart services after API key changes
- Monitor logs for errors

❌ **DON'T:**
- Use USDT-based pairs (connector converts automatically)
- Share API keys between bots
- Use admin keys for trading
- Skip service health checks

---

## Related Documentation

- [STRIKE_CONNECTOR_ARCHITECTURE.md](./STRIKE_CONNECTOR_ARCHITECTURE.md) - Technical deep dive
- [ORDERBOOK_SETUP.md](../strike-v2-backend/ORDERBOOK_SETUP.md) - Order book details

---

## Support

**Logs to check:**
```bash
# Hummingbot logs
tail -f logs/logs_conf_perpetual_market_making_1.log

# Strike API logs
docker-compose -f docker-compose.local.yml logs -f api

# Matching engine logs
docker-compose -f docker-compose.local.yml logs -f engines
```

**Common issues:** See [Troubleshooting](#troubleshooting) section above.

---

**Ready to trade!** Your Strike Perpetual + Hummingbot setup is complete. 🚀
