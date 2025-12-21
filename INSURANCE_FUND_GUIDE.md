# Insurance Fund - Hummingbot Setup Guide

Complete guide for running the Strike Insurance Fund unwinding strategy in Hummingbot.

## ✅ Prerequisites

- Strike V2 backend running (`docker-compose -f docker-compose.local.yml up -d`)
- Database initialized (`goose up`)
- Admin API key available
- Market data in Redis (ADA-USD, BTC-USD, etc.)

## 🏗️ Initial Setup (First Time Only)

If you haven't created the Insurance Fund account yet, follow these steps:

### Step 1: Create IF Account

```bash
cd /Users/hoangvu/hade/strike/strike-v2-backend

# Generate a unique account ID
IF_ACCOUNT_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')

# Create Insurance Fund account in Redis
docker exec strike-redis-local redis-cli SET "account:$IF_ACCOUNT_ID" "{
  \"ID\":\"$IF_ACCOUNT_ID\",
  \"Type\":\"if\",
  \"FeeBracketId\":0,
  \"Balance\":\"1000000\",
  \"IsReferred\":false,
  \"Symbols\":{}
}"

# Set account balance
docker exec strike-redis-local redis-cli SET "account:$IF_ACCOUNT_ID:balance" "1000000"

# Set account info
docker exec strike-redis-local redis-cli SET "account:info:$IF_ACCOUNT_ID" "{
  \"account_id\":\"$IF_ACCOUNT_ID\",
  \"blockchain\":\"cardano\",
  \"blockchain_address\":\"addr_if_$IF_ACCOUNT_ID\"
}"

echo "✅ Insurance Fund account created: $IF_ACCOUNT_ID"
```

### Step 2: Generate Bot API Key

```bash
# Use the backend script to generate the bot API key
cd /Users/hoangvu/hade/strike/strike-v2-backend/scripts

# Replace with your admin API key
ADMIN_KEY="sk_admin__PCmMa-mwcdRY8u6yI4hr7QdrjXdj8s59hUrewnTUU8"

# Generate bot API key for IF account
./generate_bot_key.sh "$IF_ACCOUNT_ID" "IF Hummingbot Bot" "$ADMIN_KEY"

# Save the generated API key - you'll need it for Hummingbot
```

The script will output your new bot API key. **Save it immediately** - it won't be shown again!

### Step 3: Update Backend Configuration

Add the IF account ID to the engines configuration:

```bash
cd /Users/hoangvu/hade/strike/strike-v2-backend

# Edit services/engines/config/config.local.toml
# Update the [engine.insurance_fund] section:
```

```toml
[engine.insurance_fund]
enabled = true
account_id = "YOUR_IF_ACCOUNT_ID"  # Use the ID from Step 1
max_position_value = 200000
max_total_value = 1000000
```

Then restart the engines:

```bash
docker-compose -f docker-compose.local.yml restart engines
```

### Step 4: Verify Setup

```bash
# Test the API key works
IF_BOT_KEY="your_generated_bot_key"  # From Step 2

curl -H "X-API-Key: $IF_BOT_KEY" \
  "http://localhost:8080/v2/account?account_id=$IF_ACCOUNT_ID" | jq
```

Should return IF account data with balance: 1000000

## 🔑 Example Credentials

For reference, a working example setup:

```bash
# Insurance Fund Account (example)
Account ID: 206fb753-5d6d-462a-9f5d-02b133d54255
API Key: sk_bot_IF_hummingbot_2024
Balance: $1,000,000

# API Endpoints (local development)
API URL: http://localhost:8080
WebSocket URL: ws://localhost:8080
```

## 📋 Choose Your Strategy

Two unwinding strategies are available:

### 1. Simple Unwinder (Recommended for Most Cases)

**File:** `if_unwinder_simple.py`

- ✅ Simple, proven, reliable
- ✅ Always uses maker limit orders
- ✅ Gradual unwinding (10% per order)
- ✅ Best for normal market conditions

**Use when:** IF positions are small relative to fund size, markets are stable

### 2. Aggressive Mode Unwinder (Advanced)

**File:** `if_unwinder_with_aggressive.py`

- ✅ Dual-mode operation (MAKER + AGGRESSIVE)
- ✅ Automatic risk monitoring
- ✅ Switches to market orders when needed
- ✅ Follows full spec requirements

**Use when:** IF handles large positions, volatile markets, or needs faster risk reduction

**Triggers aggressive mode when:**
- Utilization > 80%
- Unrealized loss > $50K
- Position hasn't reduced after 5 minutes

## 🚀 Quick Start

### Step 1: Set Environment Variables

