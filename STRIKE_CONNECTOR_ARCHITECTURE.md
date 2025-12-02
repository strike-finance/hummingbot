# Strike Perpetual Connector - Complete Architecture Guide

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         HUMMINGBOT CORE                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │         Perpetual Market Making Strategy (PMM)               │  │
│  │  - Calculates bid/ask spreads                                │  │
│  │  - Determines order sizes                                     │  │
│  │  - Monitors PnL and positions                                │  │
│  └─────────────────────┬────────────────────────────────────────┘  │
│                        │ calls market.buy()/sell()                  │
│                        ▼                                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │      StrikePerpetualDerivative (Main Connector)              │  │
│  │  - Extends PerpetualDerivativePyBase                         │  │
│  │  - Manages order lifecycle                                    │  │
│  │  - Tracks positions and balances                             │  │
│  │  - Handles USD/USDT conversion                               │  │
│  └──────┬─────────────┬─────────────┬─────────────┬──────────┘  │
│         │             │             │             │              │
└─────────┼─────────────┼─────────────┼─────────────┼──────────────┘
          │             │             │             │
          ▼             ▼             ▼             ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
    │  Auth   │   │OrderBook│   │UserStream│  │WebUtils │
    │ Handler │   │ Source  │   │  Source  │  │         │
    └─────────┘   └─────────┘   └─────────┘   └─────────┘
          │             │             │             │
          └─────────────┴─────────────┴─────────────┘
                        │
          ┌─────────────┴─────────────────────────────┐
          │                                             │
          ▼                                             ▼
┌──────────────────┐                        ┌──────────────────┐
│  Strike V2 API   │                        │  Strike V2 WS    │
│  (port 8080)     │                        │  (port 8083)     │
│                  │                        │                  │
│  REST Endpoints: │                        │  WebSocket:      │
│  - /v2/account   │                        │  - orders        │
│  - /v2/order     │                        │  - positions     │
│  - /v2/positions │                        │  - balance       │
│  - /v2/markets   │                        │                  │
└──────────────────┘                        └──────────────────┘
```

## 2. Connector Components

The Strike connector consists of **7 Python modules**:

### Core Files:

```
strike_perpetual/
├── strike_perpetual_derivative.py       (Main connector - 800+ lines)
├── strike_perpetual_auth.py            (Authentication handler)
├── strike_perpetual_api_order_book_data_source.py  (Market data)
├── strike_perpetual_api_user_stream_data_source.py (WebSocket events)
├── strike_perpetual_constants.py       (URLs, endpoints, mappings)
├── strike_perpetual_utils.py          (Config and fees)
└── strike_perpetual_web_utils.py      (HTTP client factory)
```

### Component Responsibilities:

```
┌────────────────────────────────────────────────────────────┐
│  strike_perpetual_derivative.py (MAIN CONNECTOR)          │
│  ─────────────────────────────────────────────────────    │
│  • Order Management: _place_order(), _place_cancel()      │
│  • Balance Tracking: _update_balances()                   │
│  • Position Tracking: _update_positions()                 │
│  • Price Conversion: get_price() - USD/USDT handling     │
│  • Order State: _process_order_message()                  │
│  • Trading Rules: _update_trading_rules()                 │
│  • Funding Rates: _update_funding_rate()                  │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  strike_perpetual_auth.py (AUTHENTICATION)                │
│  ────────────────────────────────────────────────────     │
│  • rest_authenticate(): Adds X-API-Key header             │
│  • ws_authenticate(): Adds account_id to WS payloads      │
│  • Fallback: account_id in request params/body            │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  strike_perpetual_api_order_book_data_source.py           │
│  ────────────────────────────────────────────────────     │
│  • fetch_trading_pairs(): Get available markets           │
│  • get_last_traded_prices(): Fetch mark prices            │
│  • get_snapshot(): Create SYNTHETIC order book            │
│    (Strike v2 has no /v2/depth endpoint)                  │
│  • listen_for_order_book_diffs(): WS order book updates   │
│  • listen_for_trades(): WS trade stream                   │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  strike_perpetual_api_user_stream_data_source.py          │
│  ────────────────────────────────────────────────────     │
│  • _subscribe_channels(): Subscribe to private streams    │
│    - orders: Order fill/cancel events                     │
│    - positions: Position updates                          │
│    - balance: Balance changes                             │
│  • _process_event_message(): Route events to connector    │
│  • _ping_thread(): Keep WebSocket alive                   │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  strike_perpetual_constants.py (CONFIGURATION)            │
│  ────────────────────────────────────────────────────     │
│  • API Endpoints: All REST and WS URLs                    │
│  • Order Status Mapping: Strike codes → Hummingbot states │
│  • Rate Limits: 1200 requests/minute                      │
│  • Currency: USDT (collateral)                            │
└────────────────────────────────────────────────────────────┘
```

## 3. Authentication Flow

Strike supports two authentication methods:

```
┌──────────────────────────────────────────────────────────────┐
│                   Authentication Decision Tree               │
└──────────────────────────────────────────────────────────────┘

                    API Key Provided?
                          │
            ┌─────────────┴─────────────┐
            │ YES                       │ NO
            ▼                           ▼
    ┌───────────────┐          ┌────────────────┐
    │  BOT MODE     │          │  MANUAL MODE   │
    │  (Recommended)│          │  (Testing)     │
    └───────────────┘          └────────────────┘
            │                           │
            │                           │
            ▼                           ▼
    X-API-Key: sk_bot_...      account_id in params/body

    ┌─────────────────────────────────┐
    │ Example Request (Bot Mode):     │
    │                                 │
    │ POST /v2/order                  │
    │ Headers:                        │
    │   X-API-Key: sk_bot_4GXFf...    │
    │   Content-Type: application/json│
    │ Body:                           │
    │   {                             │
    │     "symbol": "ADA-USD",        │
    │     "side": "buy",              │
    │     "type": "limit",            │
    │     "price": "0.45",            │
    │     "size": "100"               │
    │   }                             │
    └─────────────────────────────────┘
