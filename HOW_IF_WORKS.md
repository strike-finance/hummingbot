# Insurance Fund: How It Works Between Hummingbot & Strike-V2

## The Two-Part System

### Part 1: Strike-V2 Backend (Creates IF Positions)

**Location:** `/Users/hoangvu/hade/strike/strike-v2-backend`

**What It Does:**

1. **Liquidation Engine** detects bankrupt traders
2. **IF Acceptance Logic** transfers bankrupt positions to IF account
3. **Stores in Redis** as IF account positions

**Example Flow:**

```text
1. Trader has LONG 100,000 ADA @ $0.44 entry, 20x leverage
2. Price drops to $0.42 → Margin Ratio hits 100%
3. Liquidation engine tries to close at Bankruptcy Price
4. Order doesn't fill → Position becomes "Bankrupt"
5. IF accepts position:
   - Trader's position: 0 (bankrupted)
   - IF position: +100,000 ADA @ $0.44 entry
6. Redis updated: account:{IF_ACCOUNT_ID} has position
```

**Backend Config:**

```toml
# services/engines/config/config.local.toml
[engine.insurance_fund]
enabled = true
account_id = "206fb753-5d6d-462a-9f5d-02b133d54255"
max_position_value = 200000    # $200K per symbol
max_total_value = 1000000      # $1M total
```

### Part 2: Hummingbot (Unwinds IF Positions)

**Location:** `/Users/hoangvu/hade/strike/hummingbot`

**What It Does:**

1. **Polls API** every 30s to check IF account
2. **Detects positions** in IF account
3. **Places limit orders** to gradually unwind
4. **Repeats** until position fully closed

**The Script (`if_unwinder_simple.py`):**

```python
def on_tick(self):
    # Every 30 seconds
    if current_time - self._last_refresh < 30:
        return

    # Check IF account for positions
    positions = exchange.account_positions

    for trading_pair, position in positions.items():
        # IF has LONG position? SELL to close
        # IF has SHORT position? BUY to close

        # Order details:
        # - Size: 10% of position
        # - Price: Mid price ± 0.1% spread
        # - Type: Limit order (not market)
```

## The Connection Between Them

### Data Flow

```text
┌─────────────────────────────────────────────────┐
│         Strike-V2 Backend                       │
│  (Liquidation & IF Position Management)         │
└─────────────────────────────────────────────────┘
                    ↓
         1. Bankrupt position created
                    ↓
┌─────────────────────────────────────────────────┐
│              Redis Storage                      │
│   Key: account:{IF_ACCOUNT_ID}                  │
│   Data: {                                       │
│     "ID": "206fb...",                           │
│     "Type": "if",                               │
│     "Balance": "1000000",                       │
│     "Symbols": {                                │
│       "ADA-USD": {                              │
│         "Position": {                           │
│           "Size": "100000",   ← IF position    │
│           "EntryPrice": "0.44"                  │
│         }                                       │
│       }                                         │
│     }                                           │
│   }                                             │
└─────────────────────────────────────────────────┘
                    ↑
         2. API polls IF account (every 30s)
                    ↓
┌─────────────────────────────────────────────────┐
│        Strike-V2 API Service                    │
│   GET /v2/account?account_id={IF_ID}            │
│   (Authenticated with bot API key)              │
└─────────────────────────────────────────────────┘
                    ↓
         3. Returns IF account data with positions
                    ↓
┌─────────────────────────────────────────────────┐
│            Hummingbot                           │
│   - Detects position: ADA-USD size=100000       │
│   - Calculates: SELL 10,000 ADA @ $0.45        │
│   - Places limit order via API                  │
└─────────────────────────────────────────────────┘
                    ↓
         4. Order sent back to backend
                    ↓
┌─────────────────────────────────────────────────┐
│        Strike-V2 Matching Engine                │
│   - Matches IF sell order with traders          │
│   - Fills occur gradually                       │
│   - Position size reduces: 100k → 90k → 80k...  │
└─────────────────────────────────────────────────┘
```

## Key Integration Points

### 1. Authentication

- **Backend generates** bot API key for IF account
- **Hummingbot uses** this key to access IF account
- **Scope:** Bot keys are account-specific (can only access assigned account)

### 2. Account Type

