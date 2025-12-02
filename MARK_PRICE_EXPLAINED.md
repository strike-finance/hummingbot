# Why Mark Price is Hardcoded - Strike V2 Architecture

## TL;DR

Mark price is **initially hardcoded in Redis** by initialization scripts for **bootstrap purposes**. The price service **should** update it continuously, but there's a **disconnect** between the price service calculations and the market data API responses.

---

## The Architecture (How It Should Work)

```
┌────────────────────────────────────────────────────────────┐
│                  PRICE DISCOVERY FLOW                      │
└────────────────────────────────────────────────────────────┘

[1] External Price Sources
    ├─ Binance: ADA/USDT = $0.387
    ├─ OKX: ADA/USDT = $0.388
    └─ Coinbase: ADA/USD = $0.386
              │
              ▼
[2] Price Service (Port 8082)
    ├─ Fetches prices from exchanges
    ├─ Calculates weighted average index price
    ├─ Applies funding rate formula
    └─ Publishes MarkPriceEvent
              │
              ▼
[3] Engines Service (Port 8081)
    ├─ Receives MarkPriceEvent from Redis stream
    ├─ Updates market state in memory
    ├─ Calls persistMarketState()
    └─ Saves to Redis: HSET market:ADA-USD data {...}
              │
              ▼
[4] Trading API (Port 8080)
    ├─ Reads from Redis: HGET market:ADA-USD data
    ├─ Returns market data to clients
    └─ GET /v2/markets → { "mark_price": "0.387" }
              │
              ▼
[5] Hummingbot
    └─ Fetches mark price and places orders around it
```

---

## The Reality (What's Actually Happening)

```
┌────────────────────────────────────────────────────────────┐
│                  WHAT'S BROKEN                             │
└────────────────────────────────────────────────────────────┘

[1] Initialization Script
    ├─ scripts/init-hummingbot-account.sh
    └─ docker exec strike-redis redis-cli HSET market:ADA-USD data '{
        "mark_price": "0.45",     ← HARDCODED HERE!
        "index_price": "0.45",
        ...
      }'
              │
              ▼
[2] Price Service (RUNNING)
    ├─ ✓ Fetching real prices from exchanges
    ├─ ✓ Calculating mark price
    ├─ ✓ Publishing MarkPriceEvent
    └─ ✗ Logs show: mark_price = 0.00449  ← WRONG CALCULATION!
              │
              ▼
[3] Engines Service (PROBLEM!)
    ├─ Receives MarkPriceEvent
    ├─ Checks: market not found in state?
    │     OR
    ├─ Validates: mark_price.IsPos() → FALSE (0.00449 validation issue?)
    │     OR
    └─ Doesn't persist to Redis (pipeline error?)
              │
              ▼
[4] Trading API
    ├─ Reads from Redis: HGET market:ADA-USD data
    └─ Gets STALE data from initialization: "0.45"
              │
              ▼
[5] Hummingbot
    └─ Always sees mark_price = 0.45 (never updates)
```

---

## Where the Hardcoding Happens

### File: `scripts/init-hummingbot-account.sh`

**Lines 82-108:**

```bash
# ADA Market Initialization
ADA_MARKET='{
  "symbol":"ADA-USDT",
  "status":"trading",
  "mark_price":"0.45",           ← HARDCODED!
  "index_price":"0.45",          ← HARDCODED!
  "funding_rate":"0.0001",
  "next_funding_time":1234567890, ← HARDCODED timestamp!
  "last_price":"0.45",           ← HARDCODED!
  "open_interest":"1000000",
  "volume_24h":"5000000",
  "high_24h":"0.46",
  "low_24h":"0.43",
  ...
}'

# Write to Redis
docker exec strike-redis redis-cli HSET "market:ADA-USDT" data "$ADA_MARKET"
```

**Why it's hardcoded:**

| Reason | Explanation |
|--------|-------------|
| Bootstrap necessity | System needs initial market data to start |
| Quick testing | Developers can test without external price feeds |
| Deterministic state | Known prices for reproducible tests |
| Expected to update | Price service should overwrite these values |