```bash
cd /Users/hoangvu/hade/strike/hummingbot

# Set your IF account credentials from Initial Setup
IF_ACCOUNT_ID="your_if_account_id"    # From Initial Setup Step 1
IF_BOT_KEY="your_if_bot_api_key"      # From Initial Setup Step 2

# Create/update .env file
cat > .env << EOF
STRIKE_PERPETUAL_ACCOUNT_ID=$IF_ACCOUNT_ID
STRIKE_PERPETUAL_API_KEY=$IF_BOT_KEY
STRIKE_PERPETUAL_BASE_URL=http://localhost:8080
STRIKE_PERPETUAL_WS_URL=ws://localhost:8080
EOF
```

### Step 2: Start Hummingbot

```bash
# Load environment variables
source .env

# Start Hummingbot
./start
```

### Step 3: Connect and Start Strategy

In Hummingbot console:

```text
>>> connect strike_perpetual
# Credentials loaded automatically from environment variables

>>> balance
# Verify shows: 1000000.00 USDT

>>> start --script if_unwinder_simple.py

# OR for aggressive mode:
>>> start --script if_unwinder_with_aggressive.py
```

✅ Done! The Insurance Fund unwinder is now active.

## 📊 Monitor the Strategy

```text
>>> status
```

Shows:

- IF account balance
- Current positions (if any)
- Active unwinding orders
- Strategy configuration

## 🎯 How It Works

### Normal Operation

1. **IF accepts bankrupt position** from backend liquidation
   - Example: IF receives +100,000 ADA @ $0.44 entry

2. **Hummingbot detects position** (refreshes every 30s)
   - Logs: "IF Position: ADA-USD size=100000"

3. **Strategy places limit order**
   - Side: SELL (to close LONG position)
   - Size: 10,000 ADA (10% of position)
   - Price: Mid price + 0.1% spread
   - Example: SELL 10,000 ADA @ $0.4545

4. **Order fills gradually**
   - As market moves, order fills
   - Realized PnL tracked

5. **Process repeats**
   - Every 30s, new order placed for remaining position
   - Continues until position fully unwound

### Strategy Configuration

Default settings (in `if_unwinder_simple.py`):

```python
maker_spread_bps = 10  # 0.1% spread from mid price
order_size_pct = 10    # Unwind 10% of position per order
refresh_time = 30      # Refresh orders every 30 seconds
```

## ⚙️ Customize Strategy

### Simple Unwinder

Edit `/Users/hoangvu/hade/strike/hummingbot/scripts/if_unwinder_simple.py`:

### Faster Unwinding (Aggressive)

```python
maker_spread_bps = 5   # Tighter spread (0.05%)
order_size_pct = 25    # Larger chunks (25%)
refresh_time = 15      # More frequent (15s)
```

### More Profitable (Conservative)

```python
maker_spread_bps = 20  # Wider spread (0.2%)
order_size_pct = 5     # Smaller chunks (5%)
refresh_time = 60      # Less frequent (60s)
```

After editing, restart:

```text
>>> stop
>>> start --script if_unwinder_simple.py
```

### Aggressive Mode Unwinder

Edit `/Users/hoangvu/hade/strike/hummingbot/scripts/if_unwinder_with_aggressive.py`:

**MAKER Mode (default):**

```python
maker_spread_bps = 10       # 0.1% spread
maker_order_size_pct = 10   # 10% of position
maker_refresh_time = 30     # 30 seconds
```

**AGGRESSIVE Mode (risk-triggered):**

```python
aggressive_spread_bps = 2         # 0.02% spread (very tight)
aggressive_order_size_pct = 30    # 30% of position (faster)
aggressive_refresh_time = 10      # 10 seconds (more frequent)
```

**Risk Thresholds:**

```python
max_utilization_pct = 80           # Trigger if utilization > 80%
max_unrealized_loss_usd = 50000    # Trigger if loss > $50K
position_stale_time_sec = 300      # Trigger if stale > 5 minutes
```

The strategy automatically switches to aggressive mode when risk thresholds are exceeded

## 🧪 Test the Strategy

### Option 1: Manual Position Test

In another terminal:

```bash
cd /Users/hoangvu/hade/strike/strike-v2-backend/tests/if_adl

# Run test that simulates liquidation
./test_if_accepts_position.sh
```

This creates a leveraged trader, simulates price drop, IF accepts position.

### Option 2: Manual Position Creation

Directly add a test position to IF account in Redis:

