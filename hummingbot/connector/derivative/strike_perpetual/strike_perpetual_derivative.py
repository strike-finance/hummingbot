import asyncio
import os
import time
from decimal import Decimal
from typing import Any, AsyncIterable, Dict, List, Optional, Tuple

import yaml
from bidict import bidict

from hummingbot.connector.client_order_tracker import ClientOrderTracker
from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.derivative.position import Position
from hummingbot.connector.derivative.strike_perpetual import (
    strike_perpetual_constants as CONSTANTS,
    strike_perpetual_web_utils as web_utils,
)
from hummingbot.connector.derivative.strike_perpetual.strike_perpetual_api_order_book_data_source import (
    StrikePerpetualAPIOrderBookDataSource,
)
from hummingbot.connector.derivative.strike_perpetual.strike_perpetual_api_user_stream_data_source import (
    StrikePerpetualUserStreamDataSource,
)
from hummingbot.connector.derivative.strike_perpetual.strike_perpetual_auth import StrikePerpetualAuth
from hummingbot.connector.perpetual_derivative_py_base import PerpetualDerivativePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import get_new_client_order_id
from hummingbot.core.api_throttler.data_types import RateLimit
from hummingbot.core.data_type.common import OrderType, PositionAction, PositionMode, PositionSide, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.utils.async_utils import safe_ensure_future, safe_gather
from hummingbot.core.utils.estimate_fee import build_trade_fee
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

bpm_logger = None