**The assumption:** Price service will continuously update these values in production.

---

## The Price Service Problem

### Logs Show Wrong Calculation

```bash
# From: docker-compose logs price

Price Service Output:
MarkPriceStage - Symbol: ADA-USD
  IndexPrice: 0.3913412900000      ← Real price ~$0.39 ✓
  PriceOne: 2.78920677621700000    ← ??? (some intermediate calc)
  PriceTwo: 0.0044903771027777777  ← ???
  MarkPrice: 0.0044903771027777777 ← WRONG! Should be ~0.39 ✗

Published:
  "symbol": "ADA-USD"
  "mark_price": "0.0044903771027777777"  ← ~$0.0045 instead of $0.39
  "index_price": "0.3913412900000"       ← Correct!
```

**The issue:**
- Index price is **correct** (~$0.39)
- Mark price is **wrong** ($0.0045 instead of $0.39)
- Off by a factor of ~87x

### Possible Root Causes

1. **Unit conversion error**
   - Price in cents instead of dollars?
   - Wrong decimal places?

2. **Formula error**
   - Mark price = Index price × (1 + Funding rate)
   - Should be: 0.39 × 1.0001 = 0.390039
   - Getting: 0.00449 (formula completely wrong)

3. **Symbol mismatch**
   - Price service calculating for wrong pair?
   - ADA-USD vs ADA-USDT confusion?

4. **Data type issue**
   - Decimal precision loss?
   - Integer division instead of float?

---

## Why Engines Doesn't Update Redis

Looking at `services/engines/handlers/market_handler.go`:

```go
func (h *MarketHandler) HandleMarkPrice(...) {
    // Get market from state
    market := state.Markets[symbol]
    if market == nil {
        h.logger.Error("market not found for mark price update")
        return nil, nil  ← EXITS WITHOUT UPDATE!
    }

    // Round prices
    markPrice := event.MarkPrice.Round(int(market.QuotePrec))

    // Validate mark price must be positive
    if markPrice.IsPos() {
        market.MarkPrice = markPrice
        market.FundingRate = event.FundingRate
        // ... persist to Redis
    } else {
        h.logger.Warn("mark price is non-positive, skip handling")
        return nil, nil  ← EXITS WITHOUT UPDATE!
    }
}
```

**Possible failures:**

| Check | Condition | Result |
|-------|-----------|--------|
| Market exists? | `state.Markets[symbol] == nil` | Skip update |
| Price positive? | `markPrice.IsPos() == false` | Skip update |
| Is 0.00449 positive? | `0.00449 > 0` → YES | Should pass... |

**But maybe:**
- The market isn't loaded in engines state at startup
- Symbol mismatch (ADA-USD vs ADA-USDT)
- Precision rounding makes it zero

---

## Checking Current State

### Check Redis Directly

```bash
# Check what's in Redis for ADA-USD
docker exec strike-redis-local redis-cli HGET "market:ADA-USD" data | python3 -m json.tool

# Expected (hardcoded):
{
  "symbol": "ADA-USD",
  "mark_price": "0.45",     ← Still hardcoded
  "index_price": "0.45",    ← Not updating
  "last_price": "0.45"
}

# Should see (if price service worked):
{
  "symbol": "ADA-USD",
  "mark_price": "0.387",    ← Real-time price
  "index_price": "0.387",   ← Real-time price
  "last_price": "0.387"
}
```

### Check Price Service Events

```bash
# Check if price service is publishing
docker-compose -f docker-compose.local.yml logs price | grep -i "published mark price"

# Should see:
# published mark price {"symbol": "ADA-USD", "mark_price": "0.00449"}
```

### Check Engines Processing

```bash
# Check if engines is receiving events
docker-compose -f docker-compose.local.yml logs engines | grep -i "mark price"

# Look for:
# - "processing mark price event" ✓ Good
# - "market not found" ✗ Problem!
# - "mark price is non-positive" ✗ Problem!
```

---

## The Real Problem

**Two issues happening simultaneously:**

### Issue 1: Price Calculation Bug

```
Price Service:
  Real ADA price = $0.39
  Calculated mark = $0.00449  ← BUG IN FORMULA

This means even if engines worked, the price would be wrong!
```

