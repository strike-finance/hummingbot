import asyncio
import time
from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

import hummingbot.connector.derivative.strike_perpetual.strike_perpetual_constants as CONSTANTS
import hummingbot.connector.derivative.strike_perpetual.strike_perpetual_web_utils as web_utils
from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.funding_info import FundingInfo, FundingInfoUpdate
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.perpetual_api_order_book_data_source import PerpetualAPIOrderBookDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from hummingbot.connector.derivative.strike_perpetual.strike_perpetual_derivative import StrikePerpetualDerivative


class StrikePerpetualAPIOrderBookDataSource(PerpetualAPIOrderBookDataSource):
    """Order book data source for Strike Perpetual."""

    _bpobds_logger: Optional[HummingbotLogger] = None
    _trading_pair_symbol_map: Dict[str, Mapping[str, str]] = {}
    _mapping_initialization_lock = asyncio.Lock()

    def __init__(
        self,
        trading_pairs: List[str],
        connector: 'StrikePerpetualDerivative',
        api_factory: WebAssistantsFactory,
        domain: str = CONSTANTS.DOMAIN,
    ):
        super().__init__(trading_pairs)
        self._connector = connector
        self._api_factory = api_factory
        self._domain = domain
        self._trading_pairs: List[str] = trading_pairs
        self._message_queue: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._snapshot_messages_queue_key = "order_book_snapshot"

    async def get_last_traded_prices(
        self,
        trading_pairs: List[str],
        domain: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Gets the last traded prices for the given trading pairs.

        :param trading_pairs: List of trading pairs
        :param domain: Not used for Strike
        :return: Dictionary mapping trading pair to last price
        """
        return await self._connector.get_last_traded_prices(trading_pairs=trading_pairs)

    async def get_funding_info(self, trading_pair: str) -> FundingInfo:
        """
        Gets funding information for a trading pair.

        :param trading_pair: The trading pair
        :return: FundingInfo object
        """
        # Strike v2 backend will provide funding info through its API
        # For now, return a default funding info structure
        # This should be implemented based on Strike's actual API response
        funding_info = FundingInfo(
            trading_pair=trading_pair,
            index_price=Decimal("0"),
            mark_price=Decimal("0"),
            next_funding_utc_timestamp=self._next_funding_time(),
            rate=Decimal("0"),
        )
        return funding_info

    async def listen_for_funding_info(self, output: asyncio.Queue):
        """
        Listens for funding info updates and pushes them to the output queue.

        :param output: Queue to push funding info updates
        """
        while True:
            try:
                for trading_pair in self._trading_pairs:
                    funding_info = await self.get_funding_info(trading_pair)
                    funding_info_update = FundingInfoUpdate(
                        trading_pair=trading_pair,
                        index_price=funding_info.index_price,
                        mark_price=funding_info.mark_price,
                        next_funding_utc_timestamp=funding_info.next_funding_utc_timestamp,
                        rate=funding_info.rate,
                    )
                    output.put_nowait(funding_info_update)
                await self._sleep(CONSTANTS.FUNDING_RATE_UPDATE_INTERNAL_SECOND)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Unexpected error when processing public funding info updates from exchange")
                await self._sleep(CONSTANTS.FUNDING_RATE_UPDATE_INTERNAL_SECOND)

    async def _request_order_book_snapshot(self, trading_pair: str) -> Dict[str, Any]:
        """
        Requests order book snapshot from Strike API.

        :param trading_pair: The trading pair
        :return: Order book snapshot data
        """
        ex_trading_pair = await self._connector.exchange_symbol_associated_to_pair(trading_pair=trading_pair)

        # Request orderbook from Strike v2 /v2/depth endpoint
        params = {
            "symbol": ex_trading_pair,
            "limit": 100
        }

        rest_assistant = await self._api_factory.get_rest_assistant()
        depth_url = web_utils.public_rest_url(CONSTANTS.DEPTH_URL, domain=self._domain)

        try:
            data = await rest_assistant.execute_request(
                url=depth_url,
                params=params,
                method=RESTMethod.GET,
                throttler_limit_id=CONSTANTS.DEPTH_URL,
            )

            # If orderbook is empty or failed, create synthetic orderbook from index price
            if not data or (not data.get("bids") and not data.get("asks")):
                # Get index price from markets endpoint
                try:
                    rest_assistant = await self._api_factory.get_rest_assistant()
                    markets_url = web_utils.public_rest_url(CONSTANTS.MARKETS_URL, domain=self._domain)
                    markets_data = await rest_assistant.execute_request(
                        url=markets_url,
                        method=RESTMethod.GET,
                        throttler_limit_id=CONSTANTS.MARKETS_URL,
                    )

                    market_data = markets_data.get("markets", {}).get(ex_trading_pair, {})
                    index_price = float(market_data.get("index_price", 0))

                    # If no index price, use mark_price or last_price
                    if index_price == 0:
                        index_price = float(market_data.get("mark_price", 0))
                    if index_price == 0:
                        index_price = float(market_data.get("last_price", 0))

                    # If all prices are still 0, raise an error
                    if index_price == 0:
                        raise ValueError(
                            f"No valid price data available for {trading_pair} from Strike API. "
                            f"Cannot create orderbook without price information."
                        )

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

                    data = {
                        "symbol": ex_trading_pair,
                        "bids": bids,
                        "asks": asks,
                        "timestamp": int(time.time() * 1000)
                    }

                    self.logger().info(
                        f"Created synthetic orderbook for {trading_pair} at {index_price} "
                        f"(bid: {bids[0][0]}, ask: {asks[0][0]})"
                    )

                except Exception as e:
                    self.logger().warning(f"Failed to create synthetic orderbook: {e}")
                    data = {
                        "symbol": ex_trading_pair,
                        "bids": [],
                        "asks": [],
                        "timestamp": int(time.time() * 1000)
                    }

            return data
        except Exception as e:
            self.logger().warning(f"Failed to fetch orderbook from Strike for {trading_pair}: {e}")
            return None

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        """
        Creates an order book snapshot message.

        :param trading_pair: The trading pair
        :return: OrderBookMessage with snapshot data
        """
        snapshot_response: Dict[str, Any] = await self._request_order_book_snapshot(trading_pair)
        snapshot_msg: OrderBookMessage = OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            {
                "trading_pair": trading_pair,
                "update_id": snapshot_response.get("timestamp", int(time.time() * 1000)),
                "bids": snapshot_response.get("bids", []),
                "asks": snapshot_response.get("asks", []),
            },
            timestamp=snapshot_response.get("timestamp", time.time())
        )
        return snapshot_msg

    async def _connected_websocket_assistant(self) -> WSAssistant:
        """
        Creates and connects a WebSocket assistant.

        :return: Connected WSAssistant
        """
        url = self._connector.strike_perpetual_ws_url
        ws: WSAssistant = await self._api_factory.get_ws_assistant()
        await ws.connect(ws_url=url, ping_timeout=CONSTANTS.HEARTBEAT_TIME_INTERVAL)
        return ws

    async def _subscribe_channels(self, ws: WSAssistant):
        """
        Subscribes to WebSocket channels for order book and trade data.

        :param ws: The WebSocket assistant
        """
        try:
            for trading_pair in self._trading_pairs:
                symbol = await self._connector.exchange_symbol_associated_to_pair(trading_pair=trading_pair)

                # Subscribe to trades
                trades_payload = {
                    "method": "subscribe",
                    "channel": CONSTANTS.TRADES_ENDPOINT_NAME,
                    "symbol": symbol,
                }
                subscribe_trade_request: WSJSONRequest = WSJSONRequest(payload=trades_payload)

                # Subscribe to orderbook
                order_book_payload = {
                    "method": "subscribe",
                    "channel": CONSTANTS.DEPTH_ENDPOINT_NAME,
                    "symbol": symbol,
                }
                subscribe_orderbook_request: WSJSONRequest = WSJSONRequest(payload=order_book_payload)

                await ws.send(subscribe_trade_request)
                await ws.send(subscribe_orderbook_request)

                self.logger().info(f"Subscribed to public order book and trade channels for {trading_pair}...")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().error("Unexpected error occurred subscribing to order book data streams.")
            raise

    def _channel_originating_message(self, event_message: Dict[str, Any]) -> str:
        """
        Determines which channel a message originated from.

        :param event_message: The WebSocket message
        :return: Channel identifier string
        """
        channel = ""
        if "result" not in event_message:
            channel_name = event_message.get("channel", "")
            if CONSTANTS.DEPTH_ENDPOINT_NAME in channel_name:
                channel = self._snapshot_messages_queue_key
            elif CONSTANTS.TRADES_ENDPOINT_NAME in channel_name:
                channel = self._trade_messages_queue_key
        return channel

    async def _parse_order_book_diff_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        """
        Parses an order book diff message from WebSocket.

        :param raw_message: Raw WebSocket message
        :param message_queue: Queue to push parsed message
        """
        data = raw_message.get("data", {})
        timestamp = data.get("timestamp", time.time())
        trading_pair = data.get("symbol", "")

        if trading_pair:
            trading_pair = await self._connector.trading_pair_associated_to_exchange_symbol(trading_pair)
            order_book_message: OrderBookMessage = OrderBookMessage(
                OrderBookMessageType.DIFF,
                {
                    "trading_pair": trading_pair,
                    "update_id": data.get("update_id", int(timestamp * 1000)),
                    "bids": data.get("bids", []),
                    "asks": data.get("asks", []),
                },
                timestamp=timestamp
            )
            message_queue.put_nowait(order_book_message)

    async def _parse_order_book_snapshot_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        """
        Parses an order book snapshot message from WebSocket.

        :param raw_message: Raw WebSocket message
        :param message_queue: Queue to push parsed message
        """
        data = raw_message.get("data", {})
        timestamp = data.get("timestamp", time.time())
        trading_pair = data.get("symbol", "")

        if trading_pair:
            trading_pair = await self._connector.trading_pair_associated_to_exchange_symbol(trading_pair)
            order_book_message: OrderBookMessage = OrderBookMessage(
                OrderBookMessageType.SNAPSHOT,
                {
                    "trading_pair": trading_pair,
                    "update_id": data.get("update_id", int(timestamp * 1000)),
                    "bids": data.get("bids", []),
                    "asks": data.get("asks", []),
                },
                timestamp=timestamp
            )
            message_queue.put_nowait(order_book_message)

    async def _parse_trade_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        """
        Parses a trade message from WebSocket.

        :param raw_message: Raw WebSocket message
        :param message_queue: Queue to push parsed message
        """
        data = raw_message.get("data", {})
        trading_pair = data.get("symbol", "")

        if trading_pair:
            trading_pair = await self._connector.trading_pair_associated_to_exchange_symbol(trading_pair)
            trade_message: OrderBookMessage = OrderBookMessage(
                OrderBookMessageType.TRADE,
                {
                    "trading_pair": trading_pair,
                    "trade_type": float(TradeType.BUY.value if data.get("side") == 1 else TradeType.SELL.value),
                    "trade_id": data.get("trade_id", ""),
                    "price": float(data.get("price", 0)),
                    "amount": float(data.get("size", 0))
                },
                timestamp=data.get("timestamp", time.time())
            )
            message_queue.put_nowait(trade_message)

    async def _parse_funding_info_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        """
        Parses a funding info message from WebSocket.

        :param raw_message: Raw WebSocket message
        :param message_queue: Queue to push parsed message
        """
        # Placeholder for funding info message parsing
        pass

    async def _request_complete_funding_info(self, trading_pair: str):
        """
        Requests complete funding information from Strike API.

        :param trading_pair: The trading pair
        :return: Funding info data
        """
        # Placeholder - Strike backend needs to implement funding info endpoint
        return {}

    def _next_funding_time(self) -> int:
        """
        Calculates the next funding timestamp.
        Assuming 8-hour funding intervals (standard for perpetual exchanges).

        :return: Unix timestamp of next funding time
        """
        current_time = int(time.time())
        funding_interval = 8 * 3600  # 8 hours in seconds
        next_funding = ((current_time // funding_interval) + 1) * funding_interval
        return next_funding
