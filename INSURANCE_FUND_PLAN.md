# Insurance Fund Strategy - Implementation Plan

## Overview

An insurance fund strategy for Strike V2 perpetual exchange that monitors liquidations, takes over positions, and manages them to minimize losses.

---

## What is an Insurance Fund?

In perpetual futures exchanges, an **insurance fund** is a reserve that:

1. **Takes over liquidated positions** when a trader's margin is exhausted
2. **Absorbs losses** from positions that can't be closed at bankruptcy price
3. **Prevents auto-deleveraging** of profitable traders
4. **Maintains market stability** during high volatility

### Example Flow

```
[1] Trader has position:
    - Long 1000 ADA @ $0.45
    - 10x leverage
    - Liquidation price: $0.40
    - Bankruptcy price: $0.39

[2] Price drops to $0.40
    - Liquidation triggered
    - Position marked for closure

[3] Market order to close
    - Try to close at $0.40
    - But price gaps down to $0.38
    - Loss: (0.40 - 0.38) × 1000 = $20

[4] Insurance fund steps in
    - Takes over position at $0.38
    - Now short 1000 ADA @ $0.38
    - Fund absorbs the $20 loss

[5] Insurance fund manages position
    - Closes position at $0.39
    - Recovers $10 of the $20 loss
    - Net loss: $10 to the fund
```

---

## Strategy Requirements

### Core Functions

1. **Liquidation Monitoring**
   - Listen to WebSocket liquidation events
   - Track positions approaching liquidation
   - Monitor mark price vs liquidation prices

2. **Position Taking**
   - Accept liquidated positions from matching engine
   - Take opposite side (liquidated long → fund shorts)
   - Record entry price and size

3. **Position Management**
   - Monitor unrealized PnL
   - Set stop-loss and take-profit levels
   - Rebalance based on risk limits

4. **Risk Management**
   - Max position size per symbol
   - Max total exposure across all symbols
   - Diversification limits

5. **Reporting**
   - Fund balance tracking
   - PnL per position
   - Historical performance

---

## Implementation Architecture

### Option 1: Hummingbot Strategy (Recommended for Testing)

```
┌─────────────────────────────────────────────────────────┐
│              Insurance Fund Strategy                    │
│  (hummingbot/strategy/insurance_fund/)                 │
└────────────────┬────────────────────────────────────────┘
                 │
                 ├─ __init__.py
                 ├─ insurance_fund.py        (main strategy)
                 ├─ insurance_fund_config.py (configuration)
                 └─ liquidation_handler.py   (liquidation logic)
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│         Strike Perpetual Connector                      │
│  - listen_for_liquidations() [NEW]                     │
│  - take_liquidated_position() [NEW]                    │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│              Strike V2 Backend                          │
│  - WebSocket: liquidation events                       │
│  - API: POST /v2/insurance/take-position               │
└─────────────────────────────────────────────────────────┘
```

### Option 2: Standalone Service (Production)

```
┌─────────────────────────────────────────────────────────┐
│     Insurance Fund Service (Go)                         │
│  - services/insurance/                                  │
│  - Monitors liquidations via WebSocket                  │
│  - Takes positions via API                              │
│  - Manages positions independently                      │
└─────────────────────────────────────────────────────────┘
```

---

## What We Need to Implement

### Backend Changes (Strike V2)

1. **Liquidation Events**
   - Add WebSocket channel: `liquidations`
   - Publish liquidation events with position details
   - Include bankruptcy price, liquidation price, etc.

2. **Insurance Fund Endpoints**
   - `POST /v2/insurance/take-position` - Accept liquidated position
   - `GET /v2/insurance/positions` - Get fund positions
   - `GET /v2/insurance/balance` - Get fund balance
   - `POST /v2/insurance/close-position` - Close a position

3. **Insurance Fund Account**
   - Special account type: `insurance_fund`
   - Can take positions without margin requirements
   - Separate balance tracking

### Connector Changes (Hummingbot)

1. **Add liquidation support to Strike connector:**
   ```python
   # strike_perpetual_derivative.py

   def listen_for_liquidations(self):
       """Subscribe to liquidation events"""
       pass

   def take_liquidated_position(self, liquidation_event):
       """Take over a liquidated position"""
       pass
   ```

