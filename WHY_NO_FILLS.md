# Why Orders Don't Fill - Strike V2 Market Making

## TL;DR

**Orders don't fill because:**
1. Mark price is **static** (hardcoded at 0.45 for ADA)
2. **No external traders** to match against your orders
3. **Spread prevents self-matching** (0.40% gap between best bid and ask)

---

## Current Market State

### ADA-USD Market Data

```
Mark Price:    0.45  (static, doesn't change)
Index Price:   0.45  (static, doesn't change)
Last Price:    0.45  (no recent trades)

Best Bid:      0.4491  (your buy order)
Best Ask:      0.4509  (your sell order)
Spread:        0.0018  (0.40%)
```

### Your Order Book

```
SELL SIDE (Asks):
  0.4509 × 100   ← Best Ask
  0.4514 × 200
  0.4518 × 300

  -------- 0.0018 GAP --------  ← No overlap!

BUY SIDE (Bids):
  0.4491 × 100   ← Best Bid
  0.4487 × 200
  0.4482 × 300
```

---

## Why Fills Don't Happen

### 1. Static Mark Price

The mark price is **hardcoded** and doesn't update based on external markets:

```bash
# Check market data
curl "http://localhost:8080/v2/markets" | jq '.markets["ADA-USD"]'

# Shows:
{
  "mark_price": "0.45",      # Static
  "index_price": "0.45",     # Static
  "last_price": "0.45",      # Never updates
  "funding_rate": "0.0001",
  "next_funding_time": 1234567890  # Hardcoded timestamp
}
```

**Why this matters:**
- Hummingbot uses mark price to calculate order prices
- If mark price doesn't change, Hummingbot keeps placing orders at the same levels
- No price movement = no reason for orders to fill

### 2. No External Traders

Strike V2 local environment has:
- ✅ Your Hummingbot bot (placing orders)
- ❌ No other traders
- ❌ No market takers
- ❌ No arbitrage bots

**Order matching requires:**
```
Scenario A: Price crosses your level
  Market moves up → hits your sell order at 0.4509 ✓

Scenario B: Another trader takes your order
  Someone buys at market → fills your sell at 0.4509 ✓

Scenario C: Your own orders cross (NOT ALLOWED)
  Your buy at 0.4491 + Your sell at 0.4509 → Gap prevents self-match ✗
```

### 3. Spread Prevents Self-Matching

Your orders have a **0.40% spread**:

```
Best Bid: 0.4491
Best Ask: 0.4509
Gap:      0.0018

For orders to match:
  Buy Price >= Sell Price

Current state:
  0.4491 < 0.4509  ✗ (no match)
```

**Strike's matching engine** only matches when:
- Buy order price ≥ Sell order price
- Orders are from different accounts (no self-trading)

---

## How Orders WOULD Fill

### Method 1: Real Price Updates

If the price service were properly connected:

```
1. External ADA price changes: 0.45 → 0.46
2. Mark price updates in Redis
3. Hummingbot reads new mark price
4. Hummingbot cancels old orders
5. Hummingbot places new orders around 0.46
6. New orders at different levels → potential fills
```

### Method 2: External Traders

If other traders joined:

```
1. Trader A places market buy order
2. Matches against your sell at 0.4509
3. Your order fills → position created
4. Hummingbot detects fill
5. Hummingbot places new orders to maintain spread
```

### Method 3: Manual Fill (Testing)

You can manually create fills for testing:

```bash
# Place a market buy to hit your sell order
curl -X POST http://localhost:8080/v2/order \
  -H "X-API-Key: sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ADA-USD",
    "side": "buy",
    "type": "market",
    "size": "50"
  }'

# This will:
# 1. Match against your best ask at 0.4509
# 2. Fill 50 ADA
# 3. Create a LONG position (+50 ADA)
# 4. Trigger WebSocket position update
# 5. Hummingbot sees the fill
```

---

## Why Price Service Isn't Working

Looking at the price service logs:

```
Price Service Log:
MarkPrice: 0.0044903771027777777  ← WRONG!
IndexPrice: 0.3913412900000       ← Real price (~$0.39)

Market API Response:
mark_price: "0.45"  ← Hardcoded, not updated
```

**The problem:**
1. Price service fetches real prices from external sources (Binance, CoinGecko)
2. Calculates mark price using formula
3. **BUT** the calculated price (0.00449) is clearly wrong
4. Market data API returns hardcoded 0.45 instead

**Possible causes:**
- Price service calculation error (wrong formula or scaling)
- Mark price not being saved to Redis correctly
- Market data API reading from wrong Redis key
- Price service and API service using different data sources

---

## Testing Order Fills

### Option A: Place Crossing Orders

Place a limit buy order above the best ask:

