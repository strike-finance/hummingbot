# Testing Strike V2 Price System - Reality Check

This guide helps you verify exactly what's happening with mark prices in your system.

---

## Test 1: Current State Baseline

### Check What's in Redis Now

```bash
echo "=== Current Redis State ==="
docker exec strike-redis-local redis-cli HGET "market:ADA-USD" data | python3 -m json.tool | grep -E "symbol|mark_price|index_price|last_price"

# Expected output (hardcoded values):
# "symbol": "ADA-USD",
# "mark_price": "0.45",
# "index_price": "0.45",
# "last_price": "0.45"
```

### Check What API Returns

```bash
echo "=== API Response ==="
curl -s "http://localhost:8080/v2/markets" | jq '.markets["ADA-USD"] | {symbol, mark_price, index_price, last_price}'

# Expected output:
# {
#   "symbol": "ADA-USD",
#   "mark_price": "0.45",
#   "index_price": "0.45",
#   "last_price": "0.45"
# }
```

**✅ Baseline established:** Both should show `0.45` (hardcoded)

---

## Test 2: Price Service Activity

### Check if Price Service is Running

```bash
echo "=== Price Service Status ==="
docker-compose -f docker-compose.local.yml ps price

# Should show: Up
```

### Monitor Price Service Calculations

```bash
echo "=== Live Price Service Output ==="
docker-compose -f docker-compose.local.yml logs -f price --tail=20 &
PRICE_LOG_PID=$!

# Let it run for 30 seconds
sleep 30
kill $PRICE_LOG_PID

# Look for lines like:
# MarkPriceStage - Symbol: ADA-USD,
#   IndexPrice: 0.3913...
#   MarkPrice: 0.00449...  ← Wrong calculation!
```

### Extract Price Service Values

```bash
echo "=== Price Service Calculations ==="
docker-compose -f docker-compose.local.yml logs price --tail=100 | \
  grep -A 3 "MarkPriceStage.*ADA-USD" | tail -4

# Should see:
# IndexPrice: 0.39... (real price)
# MarkPrice: 0.0044... (calculated wrong)
```

**✅ Test Result:**
- If you see `MarkPrice: 0.0044...` → **Price calculation is broken** ✗
- If you see `MarkPrice: 0.39...` → **Price calculation works** ✓

---

## Test 3: Engines Processing

### Check if Engines Receives Events

```bash
echo "=== Engines Mark Price Processing ==="
docker-compose -f docker-compose.local.yml logs engines --tail=100 | \
  grep -i "mark price"

# Look for:
# "processing mark price event" ✓ Good
# "market not found" ✗ Problem
# "mark price is non-positive" ✗ Problem
```

### Watch Engines Live

```bash
echo "=== Live Engines Processing ==="
docker-compose -f docker-compose.local.yml logs -f engines | grep -i "mark\|price" &
ENGINES_LOG_PID=$!

# Let it run for 30 seconds
sleep 30
kill $ENGINES_LOG_PID

# Count how many mark price events processed
docker-compose -f docker-compose.local.yml logs engines --since 30s | \
  grep -c "processing mark price event"
```

**✅ Test Result:**
- If count > 0 → **Engines is receiving events** ✓
- If count = 0 → **Engines not receiving events** ✗

---

## Test 4: Redis Update Check

### Monitor Redis Changes

Open two terminals:

**Terminal 1 - Monitor Redis:**
```bash
# Watch Redis for changes
docker exec strike-redis-local redis-cli --csv MONITOR | grep "market:ADA-USD"
```

**Terminal 2 - Wait for Update:**
```bash
# Wait 60 seconds and check if Redis changed
sleep 60
docker exec strike-redis-local redis-cli HGET "market:ADA-USD" data | \
  python3 -c "import json, sys; d=json.load(sys.stdin); print(f'Mark: {d[\"mark_price\"]}, Index: {d[\"index_price\"]}')"
```

**✅ Test Result:**
- If still shows `Mark: 0.45` → **Redis not being updated** ✗
- If shows `Mark: 0.39...` → **Redis is updating** ✓

---

## Test 5: Manual Update Verification

### Manually Set New Price

```bash
echo "=== Manually Updating Redis ==="

# Set new mark price
docker exec strike-redis-local redis-cli HSET "market:ADA-USD" data '{
  "symbol":"ADA-USD",
  "status":"trading",
  "mark_price":"0.888",
  "index_price":"0.888",
  "last_price":"0.888",
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

echo "Updated mark price to 0.888"
```