```

### Authentication Code Flow:

```python
# strike_perpetual_auth.py:33
async def rest_authenticate(self, request: RESTRequest):
    if self._api_key:
        # Bot mode - add X-API-Key header
        request.headers["X-API-Key"] = self._api_key
    else:
        # Manual mode - add account_id to params/body
        if request.method == RESTMethod.POST:
            request.data = self._add_account_id_to_params(request.data)
        elif request.method == RESTMethod.GET:
            request.params["account_id"] = self._account_id
```

## 4. Order Lifecycle

```
┌────────────────────────────────────────────────────────────────┐
│                      ORDER LIFECYCLE                           │
└────────────────────────────────────────────────────────────────┘

[1] Strategy calls market.buy("ADA-USD", 100, OrderType.LIMIT, 0.45)
                    │
                    ▼
[2] StrikePerpetualDerivative._place_order()
                    │
                    ├─> Create InFlightOrder
                    ├─> Assign client_order_id
                    └─> Send to order_tracker
                    │
                    ▼
[3] HTTP POST /v2/order
                    │
    ┌───────────────┴───────────────┐
    │ Request Body:                 │
    │ {                             │
    │   "symbol": "ADA-USD",        │
    │   "side": "buy",              │
    │   "type": "limit",            │
    │   "price": "0.45",            │
    │   "size": "100",              │
    │   "reduce_only": false,       │
    │   "time_in_force": "GTC"      │
    │ }                             │
    └───────────────┬───────────────┘
                    │
                    ▼
[4] Strike Matching Engine processes order
                    │
                    ▼
[5] WebSocket Event: {"channel": "orders", "data": {...}}
                    │
                    ▼
[6] UserStreamDataSource receives event
                    │
                    ▼
[7] Connector._process_order_message()
                    │
                    ├─> Update InFlightOrder state
                    ├─> Emit OrderFilledEvent if filled
                    └─> Update balances and positions
                    │
                    ▼
[8] Strategy receives event and adjusts behavior
```

### Order State Mapping:

```
Strike Status Code    →    Hummingbot OrderState
────────────────────────────────────────────────
0 (NONE)              →    PENDING_CREATE
1 (PENDING)           →    PENDING_CREATE
2 (OPEN)              →    OPEN
3 (FILLED)            →    FILLED
4 (CANCELED)          →    CANCELED
5 (UNTRIGGERED)       →    OPEN
6 (REJECTED)          →    FAILED
7 (EXPIRED)           →    CANCELED
```

## 5. USD/USDT Conversion Architecture

This is a **critical design decision** due to Strike's architecture:

```
┌────────────────────────────────────────────────────────────────┐
│                    USD vs USDT MISMATCH                        │
└────────────────────────────────────────────────────────────────┘

Strike V2 Architecture:
  • Trading Pairs: ADA-USD, BTC-USD (quote currency: USD)
  • Collateral: USDT (actual balance currency)
  • They treat 1 USD = 1 USDT internally