```bash
BOT_KEY="sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o"

# Your best ask is at 0.4509
# Place a buy order at 0.46 (above the ask)
curl -X POST http://localhost:8080/v2/order \
  -H "X-API-Key: $BOT_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ADA-USD",
    "side": "buy",
    "type": "limit",
    "price": "0.46",
    "size": "50"
  }'
```

**What happens:**
```
1. Buy order at 0.46 submitted
2. Matching engine sees: 0.46 >= 0.4509 ✓
3. Order crosses → immediate fill
4. Your sell at 0.4509 fills
5. Position created: +50 ADA
```

### Option B: Use Market Orders

```bash
# Market buy - will fill at best ask
curl -X POST http://localhost:8080/v2/order \
  -H "X-API-Key: $BOT_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ADA-USD",
    "side": "buy",
    "type": "market",
    "size": "100"
  }'

# Will fill against your sell orders:
# - 100 @ 0.4509 (fills completely)
```

### Option C: Second Bot Account

Create a second account with its own API key to trade against yourself:

```bash
# Create second account
ACCOUNT_2="019xxx-second-account-xxx"
BOT_KEY_2="sk_bot_second_account_key"

# Account 1: Places sell orders
# Account 2: Places buy orders that match

# This simulates real market activity
```

---

## Understanding the Flow

### Normal Market Making Flow

```
┌─────────────────────────────────────────────────────────┐
│  1. External Price Changes                              │
│     Binance: ADA = $0.50 → $0.51                       │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  2. Price Service Updates Mark Price                    │
│     Strike mark_price: 0.50 → 0.51                     │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  3. Hummingbot Detects Price Change                     │
│     Old: 0.50, New: 0.51, Change: 2%                   │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  4. Hummingbot Cancels Old Orders                       │
│     Cancel all orders around 0.50                       │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  5. Hummingbot Places New Orders                        │
│     Buy:  0.5049 (1% below 0.51)                       │
│     Sell: 0.5151 (1% above 0.51)                       │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  6. Traders Match Against New Orders                    │
│     Market taker buys at 0.5151 → Your order fills     │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  7. Position Created                                     │
│     You sold 100 ADA at 0.5151 → Short position        │
└─────────────────────────────────────────────────────────┘
```

### Current Broken Flow

```
┌─────────────────────────────────────────────────────────┐
│  1. External Price Changes                              │
│     Binance: ADA = $0.39                                │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  2. Price Service Calculates Wrong                      │
│     Calculated: 0.00449 (WRONG!)                        │
│     Not saved to Redis or API ignores it                │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  3. Market API Returns Hardcoded Price                  │
│     mark_price: 0.45 (static)                          │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  4. Hummingbot Sees No Change                           │
│     Old: 0.45, New: 0.45, Change: 0%                   │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  5. Hummingbot Does Nothing                             │
│     No price change → No order updates                  │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  6. No Traders                                          │
│     Local environment → No external orders              │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  7. Orders Sit Unfilled                                 │
│     Orders at 0.4491 / 0.4509 never match              │
└─────────────────────────────────────────────────────────┘
```

---

## Solutions

### For Testing (Quick Fix)

Manually create fills to test position management:

```bash
# Test script: /tmp/test_fills.sh
BOT_KEY="sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o"

# Buy 50 ADA at market (fills against your sell orders)
curl -X POST http://localhost:8080/v2/order \
  -H "X-API-Key: $BOT_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"ADA-USD","side":"buy","type":"market","size":"50"}'

sleep 2

# Check position
curl -H "X-API-Key: $BOT_KEY" \
  "http://localhost:8080/v2/positions?symbol=ADA-USD"
```

### For Production (Real Fix)

Fix the price service integration:

1. **Debug price calculation:**
   - Check why mark price is 0.00449 instead of ~0.45
   - Verify price source configuration
   - Fix calculation formula

2. **Verify Redis integration:**
   - Ensure price service writes to correct Redis key
   - Ensure API service reads from correct Redis key
   - Check data format consistency

3. **Enable real price feeds:**
   - Configure price service with real API keys (Binance, CoinGecko)
   - Set update intervals (e.g., every 5 seconds)
   - Monitor price service logs for successful updates

4. **Deploy external market maker:**
   - Run second Hummingbot instance with different spreads
   - Or integrate with real perpetual DEX for external liquidity

---

## Summary

| Component | Current State | Impact |
|-----------|--------------|--------|
| Mark Price | Static (0.45) | No price discovery |
| External Traders | None | No order matches |
| Price Service | Running but broken | Calculated prices not used |
| Order Book | Working | Orders placed correctly |
| Matching Engine | Working | Would match if orders cross |
| Hummingbot | Working | Places orders, waits for fills |

**Bottom line:** The system is working correctly, but there's no **price volatility** or **external liquidity** to create fills. This is expected in a local test environment.

To see fills, either:
1. Manually create crossing orders (testing)
2. Fix price service integration (development)
3. Deploy to production with real traders (production)
