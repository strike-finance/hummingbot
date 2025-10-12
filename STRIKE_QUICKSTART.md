# 🚀 Strike v2 + Hummingbot Quick Start Guide

## ✅ What's Ready

- **Strike v2 Backend**: Running on `http://localhost:8080`
- **Strike Connector**: Installed at `hummingbot/connector/derivative/strike_perpetual/`
- **Test Account**: `0199dc01-720d-7314-84d3-b3c3a102a9f9`
- **Test Balance**: $1,000.50 USDT
- **Market**: BTCUSDT (trading enabled)

---

## 🏃 Start Hummingbot

### Option 1: Direct Run (Quickest)

```bash
cd /Users/hoangvu/hade/strike/hummingbot

# Run Hummingbot directly
./bin/hummingbot.py
```

### Option 2: With Conda (If you use conda)

```bash
cd /Users/hoangvu/hade/strike/hummingbot

# Activate conda environment
conda activate hummingbot

# Run Hummingbot
./bin/hummingbot.py
```

---

## 🔌 Connect to Strike

Once Hummingbot starts, in the CLI:

```
>>> connect strike_perpetual
```

**When prompted, enter:**

1. **Strike account ID**: `0199dc01-720d-7314-84d3-b3c3a102a9f9`
2. **Strike API base URL** (press Enter for default): `http://localhost:8080`
3. **Strike WebSocket URL** (press Enter for default): `ws://localhost:8081/ws`

---

## 📊 Check Your Setup

```
# Check connection
>>> status

# Check balance
>>> balance

# List trading pairs
>>> list
```

---

## 🤖 Create Your First Strategy

### Quick Test Strategy:

```
>>> create

# Choose strategy
What is your market making strategy? >>> pure_market_making

# Configure
Exchange >>> strike_perpetual
Trading pair >>> BTC-USDT
Bid spread >>> 0.01
Ask spread >>> 0.01
Order amount >>> 0.001
```

### Start Trading:

```
>>> start

# Monitor
>>> status

# Check orders
>>> orders

# Stop
>>> stop
```

---

## 📍 Important URLs

- **Strike API**: http://localhost:8080
- **Strike WebSocket**: ws://localhost:8081/ws
- **API Health**: http://localhost:8080/healthz

---

## 🔧 Troubleshooting

### If Hummingbot won't start:

```bash
# Install dependencies
cd /Users/hoangvu/hade/strike/hummingbot
pip3 install -e .

# Or install from requirements
pip3 install -r requirements.txt
```

### Check Strike Backend:

```bash
# Check if Strike is running
curl http://localhost:8080/healthz

# Check services
cd /Users/hoangvu/hade/strike/strike-v2-backend
docker-compose ps
```

### View Logs:

```bash
# Strike API logs
docker logs -f strike-api

# Strike Engines logs
docker logs -f strike-engines

# Hummingbot logs
tail -f logs/hummingbot_logs.log
```

---

## 🎯 Test Commands

### Check Account:
```bash
curl "http://localhost:8080/v2/account?account_id=0199dc01-720d-7314-84d3-b3c3a102a9f9"
```

### Check Positions:
```bash
curl "http://localhost:8080/v2/positions?account_id=0199dc01-720d-7314-84d3-b3c3a102a9f9"
```

### Check Open Orders:
```bash
curl "http://localhost:8080/v2/openOrders?account_id=0199dc01-720d-7314-84d3-b3c3a102a9f9"
```

---

## 📝 Your Configuration

**Account Details:**
- **Account ID**: `0199dc01-720d-7314-84d3-b3c3a102a9f9`
- **Balance**: $1,000.50 USDT
- **Trading Pair**: BTC-USDT
- **Market Status**: Trading

**Strike Services:**
- **API**: http://localhost:8080 ✅
- **WebSocket**: ws://localhost:8081/ws ✅
- **Price Service**: http://localhost:8082 ✅

---

## 🎉 You're Ready!

Just run:
```bash
cd /Users/hoangvu/hade/strike/hummingbot
./bin/hummingbot.py
```

Then type `connect strike_perpetual` and start trading! 🚀