Hummingbot PMM Strategy:
  • Checks collateral with: market.get_price("USD-USDT")
  • Calculates budget: balance_in_usdt * usd_price

Without Fix:
  ✗ get_price("USD-USDT") → Order book not found
  ✗ get_price("ADA-USDT") → Order book not found
  ✗ Clock tick fails → Strategy stops

With Fix (strike_perpetual_derivative.py:220):
  ✓ get_price("USD-USDT") → Fetches real USDT/USD rate from Binance
  ✓ get_price("ADA-USDT") → Converts to ADA-USD automatically
  ✓ Stores balances under BOTH "USD" and "USDT" keys
```

### USD/USDT Conversion Code:

```python
def get_price(self, trading_pair: str, is_buy: bool) -> Decimal:
    # Handle USD-USDT conversion
    if trading_pair in ["USD-USDT", "USDT-USD"]:
        return self._get_usdt_usd_reference_price()

    # Convert USDT-based pairs to USD-based pairs
    if "-USDT" in trading_pair:
        converted_pair = trading_pair.replace("-USDT", "-USD")
        if converted_pair in self.order_book_tracker.order_books:
            return super().get_price(converted_pair, is_buy)

    return super().get_price(trading_pair, is_buy)

def _get_usdt_usd_reference_price(self) -> Decimal:
    """
    Fetch USDT/USD rate from Binance (uses USDC/USDT as proxy)
    Cached for 60 seconds to avoid excessive API calls
    Fallback to 1.0 if fetch fails
    """
    # Implementation fetches from:
    # https://api.binance.com/api/v3/ticker/price?symbol=USDCUSDT
    # Then inverts: 1 / USDC_USDT = USDT_USD
```

### Balance Storage Fix:

Located in `strike_perpetual_derivative.py:490`

```python
# Store balances under BOTH keys for compatibility
quote = "USD"  # Match trading pair quote currency
self._account_balances[quote] = wallet_balance
self._account_available_balances[quote] = available_balance

# Also store under "USDT" (actual collateral currency)
self._account_balances[CONSTANTS.CURRENCY] = wallet_balance
self._account_available_balances[CONSTANTS.CURRENCY] = available_balance
```

**Why this matters:**
- Trading pairs (ADA-USD, BTC-USD) use "USD" as quote currency
- The `status` command and PMM strategy look for "USD" balance
- The API returns balances in "USDT" (actual collateral)
- Storing under both keys ensures compatibility with both systems

## 6. Synthetic Order Book

Strike V2 doesn't have a `/v2/depth` endpoint, so the connector creates a **synthetic order book**:

```
┌────────────────────────────────────────────────────────────────┐
│              SYNTHETIC ORDER BOOK GENERATION                   │
└────────────────────────────────────────────────────────────────┘

[1] Fetch mark price from /v2/markets
            │
            ▼ mark_price = 0.45 (for ADA-USD)
            │
[2] Calculate bid/ask with 0.2% spread
            │
            ├─> bid_price = 0.45 * (1 - 0.002) = 0.4491
            └─> ask_price = 0.45 * (1 + 0.002) = 0.4509
            │
[3] Create 5 levels with increasing spreads
            │
            ▼
┌─────────────────────────────────────────────┐
│  Synthetic Order Book:                      │
│                                             │
│  Bids:                                      │
│    Level 0: 0.4491 × 100   (0.0% from mid) │
│    Level 1: 0.4487 × 200   (0.1% spread)   │
│    Level 2: 0.4482 × 300   (0.2% spread)   │
│    Level 3: 0.4478 × 400   (0.3% spread)   │
│    Level 4: 0.4473 × 500   (0.4% spread)   │
│                                             │
│  Asks:                                      │
│    Level 0: 0.4509 × 100                   │
│    Level 1: 0.4513 × 200                   │
│    Level 2: 0.4518 × 300                   │
│    Level 3: 0.4523 × 400                   │
│    Level 4: 0.4527 × 500                   │
└─────────────────────────────────────────────┘
            │
            ▼
[4] Return to strategy for bid/ask calculations
```

### Implementation:

Located in `strike_perpetual_api_order_book_data_source.py:195`

```python
# Create synthetic orderbook with 0.2% spread around index price
spread_pct = 0.002  # 0.2%
bid_price = index_price * (1 - spread_pct)
ask_price = index_price * (1 + spread_pct)