2. **Add WebSocket channel:**
   ```python
   # strike_perpetual_api_user_stream_data_source.py

   LIQUIDATIONS_ENDPOINT_NAME = "liquidations"
   ```

### Strategy Implementation (Hummingbot)

```python
# hummingbot/strategy/insurance_fund/insurance_fund.py

class InsuranceFundStrategy:
    def __init__(self, connectors, config):
        self.max_position_size = config.max_position_size
        self.max_exposure = config.max_exposure
        self.take_profit_pct = config.take_profit_pct
        self.stop_loss_pct = config.stop_loss_pct

    def on_liquidation_event(self, event):
        """Handle incoming liquidation"""
        # Check if we should take this position
        if self.should_take_position(event):
            self.take_position(event)

    def should_take_position(self, event):
        """Risk checks before taking position"""
        # Check max position size
        # Check total exposure
        # Check fund balance
        pass

    def manage_positions(self):
        """Periodic position management"""
        for position in self.positions:
            # Check PnL
            # Close if take-profit hit
            # Close if stop-loss hit
            # Rebalance if needed
            pass
```

---

## Development Phases

### Phase 1: Backend Infrastructure (Strike V2)

**Goal:** Add liquidation support to Strike V2

**Tasks:**
1. ✅ Design liquidation event structure
2. ✅ Add WebSocket liquidation channel
3. ✅ Create insurance fund endpoints
4. ✅ Create insurance fund account type
5. ✅ Test liquidation flow manually

**Estimated time:** 2-3 days

### Phase 2: Connector Support (Hummingbot)

**Goal:** Add liquidation support to Strike connector

**Tasks:**
1. ✅ Add liquidation WebSocket subscription
2. ✅ Add liquidation event parsing
3. ✅ Add take_position() method
4. ✅ Add position management methods
5. ✅ Test with mock liquidations

**Estimated time:** 1-2 days

### Phase 3: Strategy Implementation (Hummingbot)

**Goal:** Implement insurance fund strategy

**Tasks:**
1. ✅ Create strategy structure
2. ✅ Implement liquidation handler
3. ✅ Implement position manager
4. ✅ Implement risk management
5. ✅ Add configuration template
6. ✅ Test with live liquidations

**Estimated time:** 2-3 days

### Phase 4: Testing & Optimization

**Goal:** Ensure reliability and performance

**Tasks:**
1. ✅ Stress test with many liquidations
2. ✅ Test position management logic
3. ✅ Optimize for latency
4. ✅ Add monitoring and alerts
5. ✅ Document usage

**Estimated time:** 1-2 days

---

## Current Status

Looking at git status from earlier conversation:
```
?? INSURANCE_FUND_IMPLEMENTATION.md
?? INSURANCE_FUND_SUMMARY.md
?? hummingbot/strategy/insurance_fund/
?? hummingbot/templates/conf_insurance_fund_strategy_TEMPLATE.yml
```

**These files were mentioned but not found in current directory.**

---

## Next Steps

### Immediate Actions

1. **Decide on approach:**
   - Option A: Hummingbot strategy (easier for testing)
   - Option B: Standalone Go service (better for production)

2. **Start with backend or connector?**
   - Backend first: Need liquidation events infrastructure
   - Connector first: Can mock liquidation events for development

3. **What do you want to focus on?**
   - Full implementation?
   - Just monitoring liquidations?
   - Just position management?

### Quick Start Option

If you want to start immediately with Hummingbot:

1. **Create mock liquidation generator**
2. **Build strategy that logs liquidations**
3. **Add position taking logic**
4. **Add position management**
5. **Connect to real backend later**

---

## Questions for You

1. **Scope:** Do you want a full insurance fund or just liquidation monitoring?

2. **Platform:** Hummingbot strategy or standalone service?

3. **Priority:** What's most important?
   - Speed (get something working fast)
   - Completeness (full featured solution)
   - Testing (easy to test and iterate)

4. **Backend state:** Does Strike V2 backend already support liquidations?
   - Are liquidation events published?
   - Are there insurance fund endpoints?

5. **Use case:** Is this for:
   - Production trading?
   - Testing and development?
   - Learning/demonstration?

Let me know your preferences and I'll help you implement it! 🚀
