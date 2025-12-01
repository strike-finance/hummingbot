# 🔑 Strike v2 API Key Authentication Setup

## Overview

Strike v2 now supports **API Key authentication** for bot/automated trading, making it easy to integrate with Hummingbot and other trading bots without requiring JWT wallet signatures.

---

## 🎯 API Key Scopes

### Three Types of API Keys:

1. **`admin` scope**
   - Access to admin endpoints only
   - Can do: Direct deposits, market updates
   - Cannot do: Trading operations

2. **`bot` scope**
   - Access to trading endpoints only
   - Can do: Create/cancel orders, get positions, view trading history
   - Cannot do: Admin operations
   - **Perfect for Hummingbot market making!**

3. **`both` scope**
   - Access to all endpoints (admin + trading)
   - Superuser key for complete control

---

## 🔧 Current Configuration

### API Keys Configured:

```toml
# Admin key - for deposits and market management
[[admin.api_keys]]
key = "admin-dev-key-12345"
scope = "admin"
name = "Admin Development Key"

# Hummingbot bot key - for automated trading
[[admin.api_keys]]
key = "hummingbot-mm-key-67890"
scope = "bot"
account_id = "0199f06b-911f-7ce8-987d-c2ff4798a06c"
name = "Hummingbot Market Maker Bot"

# Superuser key - for both admin and trading
[[admin.api_keys]]
key = "superuser-key-99999"
scope = "both"
account_id = "0199f06b-911f-7ce8-987d-c2ff4798a06c"
name = "Superuser Key (Admin + Trading)"
```

**Location**: `/Users/hoangvu/hade/strike/strike-v2-backend/services/api/config/config.local.toml`

---

## 🚀 How to Use

### For Hummingbot:

1. **Start Hummingbot**:
   ```bash
   cd /Users/hoangvu/hade/strike/hummingbot

   # Optional: Set password as environment variable
   export CONFIG_PASSWORD="dev"

   # Run Hummingbot
   ./bin/hummingbot.py
   ```

2. **Connect with API Key**:

   In Hummingbot CLI, type:
   ```
   >>> connect strike_perpetual
   ```

   **When prompted, enter:**

   - **Strike account ID**: `0199f06b-911f-7ce8-987d-c2ff4798a06c`
   - **Strike API key**: `hummingbot-mm-key-67890`
   - **Strike API base URL**: `http://localhost:8080` (or press Enter for default)
   - **Strike WebSocket URL**: `ws://localhost:8083/ws` (or press Enter for default)

3. **The bot will now use API key authentication** - no JWT required!

   The X-API-Key header will be automatically included in all requests.

---

## 📡 API Usage Examples

### Trading with Bot API Key:

**Create Order:**
```bash
curl -X POST "http://localhost:8080/v2/order" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hummingbot-mm-key-67890" \
  -d '{
    "symbol": "ADA-USDT",
    "side": "buy",
    "order_type": "limit",
    "quantity": "100",
    "price": "0.44",
    "time_in_force": "GTC"
  }'
```

**Get Positions:**
```bash
curl -H "X-API-Key: hummingbot-mm-key-67890" \
  "http://localhost:8080/v2/positions?symbol=ADA-USDT"
```

**Cancel Order:**
```bash
curl -X DELETE "http://localhost:8080/v2/order/cancel" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hummingbot-mm-key-67890" \
  -d '{
    "symbol": "ADA-USDT",
    "order_id": "<order_id>"
  }'
```

### Admin Operations with Admin API Key:

**Deposit Funds:**
```bash
curl -X POST "http://localhost:8080/admin/deposit" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: admin-dev-key-12345" \
  -d '{
    "account_id": "0199f06b-911f-7ce8-987d-c2ff4798a06c",
    "usd_value": "10000.00",
    "note": "Initial funding for Hummingbot bot"
  }'
```

---

## 🔒 Security Features

### Scope Enforcement:

✅ **Bot API key cannot access admin endpoints**
```bash
# This will fail with 403 Forbidden
curl -X POST "http://localhost:8080/admin/deposit" \
  -H "X-API-Key: hummingbot-mm-key-67890" \
  ...
```

✅ **Admin API key cannot access trading endpoints**
```bash
# This will fail with 403 Forbidden
curl -X POST "http://localhost:8080/v2/order" \
  -H "X-API-Key: admin-dev-key-12345" \
  ...
```

✅ **Bot API key is linked to specific account**
- Trading operations automatically use the account associated with the API key
- No need to pass account_id in requests when using API keys

---

## 🎨 Architecture

### Authentication Flow:

```
Hummingbot Bot
    |
    | X-API-Key: hummingbot-mm-key-67890
    v
Strike API (Port 8080)
    |
    | Validates API key
    | Checks scope: "bot"
    | Sets account_id: 0199f06b-911f-7ce8-987d-c2ff4798a06c
    v
Trading Endpoints
    |
    | POST /v2/order
    | GET /v2/positions
    | DELETE /v2/order/cancel
    v
Strike Engines (Port 8081)
    |
    v
Order Execution
```

### Flexible Authentication:

The Strike API now supports **two authentication methods**:

1. **JWT Authentication** (for manual users)
   - Wallet signature required
   - Used by web interface

2. **API Key Authentication** (for bots)
   - Simple header-based auth
   - No wallet signatures needed
   - Perfect for automated trading

---

## 📝 Adding New API Keys

To add a new bot API key, edit `config.local.toml`:

```toml
[[admin.api_keys]]
key = "new-bot-key-xxxxx"
scope = "bot"
account_id = "<account_id>"
name = "My New Trading Bot"
```

Then rebuild and restart the API service:

```bash
cd /Users/hoangvu/hade/strike/strike-v2-backend
docker-compose build api
docker-compose restart api
```

---

## 🔄 Reconnecting Hummingbot After Updates

If you update the connector code or need to reconnect:

```bash
cd /Users/hoangvu/hade/strike/hummingbot

# Clear connector cache
rm -rf conf/connectors/strike_perpetual*.yml

# Clear Python cache
find hummingbot/connector/derivative/strike_perpetual -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Reinstall
pip3 install -e .

# Restart Hummingbot
export CONFIG_PASSWORD="dev"
./bin/hummingbot.py
```

Then reconnect:
```
>>> connect strike_perpetual
```

---

## ✅ Verification

Test your setup:

```bash
# Run the comprehensive test script
/tmp/test_bot_api_key.sh
```

Expected results:
- ✅ Bot API key can access trading endpoints
- ✅ Bot API key cannot access admin endpoints
- ✅ Admin API key can access admin endpoints
- ✅ Admin API key cannot access trading endpoints
- ✅ Superuser key can access both

---

## 🎉 Ready for Market Making!

Your Hummingbot bot is now ready to trade on Strike v2 using secure API key authentication!

**Key Benefits:**
- No wallet signatures needed
- Account automatically linked via API key
- Scope-based security
- Easy to revoke/rotate keys
- Perfect for 24/7 automated trading

Happy trading! 🚀