# Create a ladder of orders with increasing size
bids = []
asks = []
for i in range(5):
    level_spread = i * 0.001  # 0.1% between levels
    size = str(100 * (i + 1))  # Increasing size

    bid_level_price = bid_price * (1 - level_spread)
    ask_level_price = ask_price * (1 + level_spread)

    bids.append([str(round(bid_level_price, 4)), size])
    asks.append([str(round(ask_level_price, 4)), size])

return {
    "trading_pair": trading_pair,
    "update_id": int(time.time()),
    "bids": bids,
    "asks": asks
}
```

**Why synthetic order book:**
- Strike V2 API doesn't expose `/v2/depth` endpoint
- Hummingbot strategies need order book data to calculate bid/ask prices
- Mark price from `/v2/markets` provides accurate mid-market reference
- Synthetic book with fixed spread is sufficient for market making strategy

## 7. WebSocket Data Flow

```
┌────────────────────────────────────────────────────────────────┐
│                    WEBSOCKET ARCHITECTURE                      │
└────────────────────────────────────────────────────────────────┘

[1] Connector starts
            │
            ▼
[2] Connect to ws://localhost:8083/ws
            │
            ▼
[3] Subscribe to 3 channels:
            │
            ├─> {"method": "subscribe", "channel": "orders",
            │    "account_id": "0199f06b-911f-7ce8-987d-c2ff4798a06c"}
            │
            ├─> {"method": "subscribe", "channel": "positions",
            │    "account_id": "0199f06b-911f-7ce8-987d-c2ff4798a06c"}
            │
            └─> {"method": "subscribe", "channel": "balance",
                 "account_id": "0199f06b-911f-7ce8-987d-c2ff4798a06c"}
            │
            ▼
[4] Receive events in real-time:

┌─────────────────────────────────────────────────────────────┐
│  Order Event:                                               │
│  {                                                          │
│    "channel": "orders",                                     │
│    "data": {                                                │
│      "order_id": 123,                                       │
│      "symbol": "ADA-USD",                                   │
│      "side": "buy",                                         │
│      "status": "filled",                                    │
│      "filled_size": "100",                                  │
│      "avg_price": "0.4505"                                  │
│    }                                                        │
│  }                                                          │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
[5] UserStreamDataSource._process_event_message()
            │
            ├─> Filter by channel
            └─> Put in asyncio.Queue
            │
            ▼
[6] Connector listens to queue and processes events
            │
            ├─> Orders → _process_order_message()
            ├─> Positions → _update_positions()
            └─> Balance → _update_balances()
            │
            ▼
[7] Update strategy state in real-time
```

### WebSocket Channels:

Located in `strike_perpetual_api_user_stream_data_source.py:76`

| Channel | Purpose | Data |
|---------|---------|------|
| `orders` | Order status updates | Order fills, cancels, rejects |
| `positions` | Position changes | Size, entry price, PnL |
| `balance` | Balance updates | Available balance, margin |

### Ping/Pong Mechanism:

```
Every 30 seconds:
    Send: {"method": "ping"}
    Receive: {"method": "pong"}

This keeps the WebSocket connection alive and prevents timeouts.
```

## 8. Configuration Flow

```
┌────────────────────────────────────────────────────────────────┐
│                    CONFIGURATION LOADING                       │
└────────────────────────────────────────────────────────────────┘

[1] User creates config file: conf/strategies/my_strike_strategy.yml
            │
            ├─ strategy: perpetual_market_making
            ├─ derivative: strike_perpetual
            ├─ market: ADA-USD
            ├─ strike_perpetual_account_id: "0199f06b-911f..."
            ├─ strike_perpetual_api_key: "sk_bot_4GXFf..."
            ├─ strike_perpetual_base_url: "http://localhost:8080"
            ├─ strike_perpetual_ws_url: "ws://localhost:8083/ws"
            └─ strike_perpetual_price_url: "http://localhost:8082"
            │
            ▼
[2] Hummingbot loads config via strike_perpetual_utils.py
            │
            ├─> StrikePerpetualConfigMap
            └─> Validates required fields (account_id, api_key)
            │
            ▼
[3] Creates StrikePerpetualDerivative instance
            │
            ├─> __init__() receives all config params
            ├─> Creates StrikePerpetualAuth with account_id + api_key
            ├─> Creates OrderBookDataSource for market data
            ├─> Creates UserStreamDataSource for events
            └─> Registers with Hummingbot core
            │
            ▼