```bash
docker exec strike-redis-local redis-cli SET "account:206fb753-5d6d-462a-9f5d-02b133d54255" '{
  "ID":"206fb753-5d6d-462a-9f5d-02b133d54255",
  "Type":"if",
  "Balance":"1000000",
  "Symbols":{
    "ADA-USD":{
      "Position":{
        "ID":8888,
        "MarginMode":"cross",
        "Leverage":1,
        "Size":"50000",
        "EntryPrice":"0.44",
        "IsoMargin":"0"
      }
    }
  }
}'

# Restart engines to reload
docker-compose -f docker-compose.local.yml restart engines
```

Watch Hummingbot detect and unwind it!

## 📝 Common Commands

```bash
# View strategy status
>>> status

# View current positions
>>> position

# View active orders
>>> orders

# View balance
>>> balance

# Stop strategy
>>> stop

# Restart strategy
>>> start --script if_unwinder_simple.py

# Exit Hummingbot
>>> exit
```

## 🔍 Monitoring & Logs

### Hummingbot Logs

```bash
# Follow live logs
tail -f logs/logs_hummingbot.log

# Search for IF activity
tail -100 logs/logs_hummingbot.log | grep -i "IF Position\|unwinding"
```

### Backend Logs (IF Acceptance)

```bash
cd /Users/hoangvu/hade/strike/strike-v2-backend

# Watch IF accept positions
docker-compose -f docker-compose.local.yml logs -f engines | grep -i insurance
```

## 🐛 Troubleshooting

### "Connection refused"

**Issue:** Backend not running

**Fix:**

```bash
cd /Users/hoangvu/hade/strike/strike-v2-backend
docker-compose -f docker-compose.local.yml ps
# If not running:
docker-compose -f docker-compose.local.yml up -d
```

### "Unauthorized" or "Authentication failed"

**Issue:** Wrong API key or account ID

**Fix:**

```bash
# Test API key
curl -H 'X-API-Key: sk_bot_IF_hummingbot_2024' \
  'http://localhost:8080/v2/account?account_id=206fb753-5d6d-462a-9f5d-02b133d54255' | jq
```

Should return IF account data with balance.

### "No positions found"

**Status:** Normal - strategy waits for IF to accept positions from liquidations

### Orders not filling

**Cause:** Spread too wide or low market liquidity

**Fix:** Reduce `maker_spread_bps` in the script for tighter pricing

## 📚 Files Reference

| File                                       | Purpose                                      |
| ------------------------------------------ | -------------------------------------------- |
| `scripts/if_unwinder_simple.py`            | Simple IF unwinder (maker mode only)         |
| `scripts/if_unwinder_with_aggressive.py`   | Advanced unwinder with aggressive mode       |
| `scripts/test_if_simple.py`                | Connection test script                       |
| `.env`                                     | Environment variables (credentials)          |
| `logs/logs_hummingbot.log`                 | Hummingbot activity logs                     |
| `HOW_IF_WORKS.md`                          | Architecture documentation                   |
| `INSURANCE_FUND_GUIDE.md`                  | Setup and usage guide                        |

## 🎓 Integration with Backend

### Backend Components

1. **Engines Service** - Accepts bankrupt positions into IF
   - Config: `services/engines/config/config.local.toml`
   - IF Account ID configured in `[engine.insurance_fund]`
   - Risk limits: $200K per symbol, $1M total

2. **API Service** - Provides IF account data to Hummingbot
   - Endpoint: `/v2/account`
   - Authentication: Bot API key

3. **Redis** - Stores IF account state
   - Account key: `account:{account_id}`
   - Balance key: `account:{account_id}:balance`
   - Market data: `market:{symbol}`

### Data Flow

```text
Backend Liquidation
    ↓
IF accepts position (Engines)
    ↓
Position stored in Redis
    ↓
Hummingbot polls /v2/account (every 30s)
    ↓
Strategy detects position
    ↓
Places unwinding order via API
    ↓
Order fills
    ↓
Position reduced
```

## 🎯 Production Deployment

For production use:

1. **Update endpoints** in `.env`:

   ```bash
   STRIKE_PERPETUAL_BASE_URL=https://api.strike.com
   STRIKE_PERPETUAL_WS_URL=wss://ws.strike.com
   ```

2. **Generate production API key** via backend admin API

3. **Adjust strategy parameters** based on market conditions

4. **Set up monitoring** for IF health and utilization

5. **Configure alerts** for high utilization or large positions

## ✅ Summary

- **IF Account:** 206fb753-5d6d-462a-9f5d-02b133d54255
- **API Key:** sk_bot_IF_hummingbot_2024
- **Strategy:** `if_unwinder_simple.py`
- **Command:** `start --script if_unwinder_simple.py`
- **Status:** ✅ Working

The Insurance Fund unwinder automatically detects and unwinds positions the IF accepts from liquidations, with configurable unwinding speed and pricing strategy.