### Verify API Sees It (Without Restart)

```bash
echo "=== Check API (No Restart) ==="
curl -s "http://localhost:8080/v2/markets" | jq '.markets["ADA-USD"].mark_price'

# May still show: "0.45" (API might cache)
```

### Restart API and Check Again

```bash
echo "=== Restart API ==="
docker-compose -f docker-compose.local.yml restart api
sleep 5

echo "=== Check API (After Restart) ==="
curl -s "http://localhost:8080/v2/markets" | jq '.markets["ADA-USD"].mark_price'

# Should now show: "0.888"
```

**✅ Test Result:**
- If shows `"0.888"` → **Manual update works** ✓
- If still shows `"0.45"` → **API not reading from Redis correctly** ✗

---

## Test 6: Price Service Override Test

### Wait After Manual Update

After manually setting price to `0.888`, wait to see if price service overrides it:

```bash
echo "=== Testing if Price Service Overrides Manual Update ==="

# Set to 0.888
docker exec strike-redis-local redis-cli HSET "market:ADA-USD" data '{"symbol":"ADA-USD","mark_price":"0.888","index_price":"0.888"}'

# Wait 2 minutes
echo "Waiting 2 minutes to see if price service overrides..."
sleep 120

# Check if it changed back
CURRENT=$(docker exec strike-redis-local redis-cli HGET "market:ADA-USD" data | python3 -c "import json, sys; print(json.load(sys.stdin)['mark_price'])")

echo "Current mark price: $CURRENT"

if [ "$CURRENT" == "0.888" ]; then
  echo "✗ Still 0.888 - Price service NOT overriding"
else
  echo "✓ Changed to $CURRENT - Price service IS overriding"
fi
```

**✅ Test Result:**
- If stays `0.888` → **Price service not updating Redis** ✗
- If changes to something else → **Price service is updating Redis** ✓

---

## Test 7: Complete System Flow Test

### Create Test Script