[4] Strategy can now call:
            │
            ├─> market.get_balance("USD")
            ├─> market.buy("ADA-USD", 100, OrderType.LIMIT, 0.45)
            ├─> market.get_price("ADA-USD", is_buy=True)
            └─> market.get_position("ADA-USD")
```

### Configuration Parameters:

Located in `strike_perpetual_utils.py:23`

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `strike_perpetual_account_id` | ✓ | - | Strike account UUID |
| `strike_perpetual_api_key` | ✓ | - | Bot API key (sk_bot_...) |
| `strike_perpetual_base_url` | - | `http://localhost:8080` | Trading API |
| `strike_perpetual_ws_url` | - | `ws://localhost:8083/ws` | WebSocket API |
| `strike_perpetual_price_url` | - | `http://localhost:8082` | Price Service |

## 9. Key Design Decisions

### ✅ Connector-Level USD/USDT Conversion

**Location:** `strike_perpetual_derivative.py:220`

**Why:** PMM strategy calls `market.get_price()` - conversion must happen in connector, not strategy.

**Alternative considered:** Modifying PMM strategy to handle USD/USDT conversion
- ❌ Would require forking core Hummingbot code
- ❌ Wouldn't work with other strategies
- ✓ Connector-level fix is transparent to all strategies

### ✅ Synthetic Order Book

**Location:** `strike_perpetual_api_order_book_data_source.py:195`

**Why:** Strike V2 doesn't expose `/v2/depth` endpoint - must create from mark prices.

**Alternative considered:** Aggregating real orders from matching engine
- ❌ Would require backend API changes
- ❌ More complex implementation
- ✓ Synthetic book with mark price is simpler and sufficient

### ✅ 60-Second USDT/USD Cache

**Location:** `strike_perpetual_derivative.py:240`

**Why:** Balance between accuracy and API rate limits. USDT/USD is stable (~1.0).

**Alternatives:**
- No cache: ❌ Excessive API calls to Binance
- 5-minute cache: ❌ Too stale for accurate calculations
- ✓ 60 seconds: Good balance for stable pair

### ✅ Dual Balance Storage (USD + USDT keys)

**Location:** `strike_perpetual_derivative.py:490`

**Why:** Trading pairs use USD, but actual collateral is USDT. Both need to work.

**Without dual storage:**
- ❌ `status` command shows 0 balance
- ❌ PMM budget checker fails
- ✓ Storing under both keys fixes all issues

### ✅ API Key Authentication

**Location:** `strike_perpetual_auth.py:33`

**Why:** More secure than account_id-only auth. Required for production trading.

**Alternatives:**
- Account ID only: ❌ Less secure, no audit trail
- ✓ API key: Secure, scoped, revokable

## 10. Complete Data Flow Example

```
┌────────────────────────────────────────────────────────────────┐
│          COMPLETE FLOW: PLACE BUY ORDER FOR ADA-USD            │
└────────────────────────────────────────────────────────────────┘

[T=0s] PMM Strategy decides to place order
        ├─> Checks spread: 5%
        ├─> Checks balance via get_price("USD-USDT") → 1.0001
        └─> Calls market.buy("ADA-USD", 100, LIMIT, 0.45)

[T=0.1s] StrikePerpetualDerivative._place_order()
        ├─> Creates InFlightOrder with client_order_id
        ├─> Converts to Strike format
        └─> Sends POST /v2/order with X-API-Key header

[T=0.2s] Strike Trading API receives request
        ├─> Validates API key → account_id
        ├─> Checks balance: 10000 USDT available
        ├─> Checks margin requirements: OK
        └─> Forwards to Matching Engine

[T=0.3s] Matching Engine processes order
        ├─> Assigns order_id: 456
        ├─> Places on order book
        └─> Broadcasts to WebSocket subscribers

[T=0.4s] WebSocket sends event
        {"channel": "orders", "data": {"order_id": 456,
         "status": "open", "symbol": "ADA-USD"}}

[T=0.5s] UserStreamDataSource receives event
        └─> Puts in asyncio.Queue

[T=0.6s] Connector processes event
        ├─> Finds InFlightOrder by order_id
        ├─> Updates state: PENDING → OPEN
        └─> Emits BuyOrderCreatedEvent

[T=5s] Another trader matches the order
        └─> Matching Engine fills order

[T=5.1s] WebSocket sends fill event
        {"channel": "orders", "data": {"order_id": 456,
         "status": "filled", "filled_size": "100",
         "avg_price": "0.4505"}}

[T=5.2s] Connector processes fill
        ├─> Updates InFlightOrder state: OPEN → FILLED
        ├─> Emits OrderFilledEvent
        ├─> Updates balance: 10000 - 45.05 = 9954.95 USDT
        ├─> Updates position: +100 ADA @ 0.4505
        └─> Stores under both "USD" and "USDT" keys

[T=5.3s] Strategy receives OrderFilledEvent
        ├─> Recalculates inventory
        ├─> Adjusts spreads if needed
        └─> Places new orders to maintain spread
```

