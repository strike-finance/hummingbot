# Strike: Liquidation, Insurance Fund & ADL

## 0. Glossary & Core Formulas

### **Mark Price (MP)**

A fair reference price derived from external exchanges' prices and internal order book. Liquidation and risk checks are performed against the Mark Price rather than the last traded price, consistent with industry practice to reduce unnecessary liquidations in volatile books.

### **Notional Value**

Total position exposure, defined as:

$
Notional_{Price} = Price \times |Size|
$

We use this **notional value** as the core risk metric for the system. It is:

- The driver of our **margin tiers** (we use notional-based tiers rather than simple size/quantity tiers), and
- The **foundation** for **Maintenance Margin** calculation across all tiers.

### **Unrealized PnL (UPnL)**

Unrealized profit and loss at a given price level:

$
UPnL_{Price} = (Price - Entry Price) \times Size
$

- For long positions: higher Price vs Entry Price ⇒ positive UPnL.
- For short positions: lower Price vs Entry Price ⇒ positive UPnL (Size carries the position sign).

UPnL evaluated at the Mark Price ($UPnL_{MP}$) is what feeds into the Margin Balance formulas used for risk checks and liquidation.

### **Margin Balance**

Represents the funds that are presently being used as collateral for open positions.

- Each **Isolated** position has its own margin balance.
- All **Cross** positions share a single margin balance.

Formally:

$
\overset{\text{Isolated}}{Margin Balance} = IsoMargin + {UPnL}_{MP}
\\
\overset{\text{Cross}}{Margin Balance} = Wallet Balance - \sum^{\text{Isolated}}IsoMargin + \sum^{\text{Cross}}{UPnL}_{MP}
$

### **Maintenance Margin (MM)**

Minimum amount of collateral required to keep a position open. Falling below Maintenance Margin (in Margin Ratio terms) triggers liquidation.

At a given Mark Price level:

$
{Maintenance Margin}_{Price} = {Notional}_{Price} \times {Maintenance Margin Rate} - {Maintenance Amount}
$

We use **notional-based margin tiers**: larger notionals move into higher tiers with higher MM rates and lower maximum effective leverage.

### **Margin Ratio (MR)**

Primary risk indicator for both isolated positions and the aggregated cross-margin balance.

$
{Margin Ratio}_{MP} = \frac{\sum{{Maintenance Margin}_{MP}}}{{Margin Balance}_{MP}}
$

- Liquidation **starts** when: `Margin Ratio ≥ 100%`
- Liquidation **stops** when: `Margin Ratio < 100%`

This matches the common "liquidation when maintenance margin ≥ margin balance" convention.

### **Bankruptcy Price**

Price at which the positions' losses equal the Isolated Margin for that position (for isolated) or the whole Wallet Balance (for cross). At the Bankruptcy Price, the trader's margin for that position is fully exhausted; any additional loss would be borne by the Insurance Fund or, in extreme cases, by ADL.

### **Liquidation Price**

The Mark Price at which a position enters liquidation. Between the Liquidation price and the Bankruptcy price, the system attempts to close or reduce the position to restore the Margin Ratio below 100%.

---

## 1. Margining Model

### 1.1 Isolated Margin

- Each position maintains its own **Isolated Margin Balance**.
- Liquidation is evaluated per-position using that balance and the position's Maintenance Margin requirement (based on its margin tier).
- Losses are capped at the isolated margin posted for that specific position; other balances are unaffected.

### 1.2 Cross Margin

- All cross-margin positions share one **Cross Margin Balance**.
- The Margin Ratio is account-level across all cross positions.
- Gains in profitable positions can offset losses in losing positions.
- Liquidation is performed in a **portfolio-aware** way (details in section 3.2):
    - Losing positions are liquidated first.
    - Winning positions are only liquidated as a last resort if necessary to restore solvency.

### 1.3 Notional-Based Margin Tiers

We apply **notional-based margin tiers** per symbol. Larger aggregate notional exposure migrates the position into higher tiers with:

- Higher Maintenance Margin Rates.
- Lower maximum effective leverage.

Notional-based tiers give strictly better risk control than a pure size/quantity model because they scale requirements with both **position size** and the **underlying price level**. This ensures that two positions with the same contract size but very different price levels do *not* receive the same margin treatment, and large notional exposures always migrate into higher maintenance tiers with more conservative parameters.

---

## 2. Liquidation Triggers

### 2.1 Core Trigger

For both Isolated and Cross margin:

