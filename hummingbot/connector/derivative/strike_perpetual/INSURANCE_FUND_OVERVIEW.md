# Insurance Fund (IF) Overview for Strike v2

## Table of Contents
1. [What is the Insurance Fund?](#what-is-the-insurance-fund)
2. [Why Strike v2 Needs It](#why-strike-v2-needs-it)
3. [How It Works with Strike v2](#how-it-works-with-strike-v2)
4. [Hummingbot Implementation](#hummingbot-implementation)
5. [Key Metrics & Monitoring](#key-metrics--monitoring)

---

## What is the Insurance Fund?

The Insurance Fund (IF) is Strike v2's **safety mechanism** that prevents traders from going into negative balance during liquidations. It is:

- **A special trading account** with `AccountType = "if"` (Insurance Fund)
- **An active risk manager** that absorbs and unwinds bankrupt positions
- **A capital pool** funded by:
  - Liquidation fees (100% of all liquidation fees)
  - Profits from unwinding positions (when IF exits above entry price)

### Key Characteristics

| Property | Value |
|----------|-------|
| Account Type | `AccountTypeInsuranceFund` ("if") |
| Purpose | Absorb bankrupt positions from failed liquidations |
| Funding | Liquidation fees + trading profits |
| Operation | Actively managed trading system |
| Risk Model | Predefined limits and tolerances |

---

## Why Strike v2 Needs It

### The Liquidation Problem

When a trader's position moves against them, the following sequence occurs:

```
1. Price moves unfavorably
   ↓
2. Margin Ratio reaches 100%
   ↓
3. Liquidation triggered
   ↓
4. Liquidation engine places Limit IOC @ Bankruptcy Price
   ↓
5. IF FILLED: Position closed, trader's loss capped ✅
   IF UNFILLED: Position becomes "Bankrupt" ❌
   ↓
6. Who absorbs the loss?
```

### Without Insurance Fund

The exchange faces three bad options:

1. **Negative Balances**: Allow user accounts to go negative
   - Bad UX
   - Credit risk for exchange
   - Recovery challenges

2. **Immediate Socialization**: ADL all counterparties immediately
   - Unfair to profitable traders
   - Creates distrust
   - May trigger cascading liquidations

3. **Exchange Absorbs**: Use exchange reserves
   - Unsustainable
   - Risk of insolvency
   - No separation of concerns

### With Insurance Fund

The IF provides a **buffer layer**:

```
Trader Loss → Liquidation → IF Absorption → Gradual Unwinding → ADL (if needed)
    ↓              ↓              ↓                ↓                  ↓
User's margin  Order book    Bankruptcy       Market impact      Last resort
               execution      Price entry      minimized          only
```

### The Loss Waterfall

Strike v2's loss waterfall (from documentation Section 8):

```
┌─────────────────────────────────────────────────────────┐
│ 1. Trader's Margin & PnL                                │
│    └─> Losses absorbed by trader's own balance          │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 2. Liquidation via Order Book                           │
│    └─> Limit IOC @ Bankruptcy Price                     │
│    └─> Liquidation fees → Insurance Fund                │
└─────────────────────────────────────────────────────────┘
                        ↓ (if unfilled)
┌─────────────────────────────────────────────────────────┐
│ 3. Insurance Fund ⭐                                     │
│    └─> Takes over unfilled residual @ Bankruptcy Price  │
│    └─> Gradually unwinds with minimal market impact     │
│    └─> Can reject if breach risk limits → ADL           │
└─────────────────────────────────────────────────────────┘
                        ↓ (if IF breaches limits)
┌─────────────────────────────────────────────────────────┐
│ 4. ADL (Auto-Deleveraging)                              │
│    └─> Counterparty positions force-closed              │
│    └─> Risk socialized across profitable traders        │
└─────────────────────────────────────────────────────────┘
```

---

## How It Works with Strike v2

### A. Position Flow

#### Normal User Liquidation Flow

```
┌──────────────────────────────────────────────────────────┐
│ User Position                                            │
│ Symbol: ADA-USD                                          │
│ Size: 1000 ADA Long                                      │
│ Entry Price: $0.44                                       │
│ Liquidation Price: $0.42                                 │
│ Bankruptcy Price: $0.40                                  │
└────────────────────┬─────────────────────────────────────┘
                     │
                     │ Mark Price drops to $0.42
                     │ Margin Ratio ≥ 100%
                     ↓
┌──────────────────────────────────────────────────────────┐
│ Liquidation Engine                                       │
│ ├─> Cancels risk-increasing orders                       │
│ ├─> Places Limit IOC Sell 1000 ADA @ $0.40              │
│ │   (Bankruptcy Price)                                   │
│ └─> Result:                                              │
│     ├─ Filled: 700 ADA @ avg $0.405 ✓                   │
│     └─ Unfilled: 300 ADA ❌ (insufficient liquidity)     │
└────────────────────┬─────────────────────────────────────┘
                     │
                     │ Transfer unfilled portion
                     ↓
┌──────────────────────────────────────────────────────────┐
│ Insurance Fund Account (Type: "if")                      │
│                                                          │
│ RECEIVES:                                                │
│ ├─ Position: Long 300 ADA                               │
│ ├─ Entry Price: $0.40 (Bankruptcy Price)                │
│ └─ Unrealized Loss: ($0.42 - $0.40) × 300 = -$6 📉      │
│                                                          │
│ TASK: Unwind this position back to the market           │
└────────────────────┬─────────────────────────────────────┘
                     │
                     ↓
              IF Unwinding Strategy
              (Hummingbot manages this)
```

#### Backend Account Structure

From `strike-v2-backend/pkg/models/enums.go`:

```go
type AccountType uint8

const (
    AccountTypeNormal        AccountType = iota + 1 // normal user
    AccountTypeMarketMaker                          // mm (market maker)
    AccountTypeInsuranceFund                        // if (insurance fund) ⭐
)
```

The IF account:
- Has its own `account_id` (UUID)
- Has its own API key for bot access
- Maintains positions just like any account
- But operates under different risk rules
- Can refuse to accept positions (triggers ADL)

### B. Unwinding Logic (Section 6.3 of Documentation)

The IF employs two unwinding modes:

#### Mode 1: MAKER (Default Behavior)

**Objective**: Unwind with minimal market impact, potentially capture profit

**Strategy**:
```
IF Position: Long 300 ADA @ $0.40 (Bankruptcy Price = Entry)
Current Mark Price: $0.45

Maker Strategy:
├─> Place Sell Limit Orders
├─> Price: Above BOTH entry and mark
│   └─> Example: $0.46 (entry + 15%, mark + 2.2%)
├─> Size: 10% of position per order (30 ADA)
├─> Refresh: Every 30 seconds
└─> Goal: Realize positive PnL

If filled @ $0.46:
└─> Profit = ($0.46 - $0.40) × 30 = $1.80 per fill 💰
```

**Parameters**:
- Order Size: 10-20% of position
- Spread: 10-50 bps above mark price
- Min Profit: 0-10 bps above entry (Bankruptcy Price)
- Order Type: Limit Maker
- Refresh Interval: 15-60 seconds

#### Mode 2: AGGRESSIVE (Risk-Driven)

**Objective**: Reduce exposure quickly, prioritize risk reduction over profit

**Triggers**:
- Margin Ratio ≥ 50% (liquidation is at 100%)
- Total Unrealized Loss ≥ $50,000
- Total Notional Exposure ≥ $1,000,000
- Utilization ≥ 80% of NAV

**Strategy**:
```
IF Position: Long 300 ADA @ $0.40
Current Mark Price: $0.45
Risk Metric: Margin Ratio = 55% ⚠️

Aggressive Strategy:
├─> Place Sell Limit IOC Orders
├─> Price: At or below mark (accept slippage)
│   └─> Example: $0.445 (mark - 1.1%, still 11% above entry)
├─> Size: 25-50% of position per order (75-150 ADA)
├─> Refresh: Every 10-15 seconds
└─> Goal: Close position fast

Even with slippage @ $0.445:
└─> Still profitable: ($0.445 - $0.40) × 75 = $3.375 💰
    But priority is RISK REDUCTION, not profit
```

**Parameters**:
- Order Size: 25-50% of position
- Slippage Tolerance: 20-100 bps
- Order Type: Limit IOC (Immediate-or-Cancel)
- Refresh Interval: 10-20 seconds

### C. Risk Management (Section 6.4)

The IF has **hard risk limits**:

```yaml
Risk Tolerances:

  # Exposure Limits
  max_total_notional_usd: 1000000
    # Total exposure across all positions
    # If breached → Aggressive Mode or Reject New Positions

  max_symbol_notional_usd: 200000
    # Per-symbol exposure limit
    # Prevents concentration risk

  max_per_direction_usd: 150000
    # Per-symbol, per-direction (long/short separately)
    # Example: Max $150k long ADA-USD, separate $150k short ADA-USD

  # Capital Utilization
  max_utilization_pct: 80
    # (Total Notional / Account Value) × 100
    # Ensures IF maintains liquidity buffer

  # Loss Thresholds
  max_unrealized_loss_usd: 50000
    # Total unrealized losses across all positions
    # If exceeded → Aggressive Mode

  margin_ratio_threshold_pct: 50
    # IF's own margin ratio (Maintenance Margin / Margin Balance)
    # If ≥ 50% → Aggressive Mode
    # Note: User liquidation happens at 100%

  # ADL Triggers
  adl_trigger_utilization_pct: 95
    # If utilization ≥ 95% → Refuse new positions, trigger ADL

  adl_emergency_loss_usd: 100000
    # If loss ≥ $100k → Emergency ADL to offload exposure
```

### D. IF Actions Based on Risk State

```
┌─────────────────────────────────────────────────────────┐
│ Risk State: NORMAL                                       │
│ ├─ Utilization < 80%                                     │
│ ├─ Margin Ratio < 50%                                    │
│ └─ Unrealized Loss < $50k                                │
│                                                          │
│ Actions:                                                 │
│ ✓ Accept new bankrupt positions                         │
│ ✓ Use MAKER mode unwinding (gradual, profit-seeking)    │
│ ✓ Low urgency                                            │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Risk State: ELEVATED                                     │
│ ├─ Utilization 80-95%                                    │
│ ├─ Margin Ratio 50-70%                                   │
│ └─ Unrealized Loss $50k-$100k                            │
│                                                          │
│ Actions:                                                 │
│ ✓ Still accept new positions (with caution)             │
│ ⚠️ Switch to AGGRESSIVE mode unwinding                   │
│ ⚠️ Increase order sizes, accept slippage                 │
│ ⚠️ High urgency to reduce exposure                       │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Risk State: CRITICAL                                     │
│ ├─ Utilization ≥ 95%                                     │
│ ├─ Margin Ratio ≥ 70%                                    │
│ └─ Unrealized Loss ≥ $100k                               │
│                                                          │
│ Actions:                                                 │
│ ❌ REFUSE new bankrupt positions → Trigger ADL           │
│ 🚨 Emergency ADL: Offload existing exposure at Mark      │
│ 🚨 Use taker orders, market orders if needed             │
│ 🚨 Maximum urgency                                       │
└─────────────────────────────────────────────────────────┘
```

### E. Emergency ADL Mechanism (Section 7.2)

When IF breaches critical limits, it can trigger **Emergency ADL**:

```
┌──────────────────────────────────────────────────────────┐
│ Insurance Fund State: CRITICAL                           │
│ ├─ Total Exposure: $1.2M (over $1M limit)               │
│ ├─ ADA-USD Position: Long 500k ADA @ $0.40              │
│ │   Notional: $225k (over $200k per-symbol limit)       │
│ └─ Decision: Trigger Emergency ADL                       │
└────────────────────┬─────────────────────────────────────┘
                     │
                     │ IF calls backend ADL API
                     ↓
┌──────────────────────────────────────────────────────────┐
│ ADL Engine (Backend)                                     │
│                                                          │
│ Parameters from IF:                                      │
│ ├─ Symbol: ADA-USD                                       │
│ ├─ Side: Long (IF wants to offload long)                │
│ ├─ Target Notional: $100,000                            │
│ │   (Offload enough to get back under $200k limit)      │
│ └─ Settlement Price: Current Mark Price                  │
│                                                          │
│ ADL Process:                                             │
│ 1. Select counterparties (short ADA-USD traders)        │
│    Sorted by: PnL/Margin ratio + Leverage               │
│    (Most profitable + highest leverage = first to ADL)   │
│                                                          │
│ 2. Force-close counterparty positions @ Mark Price       │
│    - Counterparties realize profit at Mark (not higher) │
│    - Total notional closed: $100,000                    │
│                                                          │
│ 3. Settle IF position                                    │
│    - IF closes $100k notional @ Mark Price              │
│    - IF realizes P&L                                     │
│    - IF exposure reduced                                 │
└──────────────────────────────────────────────────────────┘
```

---

## Hummingbot Implementation

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Strike v2 Backend                            │
│                                                                 │
│  ┌──────────────────┐         ┌────────────────────┐          │
│  │ Liquidation      │────────→│ IF Account         │          │
│  │ Engine           │ Transfer│ Type: "if"         │          │
│  │                  │ Bankrupt│ Balance: $100k     │          │
│  │ - Detects MR≥100%│ Position│ Positions: {...}   │          │
│  │ - Places IOC     │ @ Bank. │ Orders: [...]      │          │
│  │ - Transfers IF   │ Price   │                    │          │
│  └──────────────────┘         └─────────┬──────────┘          │
│                                          │                      │
│                                          │ REST API             │
│                                          │ WebSocket            │
└──────────────────────────────────────────┼──────────────────────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    │                      ↓                      │
                    │   GET /v2/positions?account_id=<if-uuid>   │
                    │   GET /v2/account?account_id=<if-uuid>     │
                    │   POST /v2/order (IF's orders)             │
                    │   WS: Position updates, fills              │
                    └──────────────────────┬──────────────────────┘
                                           │
                                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                      Hummingbot Bot                             │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ Strike Perpetual Connector                                │ │
│  │ - Account ID: <if-account-uuid>                           │ │
│  │ - API Key: <if-bot-key>                                   │ │
│  │ - Tracks positions, balance, orders                       │ │
│  └────────────────────────┬──────────────────────────────────┘ │
│                           │                                    │
│                           ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ Insurance Fund Unwinder Strategy (Script)                 │ │
│  │                                                            │ │
│  │ on_tick() every 1 second:                                 │ │
│  │                                                            │ │
│  │ 1. Get IF Positions                                       │ │
│  │    └─> connector.account_positions                        │ │
│  │                                                            │ │
│  │ 2. Calculate Risk Metrics                                 │ │
│  │    ├─> Total notional = Σ(|size| × mark_price)           │ │
│  │    ├─> Total UPnL = Σ((mark - entry) × size)             │ │
│  │    ├─> Utilization = notional / account_value × 100       │ │
│  │    └─> Margin Ratio (approx)                              │ │
│  │                                                            │ │
│  │ 3. Determine Mode                                         │ │
│  │    IF (margin_ratio ≥ 50% OR loss ≥ $50k OR util ≥ 80%): │ │
│  │       mode = AGGRESSIVE                                   │ │
│  │    ELSE:                                                  │ │
│  │       mode = MAKER                                        │ │
│  │                                                            │ │
│  │ 4. Create Unwinding Orders                                │ │
│  │    FOR each position:                                     │ │
│  │      IF mode == MAKER:                                    │ │
│  │        price = mark × (1 + spread_bps/10000)             │ │
│  │        size = position × 10%                              │ │
│  │      ELSE (AGGRESSIVE):                                   │ │
│  │        price = mark × (1 - slippage_bps/10000)           │ │
│  │        size = position × 25%                              │ │
│  │      place_order(price, size)                             │ │
│  │                                                            │ │
│  │ 5. Monitor & Log                                          │ │
│  │    └─> Every 5 minutes: Status report                     │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Key Implementation Details

#### 1. Position Entry Price = Bankruptcy Price

```python
# CRITICAL: For IF positions, entry_price is the Bankruptcy Price
# This is where the IF took over the position, NOT the original trader's entry

for position in if_positions:
    # position.entry_price = Bankruptcy Price at which IF received it
    # Example: $0.40 for ADA-USD

    bankruptcy_price = position.entry_price  # IF's cost basis

    # Goal: Exit above bankruptcy price to profit (or at least break-even)
    target_exit_price = bankruptcy_price * Decimal("1.01")  # +1% profit target
```

#### 2. Risk Calculation

```python
def calculate_risk_metrics(self, positions):
    total_notional = Decimal("0")
    total_upnl = Decimal("0")

    for position in positions:
        mark_price = get_mark_price(position.trading_pair)

        # Notional = |Size| × Mark Price
        notional = abs(position.amount) * mark_price
        total_notional += notional

        # UPnL = (Mark - Entry) × Size (with sign)
        upnl = (mark_price - position.entry_price) * position.amount
        total_upnl += upnl

    account_value = get_account_balance()

    # Utilization = Total Notional / Account Value × 100
    utilization_pct = (total_notional / account_value * Decimal("100"))

    return {
        'total_notional': total_notional,
        'total_upnl': total_upnl,
        'utilization_pct': utilization_pct,
        'account_value': account_value
    }
```

#### 3. Mode Selection

```python
def determine_mode(self, risk_metrics):
    # Aggressive mode triggers
    if risk_metrics['margin_ratio'] >= Decimal("50"):
        return AGGRESSIVE  # Approaching user liquidation threshold (100%)

    if risk_metrics['total_upnl'] <= Decimal("-50000"):
        return AGGRESSIVE  # Too much unrealized loss

    if risk_metrics['total_notional'] >= Decimal("1000000"):
        return AGGRESSIVE  # Exposure too large

    if risk_metrics['utilization_pct'] >= Decimal("80"):
        return AGGRESSIVE  # Capital tied up

    # Default to maker mode
    return MAKER
```

#### 4. Order Placement

```python
def create_unwinding_order(self, position, mode):
    mark_price = get_mark_price(position.trading_pair)

    # Determine side (opposite of position)
    if position.amount > 0:  # Long position
        side = SELL
    else:  # Short position
        side = BUY

    # Calculate price and size based on mode
    if mode == MAKER:
        # Maker: Try to profit
        if side == SELL:
            # Sell above mark
            price = mark_price * (1 + maker_spread_bps / 10000)
        else:
            # Buy below mark
            price = mark_price * (1 - maker_spread_bps / 10000)

        # Ensure price is at least as good as entry (Bankruptcy Price)
        min_acceptable = position.entry_price * (1 + min_profit_bps / 10000)
        if side == SELL:
            price = max(price, min_acceptable)
        else:
            price = min(price, min_acceptable)

        size = abs(position.amount) * Decimal("0.10")  # 10% of position
        order_type = LIMIT

    else:  # AGGRESSIVE
        # Aggressive: Accept slippage to exit fast
        if side == SELL:
            price = mark_price * (1 - aggressive_slippage_bps / 10000)
        else:
            price = mark_price * (1 + aggressive_slippage_bps / 10000)

        size = abs(position.amount) * Decimal("0.25")  # 25% of position
        order_type = LIMIT  # Still limit, but IOC-like behavior

    # Place order
    place_order(
        trading_pair=position.trading_pair,
        side=side,
        price=price,
        amount=size,
        order_type=order_type,
        position_action=CLOSE
    )
```

---

## Key Metrics & Monitoring

### Health Metrics

Monitor these metrics to assess IF health:

```
┌─────────────────────────────────────────────────────────┐
│ Insurance Fund Health Dashboard                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Capital Metrics:                                        │
│ ├─ Account Value:        $100,000                      │
│ ├─ Total Notional:       $450,000 (45% utilization) ✓  │
│ ├─ Available Capital:    $550,000                      │
│ └─ Cumulative Profit:    $12,450 (12.45% ROI) 💰       │
│                                                         │
│ Position Metrics:                                       │
│ ├─ Active Positions:     3                             │
│ ├─ Total UPnL:          +$3,200 (in profit) ✓          │
│ ├─ Largest Position:     ADA-USD ($180k notional)      │
│ └─ Margin Ratio:         35% (safe) ✓                  │
│                                                         │
│ Risk Status:                                            │
│ ├─ Mode:                 MAKER (gradual unwinding) ✓   │
│ ├─ Utilization:          45% / 80% max ✓               │
│ ├─ Loss Exposure:        N/A (in profit)               │
│ └─ ADL Risk:             LOW ✓                         │
│                                                         │
│ Performance (24h):                                      │
│ ├─ Positions Closed:     5                             │
│ ├─ Avg Profit/Close:     $89.50                        │
│ ├─ Total Fees Earned:    $1,250 (liquidation fees)     │
│ └─ Win Rate:             100% (all closes profitable)   │
└─────────────────────────────────────────────────────────┘
```

### Alert Thresholds

```yaml
Alerts:

  WARNING (Yellow):
    - Utilization ≥ 70%
    - Unrealized Loss ≥ $30,000
    - Margin Ratio ≥ 40%
    - Single position > $180k notional

  CRITICAL (Red):
    - Utilization ≥ 90%
    - Unrealized Loss ≥ $80,000
    - Margin Ratio ≥ 60%
    - Total notional > $900k

  EMERGENCY (Flashing Red):
    - Utilization ≥ 95% → REFUSE NEW POSITIONS
    - Unrealized Loss ≥ $100k → TRIGGER EMERGENCY ADL
    - Margin Ratio ≥ 80% → RISK OF IF LIQUIDATION
```

### Success Criteria

The IF is operating successfully when:

✅ **Capital Growth**: IF balance growing from fees and profits
✅ **Low ADL Rate**: < 5% of positions require ADL (95%+ unwound via market)
✅ **Positive PnL**: Average unwind realizes profit vs Bankruptcy Price entry
✅ **Fast Unwinding**: Average position held < 24 hours
✅ **Risk Compliance**: Never breach critical thresholds
✅ **Market Impact**: Minimal slippage, no orderbook disruption

---

## Reference

- **Liquidation Documentation**: `STRIKE_LIQUIDATION_INSURANCE_ADL.md`
- **Backend Enums**: `strike-v2-backend/pkg/models/enums.go`
- **Backend Account Model**: `strike-v2-backend/pkg/models/core.go`
- **Strategy Implementation**: `scripts/insurance_fund_unwinder.py`