## 11. API Endpoints Reference

### Trading API (Port 8080)

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `/healthz` | GET | Health check | No |
| `/v2/markets` | GET | List all markets | No |
| `/v2/account` | GET | Get account info | Yes |
| `/v2/order` | POST | Create order | Yes |
| `/v2/order` | GET | Get order status | Yes |
| `/v2/order/cancel` | DELETE | Cancel order | Yes |
| `/v2/openOrders` | GET | List open orders | Yes |
| `/v2/positions` | GET | Get positions | Yes |
| `/v2/deposit` | POST | Deposit funds | Yes |
| `/v2/withdraw` | POST | Withdraw funds | Yes |

### Price Service (Port 8082)

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `/v2/exchangeInfo` | GET | Market metadata | No |
| `/v2/ticker/price` | GET | Current prices | No |
| `/v2/ticker/bookTicker` | GET | Best bid/ask | No |
| `/v2/premiumIndex` | GET | Funding rates | No |

### WebSocket (Port 8083)

| Channel | Purpose | Subscribe Payload |
|---------|---------|-------------------|
| `orders` | Order updates | `{"method": "subscribe", "channel": "orders", "account_id": "..."}` |
| `positions` | Position updates | `{"method": "subscribe", "channel": "positions", "account_id": "..."}` |
| `balance` | Balance updates | `{"method": "subscribe", "channel": "balance", "account_id": "..."}` |
| `trades` | Public trades | `{"method": "subscribe", "channel": "trades", "symbol": "ADA-USD"}` |
| `orderbook` | Order book updates | `{"method": "subscribe", "channel": "orderbook", "symbol": "ADA-USD"}` |

## 12. Error Handling

### Common Errors:

```
Error: "No order book exists for 'USD-USDT'"
Fix: Implemented in get_price() - fetches from Binance

Error: "No order book exists for 'ADA-USDT'"
Fix: Implemented in get_price() - converts to ADA-USD

Error: "Balance shows 0 in USD"
Fix: Store balances under both USD and USDT keys

Error: "Empty bid/ask prices"
Fix: Initialize order book with init_orderbook.sh script

Error: "API key authentication failed"
Fix: Ensure API key is in database and services are restarted
```

### Debugging:

```bash
# Check Hummingbot logs
tail -f logs/logs_conf_perpetual_market_making_1.log

# Check Strike API logs
docker-compose logs -f api

# Check matching engine logs
docker-compose logs -f engines

# Check WebSocket connection
docker-compose logs -f api | grep -i websocket
```

## 13. Testing Checklist

- [ ] API key authentication works
- [ ] Can fetch account balance
- [ ] Can place limit orders
- [ ] Can cancel orders
- [ ] WebSocket receives order events
- [ ] WebSocket receives position events
- [ ] WebSocket receives balance events
- [ ] USD/USDT conversion works
- [ ] Balance shows correctly in `status` command
- [ ] Synthetic order book has bid/ask prices
- [ ] Orders fill correctly
- [ ] Position tracking updates
- [ ] Funding rates update

## Summary

The Strike Perpetual connector is a **full-featured perpetual futures connector** that:

1. **Extends** Hummingbot's `PerpetualDerivativePyBase` class
2. **Authenticates** via API keys with X-API-Key headers
3. **Handles** USD/USDT currency mismatch transparently
4. **Creates** synthetic order books from mark prices
5. **Tracks** orders, positions, and balances in real-time via WebSocket
6. **Supports** market making strategies with proper collateral calculations
7. **Integrates** seamlessly with existing PMM strategies

The connector's architecture prioritizes **reliability**, **transparency**, and **maintainability** while working around Strike V2 API limitations (no depth endpoint, USD/USDT mismatch).

## Related Documentation

- [Quick Start Guide](./QUICKSTART.md) - Setup and run in 5 minutes
- [API Key Setup](./API_KEY_SETUP.md) - Generate and configure API keys
- [Hummingbot Setup](./HUMMINGBOT_SETUP.md) - Detailed configuration guide
