from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState

EXCHANGE_NAME = "strike_perpetual"
BROKER_ID = "HBOT"
MAX_ORDER_ID_LEN = 64

DOMAIN = EXCHANGE_NAME

# Base URLs
PERPETUAL_BASE_URL = "http://localhost:8080"
PERPETUAL_WS_URL = "ws://localhost:8081/ws"

FUNDING_RATE_UPDATE_INTERNAL_SECOND = 60

CURRENCY = "USDT"

# REST API Endpoints
PING_URL = "/healthz"
EXCHANGE_INFO_URL = "/admin/market"

# Account endpoints
ACCOUNT_INFO_URL = "/v2/account"

# Order endpoints
CREATE_ORDER_URL = "/v2/order"
CANCEL_ORDER_URL = "/v2/order/cancel"
ORDER_STATUS_URL = "/v2/order"
OPEN_ORDERS_URL = "/v2/openOrders"

# Position endpoints
POSITION_INFORMATION_URL = "/v2/positions"

# Asset endpoints
DEPOSIT_URL = "/v2/deposit"
WITHDRAW_URL = "/v2/withdraw"

# WebSocket channels
TRADES_ENDPOINT_NAME = "trades"
DEPTH_ENDPOINT_NAME = "orderbook"
USER_ORDERS_ENDPOINT_NAME = "orders"
USER_POSITIONS_ENDPOINT_NAME = "positions"
USER_BALANCE_ENDPOINT_NAME = "balance"

# Order Types (from Strike API)
ORDER_TYPE_MARKET = 1
ORDER_TYPE_LIMIT = 2
ORDER_TYPE_STOP = 3
ORDER_TYPE_STOP_LIMIT = 4
ORDER_TYPE_TAKE_PROFIT = 5
ORDER_TYPE_TAKE_PROFIT_LIMIT = 6

# Order Sides (from Strike API)
ORDER_SIDE_BUY = 1
ORDER_SIDE_SELL = 2

# Order Status (from Strike API documentation)
ORDER_STATUS_NONE = 0
ORDER_STATUS_PENDING = 1
ORDER_STATUS_OPEN = 2
ORDER_STATUS_FILLED = 3
ORDER_STATUS_CANCELED = 4
ORDER_STATUS_UNTRIGGERED = 5
ORDER_STATUS_REJECTED = 6
ORDER_STATUS_EXPIRED = 7

# Order State Mapping
ORDER_STATE = {
    0: OrderState.PENDING_CREATE,      # NONE
    1: OrderState.PENDING_CREATE,      # PENDING
    2: OrderState.OPEN,                # OPEN (active on orderbook)
    3: OrderState.FILLED,              # FILLED
    4: OrderState.CANCELED,            # CANCELED
    5: OrderState.OPEN,                # UNTRIGGERED (conditional orders)
    6: OrderState.FAILED,              # REJECTED
    7: OrderState.CANCELED,            # EXPIRED
}

# Time in Force
TIME_IN_FORCE_GTC = 1
TIME_IN_FORCE_IOC = 2
TIME_IN_FORCE_FOK = 3

# Margin Modes
MARGIN_MODE_CROSS = 1
MARGIN_MODE_ISOLATED = 2

HEARTBEAT_TIME_INTERVAL = 30.0

# Rate Limits
MAX_REQUEST = 1200
ALL_ENDPOINTS_LIMIT = "All"

RATE_LIMITS = [
    RateLimit(ALL_ENDPOINTS_LIMIT, limit=MAX_REQUEST, time_interval=60),

    # Public endpoints
    RateLimit(limit_id=PING_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=EXCHANGE_INFO_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),

    # Account endpoints
    RateLimit(limit_id=ACCOUNT_INFO_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),

    # Order endpoints
    RateLimit(limit_id=CREATE_ORDER_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=CANCEL_ORDER_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=ORDER_STATUS_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=OPEN_ORDERS_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),

    # Position endpoints
    RateLimit(limit_id=POSITION_INFORMATION_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),

    # Asset endpoints
    RateLimit(limit_id=DEPOSIT_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=WITHDRAW_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
]

# Error messages
ORDER_NOT_EXIST_MESSAGE = "order not found"
UNKNOWN_ORDER_MESSAGE = "unknown order"