- **Backend creates** account with `Type: "if"`
- **Hummingbot doesn't care** - it's just another trading account
- **Benefit:** IF account trades at zero fees

### 3. Position Discovery

- **Backend stores** positions in Redis when IF accepts them
- **Hummingbot reads** via `/v2/account` API endpoint
- **No special logic** - just reads `account_positions` property

### 4. Order Placement

- **Hummingbot places** normal limit orders (same as any trader)
- **Backend matching engine** fills them normally
- **IF earns profits** if exit price > entry price

## Why This Design?

### Separation of Concerns

**Backend (Strike-V2):**

- ✅ Risk management (when to accept bankrupt positions)
- ✅ Liquidation logic (when traders get liquidated)
- ✅ Order matching (fills IF unwinding orders)
- ❌ Doesn't care about unwinding strategy

**Hummingbot:**

- ✅ Unwinding strategy (how to exit positions)
- ✅ Market making (placing limit orders)
- ✅ Timing (when to refresh orders)
- ❌ Doesn't care about how IF got positions

### Benefits

1. **Flexibility:** Change unwinding strategy without touching backend
2. **Simplicity:** Hummingbot is just a trading bot for IF account
3. **Testability:** Can test IF acceptance separately from unwinding
4. **Monitoring:** Easy to see IF activity in Hummingbot logs

## Real Example

### Scenario: Trader Gets Liquidated

**T+0s: Backend liquidates trader**

```bash
# Engines service log
[INFO] Liquidation triggered: account=trader_123 symbol=ADA-USD
[INFO] Bankruptcy price: $0.42
[INFO] Liquidation order unfilled
[INFO] IF accepting position: size=100,000 ADA @ $0.44
[INFO] IF utilization: $44,000 / $1,000,000 (4.4%)
```

**T+10s: Hummingbot polls (not yet time)**

```python
# if_unwinder_simple.py
# Current time - last refresh = 10s < 30s
# Skip this tick
```

**T+30s: Hummingbot detects position**

```bash
# Hummingbot log
[INFO] IF Position: ADA-USD size=100000
[INFO] Placing sell order: 10000 ADA @ $0.4545
[INFO] ✓ Order placed successfully
```

**T+45s: Order partially fills**

```bash
# Backend API log
[INFO] Order filled: order_id=123 filled=5000/10000

# Hummingbot log
[INFO] Order partially filled: 5000/10000
```

**T+60s: Hummingbot refreshes**

```bash
# Hummingbot log
[INFO] IF Position: ADA-USD size=95000  # 100k - 5k filled
[INFO] Canceling old order: 10000 ADA (5k already filled)
[INFO] Placing new sell order: 9500 ADA @ $0.4545  # 10% of 95k
```

**T+300s: Position fully unwound**

```bash
# Hummingbot log
[INFO] IF Position: ADA-USD size=0
[INFO] No IF positions to unwind

# IF made profit: Entered @ $0.44, Exited @ $0.4545 avg
# Profit: 100,000 * ($0.4545 - $0.44) = $1,450
```

## The Key Insight

**Hummingbot doesn't know it's an "Insurance Fund"** - it's just a trading bot that:

- Reads positions from an account
- Places orders to close those positions
- Uses limit orders for better pricing

**Backend doesn't know about Hummingbot** - it just:

- Transfers bankrupt positions to IF account
- Stores them in Redis
- Matches orders normally

**They're loosely coupled via:**

- Redis (data storage)
- API (data access)
- Bot API key (authentication)

This is why we can easily:

- Change unwinding strategy (edit `if_unwinder_simple.py`)
- Adjust risk limits (edit `config.local.toml`)
- Run multiple IF bots (for different strategies)
- Test each part independently

## Component Responsibilities

### Strike-V2 Backend Components

#### 1. Engines Service

```toml
# services/engines/config/config.local.toml
[engine.insurance_fund]
enabled = true
account_id = "206fb753-5d6d-462a-9f5d-02b133d54255"
max_position_value = 200000
max_total_value = 1000000
```

**Responsibilities:**

- Monitor all trader positions for liquidation
- Trigger liquidation when margin ratio ≥ 100%
- Accept bankrupt positions into IF account
- Enforce IF risk limits (per-symbol, total)
- Trigger ADL if IF rejects position

