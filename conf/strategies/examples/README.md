# Strike Perpetual Market Making Strategy Examples

Example configurations for running market making bots on Strike Perpetual.

## Available Configs

| File | Market | Base Size | Level Increment | Total Levels |
|------|--------|-----------|-----------------|--------------|
| `btc_usd_mm.yml` | BTC-USD | 0.01 BTC | +0.005 | 7 |
| `eth_usd_mm.yml` | ETH-USD | 0.1 ETH | +0.05 | 7 |
| `sol_usd_mm.yml` | SOL-USD | 5 SOL | +2 | 7 |
| `ada_usd_mm.yml` | ADA-USD | 500 ADA | +100 | 7 |

## Common Settings

All configs share these settings:
- **Leverage**: 10x
- **Bid/Ask Spread**: 0.15%
- **Order Levels**: 7 on each side (14 total orders)
- **Level Spread**: 0.1% between levels
- **Refresh Rate**: 5 seconds
- **Profit Taking**: 0.5%
- **Stop Loss**: 2%

## Usage

### Single Bot (copy to strategies folder)

```bash
cp conf/strategies/examples/btc_usd_mm.yml conf/strategies/
```

Then in Hummingbot:
```
>>> import --strategy btc_usd_mm.yml
>>> start
```

### Multiple Bots (use docker-compose-multi.yml)

```bash
# Copy all configs
cp conf/strategies/examples/*.yml conf/strategies/

# Create log directories
mkdir -p logs/{btc,eth,sol,ada} data/{btc,eth,sol,ada}

# Start all bots
docker-compose -f docker-compose-multi.yml up -d

# Check status
docker ps

# Attach to individual bot
docker attach hummingbot-btc
```

## Customization

Adjust these key parameters based on your needs:

| Parameter | Description | Aggressive | Conservative |
|-----------|-------------|------------|--------------|
| `bid_spread` / `ask_spread` | Distance from mid price | 0.1% | 0.3% |
| `order_amount` | Base order size | Higher | Lower |
| `order_levels` | Number of price levels | 10+ | 3-5 |
| `order_refresh_time` | How often to update | 3s | 15s |

## Detach from Bot

Press `Ctrl+P` then `Ctrl+Q` to detach without stopping.

## View Logs

```bash
docker logs --tail 100 hummingbot-btc
```