- Liquidation is triggered when the Margin Ratio at Mark Price reaches or exceeds 100%.

Once in liquidation:

- The account (or isolated position) is flagged as being in **liquidation mode**.
- A specialized liquidation engine takes over:
    - Cancels specific open orders (see 3.1).
    - Applies partial and/or full liquidation logic by placing liquidation orders as Limit IOC at Bankruptcy Price.
    - Transfers any remaining Bankrupt Position to the Insurance Fund (or to ADL if Insurance Fund declines / is constrained).

The process runs until:

- Margin Ratio falls back below 100%,
- *or* the relevant position(s) are fully closed or taken over.

### 2.2 System Failure Condition

If, at Mark Price, the **Margin Balance ≤ 0** (i.e., price moves beyond the Bankruptcy Price such that losses exceed posted collateral) for an isolated position or overall cross margin:

- The position is declared a **Bankrupt Position** immediately.
- No liquidation order gets sent to the order book.
- It is taken over directly by the **Insurance Fund**, settled on the trader side at the position's Bankruptcy Price.
- Any additional loss (the difference between Mark Price and Bankruptcy Price) is entirely absorbed by the Insurance Fund.

This defines a hard boundary: client accounts do not go negative as a result of exchange-level liquidation logic; instead, the loss waterfall flows into the Insurance Fund and, in tail events, into ADL.

---

## 3. Liquidation Process

### 3.1 Pre-Liquidation Order Management

When an account or isolated position enters liquidation:

1. **Cancel open orders that increase exposure.**
    - For the symbol being liquidated, all open orders that would **increase** the position size are cancelled.
2. **Preserve risk-reducing orders.**
    - Reduce-only orders, stop-loss orders, and any order whose execution would strictly **reduce** or close the liquidated exposure are allowed to remain.
3. **Cross-margin scope:**
    - For cross margin, the above cancellation logic applies **across all symbols** under the same account, since the risk is shared at the account level.

This guarantees that while the engine is trying to stabilize the account, the trader cannot re-lever or unintentionally increase risk through resting orders.

### 3.2 Position Selection (Cross Margin)

In cross mode, because Margin Ratio is shared, multiple positions may need to be liquidated simultaneously:

- We first **identify losing positions** (negative UPnL at Mark Price).
- Liquidation attempts are applied to **losing positions only** until:
    - Margin Ratio falls below 100%, or
    - All losing positions are fully liquidated.

Only if Margin Ratio **remains ≥ 100%** after all losing positions have been exhausted will the system begin to:

- Systematically reduce profitable positions (starting from those with the largest risk contribution) to restore account solvency.

This ensures profitable positions are treated as a last-line buffer rather than the primary liquidation target.

### 3.3 Liquidation Orders: Limit IOC at Bankruptcy Price

All liquidation orders (partial or full liquidation) routed to the order book are placed as **Limit IOC (Immediate-or-Cancel)** orders, with: **Limit Price = Bankruptcy Price** of the position being liquidated.

Conceptually:

- The **Liquidation Price** acts as the trigger.
- The **Bankruptcy Price** acts as the worst-acceptable execution level.
- Any fills between these two prices:
    - Reduce or close the trader's position.
    - Realize PnL **to the trader's account**, affecting their Cross Margin Balance directly.
    - Do **not** involve the Insurance Fund; the Fund is untouched as long as the position can be closed in the market before hitting Bankruptcy Price.

Any residual size that cannot be filled at or better than Bankruptcy Price becomes a **Bankrupt Position** (see sections 5 and 6).

---

## 4. Partial Liquidation

When a position is **not** yet in the lowest notional tier, the engine prefers **partial liquidation** over full closure, to reduce systemic impact and unnecessary churn.

### 4.1 Objectives

- Reduce notional exposure enough to:
    - Step down to a lower margin tier, and
    - Restore Margin Ratio below 100% with a configurable safety buffer.
- Minimize trader impact by:
    - Avoiding full position closures when a smaller reduction suffices.
    - Reducing the frequency and magnitude of ADL.

### 4.2 Sizing

On each liquidation step, we compute a **target partial liquidation size** based on:

1. **Tier De-Escalation Requirement**
The minimum size reduction needed to migrate the position to a **lower notional tier**, plus a configurable buffer to avoid immediately bouncing back into a higher tier on small price moves.
2. **Notional Fraction Cut**
A configurable fraction of current notional (e.g., a minimum "position cut" for meaningful risk reduction).
3. **Margin Ratio Sensitivity**
The worse the Margin Ratio (further above 100%), the more aggressively the engine scales up the partial liquidation size within configured bounds.