class StrikePerpetualDerivative(PerpetualDerivativePyBase):
    """Strike Perpetual Exchange connector for Hummingbot."""

    web_utils = web_utils

    SHORT_POLL_INTERVAL = 5.0
    LONG_POLL_INTERVAL = 12.0

    def __init__(
        self,
        balance_asset_limit: Optional[Dict[str, Dict[str, Decimal]]] = None,
        rate_limits_share_pct: Decimal = Decimal("100"),
        strike_perpetual_account_id: str = None,
        strike_perpetual_api_key: str = None,
        strike_perpetual_base_url: str = CONSTANTS.PERPETUAL_BASE_URL,
        strike_perpetual_ws_url: str = CONSTANTS.PERPETUAL_WS_URL,
        strike_perpetual_price_url: str = CONSTANTS.PERPETUAL_PRICE_URL,
        trading_pairs: Optional[List[str]] = None,
        trading_required: bool = True,
        domain: str = CONSTANTS.DOMAIN,
    ):
        """
        Initialize the Strike Perpetual connector.

        :param balance_asset_limit: Optional balance limits per asset
        :param rate_limits_share_pct: Percentage of rate limits to use
        :param strike_perpetual_account_id: Strike account ID
        :param strike_perpetual_api_key: Strike API key for bot authentication
        :param strike_perpetual_base_url: Base URL for Strike Trading API (default: http://localhost:8080)
        :param strike_perpetual_ws_url: WebSocket URL for Strike UserStream (default: ws://localhost:8083/ws)
        :param strike_perpetual_price_url: Base URL for Strike Price Service (default: http://localhost:8082)
        :param trading_pairs: List of trading pairs to track
        :param trading_required: Whether trading is required
        :param domain: The exchange domain
        """
        self.strike_perpetual_account_id = strike_perpetual_account_id
        self.strike_perpetual_api_key = strike_perpetual_api_key
        self.strike_perpetual_base_url = strike_perpetual_base_url
        self.strike_perpetual_ws_url = strike_perpetual_ws_url
        self.strike_perpetual_price_url = strike_perpetual_price_url
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs
        self._domain = domain
        self._position_mode = None
        self._last_trade_history_timestamp = None

        # Update constants with user-provided URLs
        CONSTANTS.PERPETUAL_BASE_URL = strike_perpetual_base_url
        CONSTANTS.PERPETUAL_WS_URL = strike_perpetual_ws_url
        CONSTANTS.PERPETUAL_PRICE_URL = strike_perpetual_price_url

        super().__init__(balance_asset_limit, rate_limits_share_pct)

    @property
    def name(self) -> str:
        """Returns the connector name."""
        return self._domain

    @property
    def authenticator(self) -> Optional[StrikePerpetualAuth]:
        """Returns the authenticator instance."""
        # Always return authenticator if account_id is provided
        # We need authentication even for read-only operations like balance checks
        if self.strike_perpetual_account_id:
            return StrikePerpetualAuth(
                account_id=self.strike_perpetual_account_id,
                api_key=self.strike_perpetual_api_key
            )
        return None

    @property
    def rate_limits_rules(self) -> List[RateLimit]:
        """Returns the rate limit rules."""
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self) -> str:
        """Returns the exchange domain."""
        return self._domain

    @property
    def client_order_id_max_length(self) -> int:
        """Returns the maximum length for client order IDs."""
        return CONSTANTS.MAX_ORDER_ID_LEN

    @property
    def client_order_id_prefix(self) -> str:
        """Returns the client order ID prefix."""
        return CONSTANTS.BROKER_ID

    @property
    def trading_rules_request_path(self) -> str:
        """Returns the trading rules request path."""
        return CONSTANTS.EXCHANGE_INFO_URL

    @property
    def trading_pairs_request_path(self) -> str:
        """Returns the trading pairs request path."""
        return CONSTANTS.EXCHANGE_INFO_URL

    @property
    def check_network_request_path(self) -> str:
        """Returns the network check request path."""
        return CONSTANTS.PING_URL

    @property
    def trading_pairs(self):
        """Returns the trading pairs."""
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        """Returns whether cancel requests are synchronous."""
        return True

    @property
    def is_trading_required(self) -> bool:
        """Returns whether trading is required."""
        return self._trading_required

    @property
    def funding_fee_poll_interval(self) -> int:
        """Returns the funding fee polling interval in seconds."""
        return 120

    async def _make_network_check_request(self):
        """Makes a network check request to verify connectivity."""
        await self._api_get(path_url=self.check_network_request_path)

    def supported_order_types(self) -> List[OrderType]:
        """Returns a list of supported order types."""
        return [OrderType.LIMIT, OrderType.MARKET]

    def supported_position_modes(self):
        """Returns supported position modes."""
        return [PositionMode.ONEWAY]

    def get_buy_collateral_token(self, trading_pair: str) -> str:
        """Returns the collateral token for buy orders."""
        trading_rule: TradingRule = self._trading_rules[trading_pair]
        return trading_rule.buy_order_collateral_token

    def get_sell_collateral_token(self, trading_pair: str) -> str:
        """Returns the collateral token for sell orders."""
        trading_rule: TradingRule = self._trading_rules[trading_pair]
        return trading_rule.sell_order_collateral_token

    def get_price(self, trading_pair: str, is_buy: bool) -> Decimal:
        """
        Override get_price to handle USD/USDT equivalence.
        Strike uses USDT as collateral but trading pairs use USD as quote.
        """
        # Handle USD-USDT conversion
        # For now, treat as 1:1 but this could be enhanced to fetch real USDT/USD rate
        # from an external source (e.g., Binance, CoinGecko) for more accuracy
        if trading_pair in ["USD-USDT", "USDT-USD"]:
            # TODO: For pmm_dynamic, consider fetching real-time USDT/USD rate
            # from a reference exchange like Binance or using an oracle
            return self._get_usdt_usd_reference_price()

        # Convert USDT-based pairs to USD-based pairs (e.g., ADA-USDT -> ADA-USD)
        # since Strike trading pairs use USD but collateral is USDT
        if "-USDT" in trading_pair:
            converted_pair = trading_pair.replace("-USDT", "-USD")
            # Check if the USD version exists
            if converted_pair in self.order_book_tracker.order_books:
                return super().get_price(converted_pair, is_buy)

        # Similarly handle USDT-XXX -> USD-XXX
        if "USDT-" in trading_pair:
            converted_pair = trading_pair.replace("USDT-", "USD-")
            if converted_pair in self.order_book_tracker.order_books:
                # For inverse pairs, we need to invert the price
                price = super().get_price(converted_pair, not is_buy)
                return Decimal("1") / price if price > 0 else Decimal("0")

        # For all other pairs, use the parent implementation
        return super().get_price(trading_pair, is_buy)

    def _get_usdt_usd_reference_price(self) -> Decimal:
        """
        Get the USDT/USD reference price for accurate collateral calculations.

        Fetches real-time USDT/USD rate from Binance with caching to avoid
        excessive API calls. This is especially important for PMM strategies
        where precise collateral valuations affect order sizing.

        :return: USDT/USD conversion rate
        """
        import time

        # Cache the reference price for 60 seconds
        cache_duration = 60  # seconds
        current_time = time.time()

        # Check cache
        if hasattr(self, '_usdt_usd_cache'):
            cached_price, cached_time = self._usdt_usd_cache
            if current_time - cached_time < cache_duration:
                return cached_price

        # Try to fetch from Binance
        try:
            import asyncio

            import aiohttp

            async def fetch_binance_price():
                try:
                    async with aiohttp.ClientSession() as session:
                        # Binance doesn't have direct USDT/USD, use USDT/USDC as proxy
                        # USDC is typically pegged 1:1 to USD
                        url = "https://api.binance.com/api/v3/ticker/price?symbol=USDCUSDT"
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as response:
                            if response.status == 200:
                                data = await response.json()
                                price = Decimal(data['price'])
                                # Invert since we got USDC/USDT but want USDT/USD
                                # If USDC = 0.9995 USDT, then USDT = 1/0.9995 = 1.0005 USD
                                return Decimal("1") / price if price > 0 else Decimal("1.0")
                except Exception:
                    pass
                return Decimal("1.0")

            # Run async fetch
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in async context, return default
                reference_price = Decimal("1.0")
            else:
                reference_price = loop.run_until_complete(fetch_binance_price())

            # Cache the result
            self._usdt_usd_cache = (reference_price, current_time)
            return reference_price

        except Exception as e:
            self.logger().debug(f"Failed to fetch USDT/USD reference price: {e}")
            # Fallback to 1:1 assumption
            fallback = Decimal("1.0")
            self._usdt_usd_cache = (fallback, current_time)
            return fallback

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception):
        """Checks if exception is related to time synchronization."""
        return False

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        """Creates the web assistants factory."""
        return web_utils.build_api_factory(
            throttler=self._throttler,
            auth=self._auth
        )

    async def _make_trading_rules_request(self) -> Any:
        """Makes a request to fetch trading rules."""
        # Strike doesn't have a dedicated trading rules endpoint yet
        # This is a placeholder - should be updated when Strike implements this
        return []

    async def _make_trading_pairs_request(self) -> Any:
        """Makes a request to fetch trading pairs."""
        # Placeholder - Strike should provide a markets endpoint
        return []

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        """Checks if order not found error occurred during status update."""
        return CONSTANTS.ORDER_NOT_EXIST_MESSAGE in str(status_update_exception)

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        """Checks if order not found error occurred during cancelation."""
        return CONSTANTS.UNKNOWN_ORDER_MESSAGE in str(cancelation_exception)

    def quantize_order_price(self, trading_pair: str, price: Decimal) -> Decimal:
        """Quantizes order price according to trading rules."""
        trading_rule = self._trading_rules.get(trading_pair)
        if trading_rule:
            return price.quantize(trading_rule.min_price_increment)
        return price

    async def _update_trading_rules(self):
        """Updates trading rules from the exchange."""
        # Create default trading rules for configured pairs
        trading_rules_list = await self._format_trading_rules({})
        self._trading_rules.clear()
        for trading_rule in trading_rules_list:
            self._trading_rules[trading_rule.trading_pair] = trading_rule

    async def _initialize_trading_pair_symbol_map(self):
        """Initializes the trading pair symbol map."""
        try:
            # Placeholder - Strike should provide a symbols endpoint
            mapping = bidict()
            for trading_pair in self._trading_pairs:
                # Strike uses symbols with hyphens (e.g., ADA-USDT)
                exchange_symbol = trading_pair  # Keep the hyphen
                mapping[exchange_symbol] = trading_pair
            self._set_trading_pair_symbol_map(mapping)
        except Exception:
            self.logger().exception("There was an error requesting exchange info.")

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        """Creates the order book data source."""
        return StrikePerpetualAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        """Creates the user stream data source."""
        return StrikePerpetualUserStreamDataSource(
            auth=self._auth,
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    def _create_order_tracker(self) -> ClientOrderTracker:
        """
        Creates the order tracker with aggressive lost order handling.

        For perpetual markets, orders can be filled/cancelled very quickly,
        so we use a lower threshold (1) to mark orders as lost sooner.
        This prevents stale "order not found" warnings for orders that
        were already filled or cancelled on the exchange.
        """
        return ClientOrderTracker(connector=self, lost_order_count_limit=1)

    async def _status_polling_loop_fetch_updates(self):
        """Fetches updates in the status polling loop."""
        await safe_gather(
            self._update_order_status(),
            self._update_balances(),
            self._update_positions(),
        )

    async def _update_order_status(self):
        """Updates order status."""
        await self._update_orders()

    async def _update_lost_orders_status(self):
        """Updates lost orders status."""
        await self._update_lost_orders()

    def _get_fee(
        self,
        base_currency: str,
        quote_currency: str,
        order_type: OrderType,
        order_side: TradeType,
        position_action: PositionAction,
        amount: Decimal,
        price: Decimal = s_decimal_NaN,
        is_maker: Optional[bool] = None
    ) -> TradeFeeBase:
        """Calculates trading fees."""
        is_maker = is_maker or False
        fee = build_trade_fee(
            self.name,
            is_maker,
            base_currency=base_currency,
            quote_currency=quote_currency,
            order_type=order_type,
            order_side=order_side,
            amount=amount,
            price=price,
        )
        return fee

    async def _update_trading_fees(self):
        """Updates fees information from the exchange."""
        pass

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        """Places a cancel order request using Strike's order ID."""
        # Get Strike's order_id (exchange order ID)
        try:
            exchange_order_id = tracked_order.exchange_order_id or await tracked_order.get_exchange_order_id()
        except asyncio.TimeoutError:
            # If we don't have the exchange order ID yet, we can't cancel
            raise IOError("Cannot cancel order: exchange order ID not available yet")

        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=tracked_order.trading_pair)

        # Strike's cancel endpoint requires order_id (uint64) and symbol only
        api_params = {
            "order_id": int(exchange_order_id),  # Convert to int for Strike's uint64 field
            "symbol": symbol,
        }

        try:
            cancel_result = await self._api_delete(
                path_url=CONSTANTS.CANCEL_ORDER_URL,
                data=api_params,
                is_auth_required=True
            )
        except IOError as e:
            # Strike API returns HTTP 404 when order not found
            error_msg = str(e)
            if "404" in error_msg or CONSTANTS.ORDER_NOT_EXIST_MESSAGE in error_msg.lower() or CONSTANTS.UNKNOWN_ORDER_MESSAGE in error_msg.lower():
                self.logger().debug(f"The order {order_id} does not exist on Strike. No cancelation needed.")
                await self._order_tracker.process_order_not_found(order_id)
                # Re-raise with a message that matches our error detection pattern
                raise IOError(CONSTANTS.UNKNOWN_ORDER_MESSAGE)
            # For other HTTP errors, re-raise as-is
            raise

        # Check for errors in the response (for 200 OK responses with error field)
        if cancel_result.get("error"):
            self.logger().debug(f"The order {order_id} does not exist on Strike. No cancelation needed.")
            await self._order_tracker.process_order_not_found(order_id)
            raise IOError(f'Error canceling order: {cancel_result.get("error")}')

        return True

    def buy(
        self,
        trading_pair: str,
        amount: Decimal,
        order_type=OrderType.LIMIT,
        price: Decimal = s_decimal_NaN,
        **kwargs
    ) -> str:
        """Creates a buy order."""
        order_id = get_new_client_order_id(
            is_buy=True,
            trading_pair=trading_pair,
            hbot_order_id_prefix=self.client_order_id_prefix,
            max_id_len=self.client_order_id_max_length
        )

        if order_type is OrderType.MARKET:
            reference_price = self.get_mid_price(trading_pair) if price.is_nan() else price
            price = reference_price  # Strike handles slippage internally for market orders

        safe_ensure_future(self._create_order(
            trade_type=TradeType.BUY,
            order_id=order_id,
            trading_pair=trading_pair,
            amount=amount,
            order_type=order_type,
            price=price,
            **kwargs
        ))
        return order_id

    def sell(
        self,
        trading_pair: str,
        amount: Decimal,
        order_type: OrderType = OrderType.LIMIT,
        price: Decimal = s_decimal_NaN,
        **kwargs
    ) -> str:
        """Creates a sell order."""
        order_id = get_new_client_order_id(
            is_buy=False,
            trading_pair=trading_pair,
            hbot_order_id_prefix=self.client_order_id_prefix,
            max_id_len=self.client_order_id_max_length
        )

        if order_type is OrderType.MARKET:
            reference_price = self.get_mid_price(trading_pair) if price.is_nan() else price
            price = reference_price  # Strike handles slippage internally for market orders

        safe_ensure_future(self._create_order(
            trade_type=TradeType.SELL,
            order_id=order_id,
            trading_pair=trading_pair,
            amount=amount,
            order_type=order_type,
            price=price,
            **kwargs
        ))
        return order_id

    async def _place_order(
        self,
        order_id: str,
        trading_pair: str,
        amount: Decimal,
        trade_type: TradeType,
        order_type: OrderType,
        price: Decimal,
        position_action: PositionAction = PositionAction.NIL,
        **kwargs,
    ) -> Tuple[str, float]:
        """Places an order on Strike."""
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)

        # Map Hummingbot order type to Strike order type
        strike_order_type = CONSTANTS.ORDER_TYPE_LIMIT if order_type == OrderType.LIMIT else CONSTANTS.ORDER_TYPE_MARKET

        api_params = {
            "account_id": self.strike_perpetual_account_id,
            "client_order_id": order_id,
            "symbol": symbol,
            "side": CONSTANTS.ORDER_SIDE_BUY if trade_type == TradeType.BUY else CONSTANTS.ORDER_SIDE_SELL,
            "type": strike_order_type,
            "size": str(amount),
            "reduce_only": position_action == PositionAction.CLOSE,
        }

        if order_type == OrderType.LIMIT:
            api_params["price"] = str(price)

        try:
            order_result = await self._api_post(
                path_url=CONSTANTS.CREATE_ORDER_URL,
                data=api_params,
                is_auth_required=True
            )
        except IOError as e:
            # Strike API may return HTTP errors for invalid orders
            # Let the exception propagate with the original error message
            raise IOError(f"Error submitting order {order_id}: {str(e)}")

        # Check for errors in the response (for 200 OK responses with error field)
        if order_result.get("error"):
            raise IOError(f"Error submitting order {order_id}: {order_result.get('error')}")

        exchange_order_id = str(order_result.get("order_id"))
        return (exchange_order_id, self.current_timestamp)

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        """Requests order status from Strike using Strike's order ID."""
        try:
            exchange_order_id = tracked_order.exchange_order_id or await tracked_order.get_exchange_order_id()
        except asyncio.TimeoutError:
            exchange_order_id = None

        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=tracked_order.trading_pair)

        params = {
            "account_id": self.strike_perpetual_account_id,
            "symbol": symbol,
        }

        # Always prefer Strike's order_id over client_order_id for queries
        if exchange_order_id:
            # Convert to int for Strike's uint64 field
            params["order_id"] = int(exchange_order_id)
        else:
            # Fallback to client_order_id only if exchange_order_id not yet available
            params["client_order_id"] = tracked_order.client_order_id

        try:
            order_update = await self._api_get(
                path_url=CONSTANTS.ORDER_STATUS_URL,
                params=params,
                is_auth_required=True
            )
        except IOError as e:
            # Strike API returns HTTP 404 with JSON error body when order not found
            # The web assistant converts this to an IOError before we can parse the JSON
            error_msg = str(e)
            if "404" in error_msg or CONSTANTS.ORDER_NOT_EXIST_MESSAGE in error_msg.lower():
                # Re-raise with a message that matches our error detection pattern
                raise IOError(CONSTANTS.ORDER_NOT_EXIST_MESSAGE)
            # For other HTTP errors, re-raise as-is
            raise

        # Check for errors in the response (for 200 OK responses with error field)
        if order_update.get("error"):
            error_msg = order_update.get("error")
            self.logger().debug(f"Error fetching order {tracked_order.client_order_id}: {error_msg}")
            raise IOError(f"Error fetching order status: {error_msg}")

        # Map Strike order status to Hummingbot OrderState
        strike_status = order_update.get("Status", 0)
        order_state = CONSTANTS.ORDER_STATE.get(strike_status)
        if order_state is None:
            self.logger().warning(f"Unknown order status {strike_status} for order {tracked_order.client_order_id}, defaulting to OPEN")
            order_state = OrderState.OPEN

        _order_update: OrderUpdate = OrderUpdate(
            trading_pair=tracked_order.trading_pair,
            update_timestamp=order_update.get("CreateTimestamp", time.time()) / 1000,
            new_state=order_state,
            client_order_id=order_update.get("ClientOrderID", tracked_order.client_order_id),
            exchange_order_id=str(order_update.get("ID", exchange_order_id)),
        )
        return _order_update

    async def _iter_user_event_queue(self) -> AsyncIterable[Dict[str, any]]:
        """Iterates over user event queue."""
        while True:
            try:
                yield await self._user_stream_tracker.user_stream.get()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network(
                    "Unknown error. Retrying after 1 seconds.",
                    exc_info=True,
                    app_warning_msg="Could not fetch user events from Strike. Check account ID and network connection.",
                )
                await self._sleep(1.0)

    async def _user_stream_event_listener(self):
        """Listens to user stream events."""
        user_channels = [
            CONSTANTS.USER_ORDERS_ENDPOINT_NAME,
            CONSTANTS.USER_POSITIONS_ENDPOINT_NAME,
            CONSTANTS.USER_BALANCE_ENDPOINT_NAME,
        ]

        async for event_message in self._iter_user_event_queue():
            try:
                if isinstance(event_message, dict):
                    channel: str = event_message.get("channel", None)
                    data = event_message.get("data", None)
                elif event_message is asyncio.CancelledError:
                    raise asyncio.CancelledError
                else:
                    raise Exception(event_message)

                if channel not in user_channels:
                    self.logger().error(f"Unexpected message in user stream: {event_message}.", exc_info=True)
                    continue

                if channel == CONSTANTS.USER_ORDERS_ENDPOINT_NAME:
                    self._process_order_message(data)
                elif channel == CONSTANTS.USER_POSITIONS_ENDPOINT_NAME:
                    await self._process_position_message(data)
                elif channel == CONSTANTS.USER_BALANCE_ENDPOINT_NAME:
                    await self._process_balance_message(data)

            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error("Unexpected error in user stream listener loop.", exc_info=True)
                await self._sleep(5.0)

    def _process_order_message(self, order_msg: Dict[str, Any]):
        """Processes order update messages."""
        client_order_id = str(order_msg.get("ClientOrderID", ""))
        tracked_order = self._order_tracker.all_updatable_orders.get(client_order_id)

        if not tracked_order:
            self.logger().debug(f"Ignoring order message with id {client_order_id}: not in in_flight_orders.")
            return

        current_state = order_msg.get("Status", 0)
        tracked_order.update_exchange_order_id(str(order_msg.get("ID")))

        # Map Strike order status to Hummingbot OrderState
        order_state = CONSTANTS.ORDER_STATE.get(current_state)
        if order_state is None:
            self.logger().warning(f"Unknown order status {current_state} for order {client_order_id}, defaulting to OPEN")
            order_state = OrderState.OPEN

        order_update: OrderUpdate = OrderUpdate(
            trading_pair=tracked_order.trading_pair,
            update_timestamp=order_msg.get("UpdateTimestamp", time.time()) / 1000,
            new_state=order_state,
            client_order_id=client_order_id,
            exchange_order_id=str(order_msg.get("ID")),
        )
        self._order_tracker.process_order_update(order_update=order_update)

    async def _process_position_message(self, position_msg: Dict[str, Any]):
        """Processes position update messages."""
        # Update positions based on WebSocket messages
        await self._update_positions()

    async def _process_balance_message(self, balance_msg: Dict[str, Any]):
        """Processes balance update messages."""
        # Update balances based on WebSocket messages
        await self._update_balances()

    def _load_trading_rules_config(self) -> dict:
        """Load trading rules from config file."""
        config_paths = [
            os.path.join(os.path.dirname(__file__), "../../../../conf/strike/trading_rules.yml"),
            "/home/hummingbot/conf/strike_trading_rules.yml",
            "/home/hummingbot/conf/strike/trading_rules.yml",
            "conf/strike/trading_rules.yml",
        ]

        for config_path in config_paths:
            try:
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        return yaml.safe_load(f)
            except Exception:
                continue

        # Return empty dict if no config found (will use defaults)
        return {}

    async def _format_trading_rules(self, exchange_info_dict: Any) -> List[TradingRule]:
        """Formats trading rules from exchange info or config file."""
        return_val: list = []

        # Load config from YAML file
        config = self._load_trading_rules_config()
        trading_rules_config = config.get("trading_rules", {})
        default_config = config.get("default", {
            "price_decimals": 4,
            "amount_decimals": 6,
            "min_order_size": 0.001
        })

        # Create trading rules for configured pairs
        for trading_pair in self._trading_pairs:
            pair_config = trading_rules_config.get(trading_pair, default_config)

            # Convert decimals to increment (e.g., 2 decimals -> 0.01)
            price_decimals = pair_config.get("price_decimals", default_config["price_decimals"])
            amount_decimals = pair_config.get("amount_decimals", default_config["amount_decimals"])
            min_order_size = pair_config.get("min_order_size", default_config["min_order_size"])

            price_increment = Decimal(10) ** -price_decimals
            amount_increment = Decimal(10) ** -amount_decimals

            return_val.append(
                TradingRule(
                    trading_pair,
                    min_base_amount_increment=amount_increment,
                    min_price_increment=price_increment,
                    min_order_size=Decimal(str(min_order_size)),
                    buy_order_collateral_token=CONSTANTS.CURRENCY,
                    sell_order_collateral_token=CONSTANTS.CURRENCY,
                )
            )

        return return_val

    async def _get_last_traded_price(self, trading_pair: str) -> float:
        """Gets the last traded price for a trading pair."""
        # Placeholder - Strike should provide ticker endpoint
        return 0.0

    async def _update_balances(self):
        """Updates account balances."""
        params = {"account_id": self.strike_perpetual_account_id}

        try:
            account_info = await self._api_get(
                path_url=CONSTANTS.ACCOUNT_INFO_URL,
                params=params,
                is_auth_required=True
            )
        except IOError as e:
            # Strike API returns HTTP 404 when account not found
            error_msg = str(e)
            if "404" in error_msg or "user not found" in error_msg.lower():
                self.logger().warning(
                    f"Account {self.strike_perpetual_account_id} not found on Strike. "
                    f"Please verify the account ID is correct."
                )
            # Re-raise so base class can handle it with standard error logging
            raise

        # Strike uses USDT as collateral, but trading pairs use USD as quote
        # Store balances under "USD" to match trading pair quote currency
        # This ensures PMM strategy can find the balance correctly
        quote = "USD"  # Changed from CONSTANTS.CURRENCY ("USDT") to match trading pairs

        # Update balances from Strike API response
        # The /v2/account endpoint now includes balance data
        wallet_balance = Decimal(str(account_info.get("wallet_balance", "0")))
        available_balance = Decimal(str(account_info.get("available_balance", "0")))

        # Store under "USD" key to match trading pair quote currency
        self._account_balances[quote] = wallet_balance
        self._account_available_balances[quote] = available_balance

        # Also store under "USDT" for compatibility (actual collateral currency)
        self._account_balances[CONSTANTS.CURRENCY] = wallet_balance
        self._account_available_balances[CONSTANTS.CURRENCY] = available_balance

    async def _update_positions(self):
        """Updates account positions."""
        params = {
            "account_id": self.strike_perpetual_account_id,
        }

        positions_response = await self._api_get(
            path_url=CONSTANTS.POSITION_INFORMATION_URL,
            params=params,
            is_auth_required=True
        )

        positions = positions_response.get("positions", [])

        for position_data in positions:
            # API returns lowercase field names
            symbol = position_data.get("symbol", "")

            # Skip positions with empty symbols
            if not symbol:
                self.logger().debug(f"Skipping position with empty symbol: {position_data}")
                continue

            # Skip positions for symbols not being traded by this bot
            try:
                trading_pair = await self.trading_pair_associated_to_exchange_symbol(symbol)
            except KeyError:
                self.logger().debug(f"Skipping position for {symbol} - not in trading pairs list")
                continue

            size = Decimal(str(position_data.get("Size", "0")))
            if size == 0:
                continue

            position_side = PositionSide.LONG if size > 0 else PositionSide.SHORT
            unrealized_pnl = Decimal(str(position_data.get("upnl", "0")))
            entry_price = Decimal(str(position_data.get("EntryPrice", "0")))
            leverage = Decimal(str(position_data.get("Leverage", "1")))

            pos_key = self._perpetual_trading.position_key(trading_pair, position_side)

            _position = Position(
                trading_pair=trading_pair,
                position_side=position_side,
                unrealized_pnl=unrealized_pnl,
                entry_price=entry_price,
                amount=abs(size),
                leverage=leverage
            )
            self._perpetual_trading.set_position(pos_key, _position)

        # Remove positions that are no longer active
        if not positions:
            keys = list(self._perpetual_trading.account_positions.keys())
            for key in keys:
                self._perpetual_trading.remove_position(key)

    async def _get_position_mode(self) -> Optional[PositionMode]:
        """Gets the current position mode."""
        return PositionMode.ONEWAY

    async def _trading_pair_position_mode_set(self, mode: PositionMode, trading_pair: str) -> Tuple[bool, str]:
        """Sets position mode for a trading pair."""
        msg = ""
        success = True
        initial_mode = await self._get_position_mode()

        if initial_mode != mode:
            msg = "Strike only supports the ONEWAY position mode."
            success = False

        return success, msg

    async def _set_trading_pair_leverage(self, trading_pair: str, leverage: int) -> Tuple[bool, str]:
        """Sets leverage for a trading pair."""
        # Placeholder - Strike should provide leverage setting endpoint
        success = True
        msg = ""

        try:
            # When Strike implements leverage setting, add API call here
            pass
        except Exception as exception:
            success = False
            msg = f"There was an error setting the leverage for {trading_pair} ({exception})"

        return success, msg

    async def _fetch_last_fee_payment(self, trading_pair: str) -> Tuple[float, Decimal, Decimal]:
        """Fetches last funding fee payment."""
        # Placeholder - Strike should provide funding payment history
        timestamp = 0.0
        funding_rate = Decimal("-1")
        payment = Decimal("-1")

        return timestamp, funding_rate, payment

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        """Returns all trade updates for a specific order."""
        # Strike connector uses WebSocket for real-time trade updates
        # This method is not used as trades are processed via _user_stream_event_listener
        return []

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        """Initializes trading pair symbol mapping from exchange info."""
        mapping = bidict()
        # For Strike, we'll use the configured trading pairs
        # This will be enhanced when Strike provides a markets/exchange info endpoint
        if self._trading_pairs:
            for trading_pair in self._trading_pairs:
                # Strike uses symbols with hyphens (e.g., ADA-USDT)
                exchange_symbol = trading_pair  # Keep the hyphen
                mapping[exchange_symbol] = trading_pair
        self._set_trading_pair_symbol_map(mapping)
