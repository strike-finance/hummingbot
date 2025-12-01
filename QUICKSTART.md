# Strike Perpetual Hummingbot Connector - Quick Start Guide

This guide will help you quickly set up and run the Strike Perpetual connector with Hummingbot for market making.

## Prerequisites

- Strike V2 backend running locally (see [strike-v2-backend setup](../strike-v2-backend/README.md))
- Python 3.10+
- Hummingbot installed

## Quick Setup

### 1. Start Strike V2 Backend

```bash
cd /path/to/strike-v2-backend
docker-compose -f docker-compose.local.yml up -d

# Wait for services to initialize
sleep 15
```

### 2. Initialize Account and API Keys

The backend needs a bot account with API key for Hummingbot to connect:

```bash
# Account Details (for testing)
ACCOUNT_ID="0199f06b-911f-7ce8-987d-c2ff4798a06c"
BOT_API_KEY="sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o"
```

**Important**: The API key must be inserted into the database and services restarted:

```bash
cd strike-v2-backend
# The key is already in the database, just restart services
docker-compose -f docker-compose.local.yml restart api engines
```

For detailed API key setup, see [API_KEY_SETUP.md](./API_KEY_SETUP.md).

### 3. Initialize Order Book

Strike V2 needs liquidity in the order book for market making:

```bash
cd strike-v2-backend
./scripts/init_orderbook.sh
```

This creates limit orders on both sides of the market for ADA-USD and BTC-USD.

### 4. Configure Hummingbot

Create or edit your strategy config file:

```bash
cd hummingbot
cp conf/strategies/conf_perpetual_market_making_1.yml conf/strategies/my_strike_strategy.yml
```

Edit the config:

```yaml
strategy: perpetual_market_making
derivative: strike_perpetual
market: ADA-USD

# Your Strike API credentials
strike_perpetual_account_id: "0199f06b-911f-7ce8-987d-c2ff4798a06c"
strike_perpetual_api_key: "sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o"

# Strategy parameters
leverage: 20
bid_spread: 5.0
ask_spread: 5.0
order_amount: 1.0
order_refresh_time: 2.0
```

### 5. Run Hummingbot

```bash
./bin/hummingbot.py
```

In the Hummingbot console:

```
start --script conf_perpetual_market_making_1.yml
```

## Verification

Check that everything is working:

```bash
# Check account balance
curl -H "X-API-Key: sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o" \
  "http://localhost:8080/v2/account?account_id=0199f06b-911f-7ce8-987d-c2ff4798a06c"

# Check market data
curl "http://localhost:8080/v2/markets" | jq '.markets["ADA-USD"]'

# Check open orders
curl -H "X-API-Key: sk_bot_4GXFfnTnxfl0uy26aka-eBMbbQrkF1cgtqNFGO5QA-o" \
  "http://localhost:8080/v2/openOrders?symbol=ADA-USD"
```

## Trading Pairs

Available trading pairs:
- `ADA-USD` - Cardano/USD perpetual
- `BTC-USD` - Bitcoin/USD perpetual

## Troubleshooting

### "unexpected error running clock tick"

This was caused by USDT collateral vs USD trading pairs. The fix is already implemented in the connector to handle USD/USDT conversion automatically.

### "No order book exists for 'ADA-USDT'"

The connector automatically converts USDT-based pairs to USD-based pairs since Strike uses USD for trading pairs but USDT for collateral.

### Empty bid/ask prices

Run the order book initialization script:

```bash
cd strike-v2-backend
./scripts/init_orderbook.sh
```

### Authentication failures

Ensure:
1. API key is in the database
2. Services are restarted after key insertion
3. Using the correct API key in Hummingbot config

## Important Notes

1. **Collateral**: Strike uses USDT as collateral but trading pairs use USD
2. **Order Book**: Since there's no depth endpoint, the connector creates a synthetic order book from market prices
3. **Price Conversion**: USD and USDT are treated as 1:1 for collateral calculations

## Next Steps

- Adjust strategy parameters in your config file
- Monitor performance in Hummingbot logs
- Check positions and PnL via Strike API

## Related Documentation

- [API Key Setup](./API_KEY_SETUP.md) - Detailed guide on API key management
- [Hummingbot Setup](./HUMMINGBOT_SETUP.md) - Detailed Hummingbot configuration
- [Backend Order Book Setup](../strike-v2-backend/ORDERBOOK_SETUP.md) - Order book initialization guide

## Support

For issues or questions:
- Check the logs: `logs/logs_conf_perpetual_market_making_1.log`
- Review Strike API logs: `docker-compose logs api`
- Check matching engine logs: `docker-compose logs engines`