#### 2. API Service

**Endpoints used by Hummingbot:**

```bash
# Get IF account data (includes positions)
GET /v2/account?account_id={IF_ACCOUNT_ID}
Header: X-API-Key: {IF_BOT_KEY}

# Place unwinding order
POST /v2/order
Body: {
  "account_id": "{IF_ACCOUNT_ID}",
  "symbol": "ADA-USD",
  "side": "sell",
  "type": "limit",
  "price": "0.45",
  "quantity": "10000"
}

# Get open orders
GET /v2/openOrders?symbol=ADA-USD

# Cancel order
DELETE /v2/order/cancel
Body: {"symbol": "ADA-USD", "order_id": 123}
```

**Responsibilities:**

- Authenticate bot API key
- Return IF account data
- Accept and validate orders
- Forward to matching engine

#### 3. Redis Storage

**Keys used:**

```bash
# IF account data with positions
account:{IF_ACCOUNT_ID}

# IF account balance
account:{IF_ACCOUNT_ID}:balance

# Market data (needed for pricing)
market:ADA-USD
market:BTC-USD
```

**Responsibilities:**

- Store IF account state
- Store positions in real-time
- Provide fast data access

### Hummingbot Components

#### 1. Strike Connector

**Location:** `hummingbot/connector/derivative/strike_perpetual/`

**Responsibilities:**

- Connect to Strike API via environment variables
- Authenticate using bot API key
- Fetch account data (balance, positions)
- Submit orders to API
- Track order status
- Handle WebSocket updates (optional)

#### 2. IF Unwinder Script

**Location:** `scripts/if_unwinder_simple.py`

**Configuration:**

```python
maker_spread_bps = 10  # 0.1% spread from mid price
order_size_pct = 10    # Unwind 10% of position per order
refresh_time = 30      # Refresh orders every 30 seconds
```

**Responsibilities:**

- Poll IF account every 30s
- Detect positions
- Calculate unwinding orders
- Place limit orders
- Cancel stale orders
- Log activity

#### 3. Test Script

**Location:** `scripts/test_if_simple.py`

**Responsibilities:**

- Verify connection to Strike API
- Check IF account access
- Display balance and positions
- Useful for debugging

## Configuration Files

### Backend Configuration

```toml
# /Users/hoangvu/hade/strike/strike-v2-backend/services/engines/config/config.local.toml

[engine.insurance_fund]
enabled = true
account_id = "206fb753-5d6d-462a-9f5d-02b133d54255"
max_position_value = 200000    # Max $200K per symbol
max_total_value = 1000000      # Max $1M total across all symbols
```

### Hummingbot Configuration

```bash
# /Users/hoangvu/hade/strike/hummingbot/.env

STRIKE_PERPETUAL_ACCOUNT_ID=206fb753-5d6d-462a-9f5d-02b133d54255
STRIKE_PERPETUAL_API_KEY=sk_bot_IF_hummingbot_2024
STRIKE_PERPETUAL_BASE_URL=http://localhost:8080
STRIKE_PERPETUAL_WS_URL=ws://localhost:8080
```

## Monitoring & Logs

### Backend Logs

```bash
cd /Users/hoangvu/hade/strike/strike-v2-backend

# Watch IF acceptance
docker-compose -f docker-compose.local.yml logs -f engines | grep -i insurance

# Watch order matching
docker-compose -f docker-compose.local.yml logs -f api | grep -i "IF\|206fb753"
```

### Hummingbot Logs

```bash
cd /Users/hoangvu/hade/strike/hummingbot

# Follow live logs
tail -f logs/logs_hummingbot.log

# Search for IF activity
tail -100 logs/logs_hummingbot.log | grep -i "IF Position\|unwinding"
```

## Summary

The Insurance Fund system is a **loosely coupled**, **two-part architecture**:

1. **Strike-V2 Backend** - Creates IF positions when traders go bankrupt
2. **Hummingbot** - Unwinds those positions by trading

They communicate through:

- **Redis** - Shared data storage
- **REST API** - Data access and order placement
- **Bot API Key** - Authentication

This design allows independent development, testing, and deployment of each component while maintaining a clean separation of concerns.