```bash
cat > /tmp/test_price_flow.sh << 'EOF'
#!/bin/bash

echo "=========================================="
echo "  STRIKE V2 PRICE SYSTEM TEST"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

test_passed=0
test_failed=0

# Test 1: Redis Current State
echo "[1/7] Checking Redis current state..."
REDIS_PRICE=$(docker exec strike-redis-local redis-cli HGET "market:ADA-USD" data 2>/dev/null | python3 -c "import json, sys; print(json.load(sys.stdin)['mark_price'])" 2>/dev/null)
if [ -n "$REDIS_PRICE" ]; then
  echo -e "${GREEN}✓${NC} Redis has mark_price: $REDIS_PRICE"
  ((test_passed++))
else
  echo -e "${RED}✗${NC} Redis mark_price not found"
  ((test_failed++))
fi
echo ""

# Test 2: API Returns Data
echo "[2/7] Checking API returns mark price..."
API_PRICE=$(curl -s "http://localhost:8080/v2/markets" | jq -r '.markets["ADA-USD"].mark_price' 2>/dev/null)
if [ -n "$API_PRICE" ] && [ "$API_PRICE" != "null" ]; then
  echo -e "${GREEN}✓${NC} API returns mark_price: $API_PRICE"
  ((test_passed++))
else
  echo -e "${RED}✗${NC} API mark_price not found"
  ((test_failed++))
fi
echo ""

# Test 3: Redis and API Match
echo "[3/7] Checking Redis and API consistency..."
if [ "$REDIS_PRICE" == "$API_PRICE" ]; then
  echo -e "${GREEN}✓${NC} Redis and API match"
  ((test_passed++))
else
  echo -e "${YELLOW}⚠${NC} Redis ($REDIS_PRICE) != API ($API_PRICE)"
  echo "   This might indicate caching"
  ((test_failed++))
fi
echo ""

# Test 4: Price Service Running
echo "[4/7] Checking price service status..."
PRICE_STATUS=$(docker-compose -f /Users/hoangvu/hade/strike/strike-v2-backend/docker-compose.local.yml ps price 2>/dev/null | grep -i "up")
if [ -n "$PRICE_STATUS" ]; then
  echo -e "${GREEN}✓${NC} Price service is running"
  ((test_passed++))
else
  echo -e "${RED}✗${NC} Price service not running"
  ((test_failed++))
fi
echo ""

# Test 5: Price Service Calculating
echo "[5/7] Checking price service calculations..."
CALC_COUNT=$(docker-compose -f /Users/hoangvu/hade/strike/strike-v2-backend/docker-compose.local.yml logs price --since 5m 2>/dev/null | grep -c "MarkPriceStage.*ADA-USD")
if [ "$CALC_COUNT" -gt 0 ]; then
  echo -e "${GREEN}✓${NC} Price service calculated $CALC_COUNT times in last 5 minutes"
  ((test_passed++))

  # Check if calculation is wrong
  LATEST_CALC=$(docker-compose -f /Users/hoangvu/hade/strike/strike-v2-backend/docker-compose.local.yml logs price --tail=50 2>/dev/null | grep "MarkPriceStage.*ADA-USD" | tail -1)
  if echo "$LATEST_CALC" | grep -q "0\.004"; then
    echo -e "${YELLOW}⚠${NC} But calculation appears wrong (0.004 range instead of 0.4)"
  fi
else
  echo -e "${RED}✗${NC} Price service not calculating (0 calculations)"
  ((test_failed++))
fi
echo ""

# Test 6: Engines Processing
echo "[6/7] Checking engines processing..."
ENGINES_COUNT=$(docker-compose -f /Users/hoangvu/hade/strike/strike-v2-backend/docker-compose.local.yml logs engines --since 5m 2>/dev/null | grep -c "processing mark price event")
if [ "$ENGINES_COUNT" -gt 0 ]; then
  echo -e "${GREEN}✓${NC} Engines processed $ENGINES_COUNT mark price events in last 5 minutes"
  ((test_passed++))
else
  echo -e "${RED}✗${NC} Engines not processing mark price events"
  ((test_failed++))
fi
echo ""

# Test 7: Manual Update Test
echo "[7/7] Testing manual Redis update..."
ORIGINAL_PRICE=$REDIS_PRICE
TEST_PRICE="0.777"

# Update Redis
docker exec strike-redis-local redis-cli HSET "market:ADA-USD" data "{\"symbol\":\"ADA-USD\",\"mark_price\":\"$TEST_PRICE\",\"index_price\":\"$TEST_PRICE\",\"status\":\"trading\",\"order_tick_price\":\"0.0001\",\"order_limit_step_size\":\"0.001\",\"order_limit_min_size\":\"0.001\",\"order_limit_max_size\":\"1000000\"}" > /dev/null 2>&1

# Check if it took
UPDATED_PRICE=$(docker exec strike-redis-local redis-cli HGET "market:ADA-USD" data 2>/dev/null | python3 -c "import json, sys; print(json.load(sys.stdin)['mark_price'])" 2>/dev/null)

if [ "$UPDATED_PRICE" == "$TEST_PRICE" ]; then
  echo -e "${GREEN}✓${NC} Manual update successful (set to $TEST_PRICE)"
  ((test_passed++))

  # Restore original
  docker exec strike-redis-local redis-cli HSET "market:ADA-USD" data "{\"symbol\":\"ADA-USD\",\"mark_price\":\"$ORIGINAL_PRICE\",\"index_price\":\"$ORIGINAL_PRICE\",\"status\":\"trading\",\"order_tick_price\":\"0.0001\",\"order_limit_step_size\":\"0.001\",\"order_limit_min_size\":\"0.001\",\"order_limit_max_size\":\"1000000\"}" > /dev/null 2>&1
  echo "   Restored original price: $ORIGINAL_PRICE"
else
  echo -e "${RED}✗${NC} Manual update failed"
  ((test_failed++))
fi
echo ""

# Summary
echo "=========================================="
echo "  TEST SUMMARY"
echo "=========================================="
echo -e "Passed: ${GREEN}$test_passed${NC}"
echo -e "Failed: ${RED}$test_failed${NC}"
echo ""

# Diagnosis
echo "=========================================="
echo "  DIAGNOSIS"
echo "=========================================="

if [ "$test_passed" -eq 7 ]; then
  echo -e "${GREEN}✓ All tests passed!${NC}"
  echo "System appears to be working correctly."
elif [ "$CALC_COUNT" -gt 0 ] && [ "$ENGINES_COUNT" -eq 0 ]; then
  echo -e "${YELLOW}⚠ Price service calculating but engines not processing${NC}"
  echo "Issue: Engines service not receiving or handling mark price events"
  echo "Fix: Check engines logs and Redis stream connection"
elif [ "$CALC_COUNT" -eq 0 ]; then
  echo -e "${YELLOW}⚠ Price service not calculating prices${NC}"
  echo "Issue: Price service may not have market data configured"
  echo "Fix: Check price service configuration and external API keys"
elif [ "$REDIS_PRICE" == "0.45" ] || [ "$REDIS_PRICE" == "0.45" ]; then
  echo -e "${YELLOW}⚠ Prices still at initialization values${NC}"
  echo "Issue: Price updates not reaching Redis"
  echo "Fix: Check engines persistence and Redis connection"
else
  echo -e "${RED}✗ Multiple issues detected${NC}"
  echo "Check individual test results above"
fi

echo ""
EOF

chmod +x /tmp/test_price_flow.sh
```