### Issue 2: Engines Not Updating

```
Engines Service:
  Receives MarkPriceEvent
  Either:
    - Market not in state, OR
    - Symbol mismatch, OR
    - Pipeline not executing
  Result: Redis never updated
```

---

## How to Fix

### Quick Fix: Update Redis Manually

For testing, manually set realistic prices:

```bash
# Update ADA-USD to current price
docker exec strike-redis-local redis-cli HSET "market:ADA-USD" data '{
  "symbol":"ADA-USD",
  "status":"trading",
  "mark_price":"0.387",
  "index_price":"0.387",
  "last_price":"0.387",
  "funding_rate":"0.0001",
  "next_funding_time":1733124000000,
  "order_tick_price":"0.0001",
  "order_limit_price_bound":"0.05",
  "order_market_price_bound":"0.10",
  "order_limit_step_size":"0.001",
  "order_limit_min_size":"0.001",
  "order_limit_max_size":"1000000",
  "order_market_step_size":"0.001",
  "order_market_min_size":"0.001",
  "order_market_max_size":"1000000",
  "order_min_notional":"1",
  "maintenance_margin_rate":"0.01",
  "liquidation_fee_rate":"0.005"
}'

# Restart API to clear cache
docker-compose -f docker-compose.local.yml restart api

# Verify
curl "http://localhost:8080/v2/markets" | jq '.markets["ADA-USD"].mark_price'
# Should show: "0.387"
```

### Proper Fix: Debug Price Service

1. **Find the calculation bug:**
   ```bash
   # Check price service source code
   find services/price -name "*.go" | xargs grep -l "MarkPrice.*calculate"

   # Look for the formula that produces 0.00449 from 0.39
   ```

2. **Fix the formula:**
   - Mark price should ≈ Index price
   - Maybe: `mark_price = index_price * (1 + funding_rate)`
   - Not: `mark_price = something_completely_wrong`

3. **Verify engines receives events:**
   ```bash
   # Check engines logs for mark price events
   docker-compose logs engines | grep -A 5 "processing mark price"

   # Should see successful processing, not "market not found"
   ```

4. **Ensure Redis updates:**
   - Check `persistMarketState()` is called
   - Check Redis pipeline executes
   - Verify data format matches

### Alternative: Mock Price Updates

Create a script to simulate price updates:

```bash
#!/bin/bash
# scripts/update_prices.sh

while true; do
  # Get real ADA price from Binance
  PRICE=$(curl -s "https://api.binance.com/api/v3/ticker/price?symbol=ADAUSDT" | jq -r '.price')

  # Update Redis
  docker exec strike-redis-local redis-cli HSET "market:ADA-USD" data "{
    \"symbol\":\"ADA-USD\",
    \"mark_price\":\"$PRICE\",
    \"index_price\":\"$PRICE\",
    \"last_price\":\"$PRICE\",
    \"status\":\"trading\",
    ...
  }"

  echo "Updated ADA-USD price to $PRICE"
  sleep 5
done
```

---

## Summary

| Component | Status | Issue |
|-----------|--------|-------|
| Initialization Script | ✓ Working | Sets hardcoded 0.45 |
| Price Service | ⚠ Running | Calculates wrong price (0.00449) |
| Engines Handler | ? Unknown | May not be updating Redis |
| Trading API | ✓ Working | Returns whatever is in Redis (0.45) |
| Hummingbot | ✓ Working | Uses mark price from API |

**Root cause:** Price service calculation bug **AND** engines may not be persisting updates.

**Effect:** Mark price stays at hardcoded initialization value (0.45).

**Solution:** Either fix price service + engines integration, or manually update Redis for testing.

---

## For Production

In production deployment:

1. **Fix price service calculation** - Critical!
2. **Verify engines processes events** - Must persist to Redis
3. **Add monitoring** - Alert if prices don't update for 60s
4. **Add fallback** - If price service fails, use last known good price
5. **Remove hardcoded values** - Market data should come from price feeds only

**For local testing:** Use manual Redis updates or accept static prices.