Practically, at the moment Margin Ratio reaches 100%, the first partial liquidation step is designed to:

- Bring the position **at least** down to around **90%** of the prior tier's cap, and
- Cut **at least** around **25%** of the position notional.

Exact numerical values and scaling curves are configurable and subject to tuning; what remains constant is the behavior pattern: de-tier first, enforce a minimum meaningful cut, grow the cut as risk increases.

### 4.3 Fees

For each partial liquidation:

- The **Liquidation Fee** is charged only on the notional actually filled in that partial liquidation.
- 100% of liquidation fees are are deducted from the trader's account and credited to the Insurance Fund associated with that market.

---

## 5. Full Liquidation & Bankrupt Positions

If partial liquidations cannot restore Margin Ratio < 100%, or if the position is already in the **lowest notional tier**, the engine proceeds to **full liquidation**.

### 5.1 Execution

- A single liquidation IOC order is placed for the entire remaining position with Limit Price = Bankruptcy Price.
- Any portion filled through the book:
    - Closes that same notional amount of the trader's position.
    - Produces realized PnL that is applied to the trader.

### 5.2 Residual Bankrupt Portion

After IOC execution:

- If there is **no unfilled portion**, the position is fully closed in the market; the Insurance Fund is not involved.
- If there is an **unfilled portion**, that residual is declared as a **Bankrupt Position**:
    - The Insurance Fund takes over that Bankrupt Position at the Bankruptcy Price.
    - Trader's effective close price = Insurance Fund's entry price = Bankruptcy Price.
    - The trader's losses are capped at their initial margin (plus realized PnL from any filled liquidation orders); they do not incur additional debt.

If Mark Price has moved unfavorably beyond the Bankruptcy Price, that difference is an unrealized loss of the Insurance Fund.

If at any point Margin Balance ≤ 0 before this step, the entire position is treated as Bankrupt and transferred directly to the Insurance Fund at the Bankruptcy Price (system failure condition from section 2.2).

### 5.3. Fees

The **Liquidation Fee** for a full liquidation is charged on the **entire position notional**, deducted from the trader's account and credited to the Insurance Fund associated with that market.

Liquidation Fees compensate the Insurance Fund for providing protection and for taking residual tail risk from bankrupt portions.

---

## 6. Insurance Fund

The Insurance Fund is not just a static pool of capital; it is an actively managed trading system tasked with:

1. **Absorbing Bankrupt Positions**, and
2. **Unwinding them into the market** with minimal systemic impact.

### 6.1 Structure

- There can be:
    - **Dedicated Insurance Funds** per symbol, or
    - **Grouped Funds** shared by sets of markets.
- Grouping is configurable and typically based on **liquidity profiles** (e.g., high-liquidity markets in one group, lower-liquidity or long-tail markets in another), rather than strictly by correlation or "all contracts in a currency".
- At launch, we operate Market Making ****and ****Insurance Fund activities using a unified capital pool, with accounting separation for risk management and reporting. Over time, independent capital allocations can be introduced as AUM grows.

### 6.2 Capital Sources

Insurance Funds' capital is built from:

1. **Liquidation Fees**
All liquidation fees (partial and full) credited directly to the relevant Insurance Fund.
2. **Profits from Closing Bankrupt Positions**
Bankrupt positions are taken over at a **discounted effective level** (Bankruptcy Price). If the Fund is able to exit at more favorable prices via its trading logic, the difference is profit.

### 6.3 Unwinding Bankrupt Positions

Once the Insurance Fund has taken over a Bankrupt Position:

- **Default behavior**:
    - Place **maker limit orders** at prices that are:
        - Favorable relative to the Entry Price, current Mark Price and Order Book, and
        - Designed to minimize market impact.
    - If the market allows, this can realize positive PnL versus the entry level (most of the time), but that is a consequence, not the primary objective.
- **Aggressive exit path**:
    - When risk metrics or volatility indicate elevated danger, the Insurance Fund may use **taker/market orders** or more aggressive pricing to reduce exposure quickly.
    - The priority here is risk reduction and market stability, not edge capture.

### 6.4 Risk Limits and Tolerances

The Insurance Fund has predefined **risk tolerances**, including:

- Overall margin ratio and losses.
- Maximum exposure per symbol and direction.
- Maximum aggregate utilization as a percentage of total fund NAV.
- Limits on concentration across low-liquidity markets.
- Thresholds for triggering **ADL events** (section 7).