### Run Complete Test

```bash
/tmp/test_price_flow.sh
```

**Expected output:**
```
==========================================
  STRIKE V2 PRICE SYSTEM TEST
==========================================

[1/7] Checking Redis current state...
✓ Redis has mark_price: 0.45

[2/7] Checking API returns mark price...
✓ API returns mark_price: 0.45

[3/7] Checking Redis and API consistency...
✓ Redis and API match

[4/7] Checking price service status...
✓ Price service is running

[5/7] Checking price service calculations...
✓ Price service calculated 15 times in last 5 minutes
⚠ But calculation appears wrong (0.004 range instead of 0.4)

[6/7] Checking engines processing...
✗ Engines not processing mark price events

[7/7] Testing manual Redis update...
✓ Manual update successful (set to 0.777)
   Restored original price: 0.45

==========================================
  TEST SUMMARY
==========================================
Passed: 6
Failed: 1

==========================================
  DIAGNOSIS
==========================================
⚠ Price service calculating but engines not processing
Issue: Engines service not receiving or handling mark price events
Fix: Check engines logs and Redis stream connection
```

---

## Test 8: Real-Time Monitoring

### Create Live Dashboard

```bash
cat > /tmp/monitor_prices.sh << 'EOF'
#!/bin/bash

echo "Real-time Price Monitoring (Press Ctrl+C to stop)"
echo "=================================================="
echo ""

while true; do
  clear
  echo "=== STRIKE V2 PRICE SYSTEM STATUS ==="
  echo "Time: $(date '+%H:%M:%S')"
  echo ""

  # Redis
  echo "Redis (ADA-USD):"
  docker exec strike-redis-local redis-cli HGET "market:ADA-USD" data 2>/dev/null | \
    python3 -c "import json, sys; d=json.load(sys.stdin); print(f'  Mark Price:  {d[\"mark_price\"]}'); print(f'  Index Price: {d[\"index_price\"]}')" 2>/dev/null || echo "  Error reading Redis"
  echo ""

  # API
  echo "API (ADA-USD):"
  curl -s "http://localhost:8080/v2/markets" 2>/dev/null | \
    jq -r '.markets["ADA-USD"] | "  Mark Price:  " + .mark_price + "\n  Index Price: " + .index_price' 2>/dev/null || echo "  Error reading API"
  echo ""

  # Price Service (last calculation)
  echo "Price Service (Last Calculation):"
  docker-compose -f /Users/hoangvu/hade/strike/strike-v2-backend/docker-compose.local.yml logs price --tail=50 2>/dev/null | \
    grep "MarkPriceStage.*ADA-USD" | tail -1 | \
    grep -oE "MarkPrice: [0-9.]+" | sed 's/MarkPrice: /  Calculated: /' || echo "  No recent calculations"
  echo ""

  # Engines (processing count)
  ENGINES_COUNT=$(docker-compose -f /Users/hoangvu/hade/strike/strike-v2-backend/docker-compose.local.yml logs engines --since 1m 2>/dev/null | grep -c "processing mark price")
  echo "Engines:"
  echo "  Events processed (last 1min): $ENGINES_COUNT"
  echo ""

  echo "=================================================="
  sleep 5
done
EOF

chmod +x /tmp/monitor_prices.sh
```

### Run Monitor

```bash
/tmp/monitor_prices.sh
```

**Watch for:**
- Redis mark price changing → ✓ Updates working
- Redis mark price stuck at 0.45 → ✗ No updates
- Price service calculations every 5s → ✓ Service working
- Engines events count increasing → ✓ Processing working

---

## Summary

**Run all tests in order:**

```bash
# Quick test
/tmp/test_price_flow.sh

# Detailed monitoring
/tmp/monitor_prices.sh
```

**Expected findings:**
1. ✓ Redis has hardcoded 0.45
2. ✓ API returns 0.45
3. ✓ Price service is calculating (but wrong: 0.004)
4. ✗ Engines not processing events
5. ✓ Manual updates work

**Conclusion:** Price system pipeline is broken between price service and Redis persistence.