Once these thresholds are approached or breached, the Insurance Fund can:

- **Refuse** to accept new Bankrupt Positions - which in turn, trigger an ADL (section 7.1)
- **Call an emergency ADL** to reduce some of its existing exposure (section 7.2).

---

## 7. Auto-Deleveraging (ADL)

ADL is explicitly a last-resort mechanism, designed as the final safeguard in the loss waterfall and is only activated by the ****Insurance Funds under clearly defined conditions.

There are two distinct ADL entry points:

### 7.1 ADL When a Bankrupt Position Is Rejected

When a Bankrupt Position is produced by the liquidation engine, the default is to transfer that position to the Insurance Fund at Bankruptcy Price.

However, if the Insurance Fund's risk engine determines that taking on this position would breach its tolerances, it may **reject** the transfer.

In that event:

1. ADL is triggered for the Bankrupt Position's size.
2. The system selects **counterparty positions** on the opposite side according to a risk-based priority queue (e.g., combining PnL per margin and effective leverage).
3. ADL is executed:
    - Counterparty positions are force-reduced or closed against the Bankrupt Position.
    - These counterparties are settled at the Bankruptcy Price of the Bankrupt Position.
4. After ADL:
    - The Bankrupt Position is fully offset.
    - The Insurance Fund does **not** take on the rejected risk.
    - Profits of counterparties subject to ADL are partially realized at Bankruptcy Price instead of potentially higher prices further out, which is the usual ADL socialization effect.

This ensures the Insurance Funds never exceeds their predefined risk capacity while still enabling orderly resolution of extreme outlier positions.

### 7.2 Emergency ADL initiated by the Insurance Funds

Separately, the Insurance Fund may already be holding Bankrupt Positions (or aggregated exposure) and breach its internal risk limits.

In that case, the Fund can initiate an **emergency ADL** as follows:

1. The Fund specifies a **target notional size** (per symbol and side) to be offloaded.
    - This target corresponds to a specific subset of the Insurance Fund's current risk-bearing position in that market (its "target position" for ADL).
    - Crucially, only the **specified target portion** of the Insurance Fund's exposure is settled in this ADL event, not necessarily its entire holdings.
2. ADL is triggered for that requested size.
3. The system again selects counterparties on the opposite side via the risk-based priority queue (similar as 7.1).
4. Settlement mechanics:
    - The Insurance Fund's target position and the selected counterparty positions are settled at the current Mark Price.
    - Counterparty positions are deleveraged (partially or fully) at Mark Price, locking in their profits at that level.
    - The Insurance Fund realizes PnL on the portion of its exposure that has been offloaded and thereby returns to within its risk tolerance.

This mechanism converts a stressed Insurance Fund state into a controlled socialization of risk via targeted deleveraging of the most profitable/high-leverage counterparties, minimizing moral hazard while preserving system solvency.

---

## 8. Loss Waterfall Summary

Putting it all together, the loss waterfall for any position is:

1. **Trader's Margin & PnL**
    - Losses are first absorbed by the trader's own balance.
    - Liquidation orders (partial/full) executed via Limit IOC between Liquidation and Bankruptcy Price adjust the trader's balance only.
2. **Liquidation via Order Book (Trader Risk Zone)**
    - Partial liquidation steps attempt to de-tier and restore Margin Ratio < 100%.
    - Full liquidation clears the remaining position when partial is insufficient.
    - Liquidation Fees on filled notional are charged to the trader and credited to the Insurance Fund.
3. **Insurance Fund (Bankrupt Position Zone)**
    - Any unfilled residual at or beyond Bankruptcy Price becomes a **Bankrupt Position**.
    - The Insurance Fund takes over at Bankruptcy Price (unless it rejects due to limits).
    - The Fund then manages and unwinds that risk within its own constraints.
4. **ADL (Systemic Protection Zone)**
    - **Per-position ADL**: if the Insurance Fund rejects a Bankrupt Position, ADL is triggered on that Bankrupt Position size and counterparties are settled at Bankruptcy Price.
    - **Emergency Fund ADL**: if the Insurance Fund's risk and utilization exceeds tolerance, it selects a target portion of its own exposure and offloads it via ADL at Mark Price, deleveraging profitable counterparties.

This structure gives a clean, deterministic path from user-level risk, through market-based liquidation, into a capitalized Insurance Fund, and finally, only in true tail events, into a structured ADL regime that socializes residual risk across the most risk-seeking and profitable participants.
