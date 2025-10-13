import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import hummingbot.connector.derivative.strike_perpetual.strike_perpetual_constants as CONSTANTS
import hummingbot.connector.derivative.strike_perpetual.strike_perpetual_web_utils as web_utils
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from hummingbot.connector.derivative.strike_perpetual.strike_perpetual_derivative import StrikePerpetualDerivative


class StrikePerpetualUserStreamDataSource(UserStreamTrackerDataSource):
    """User stream data source for Strike Perpetual."""

    LISTEN_KEY_KEEP_ALIVE_INTERVAL = 1800  # Keep connection alive interval
    HEARTBEAT_TIME_INTERVAL = 30.0
    _logger: Optional[HummingbotLogger] = None

    def __init__(
        self,
        auth: AuthBase,
        trading_pairs: List[str],
        connector: 'StrikePerpetualDerivative',
        api_factory: WebAssistantsFactory,
        domain: str = CONSTANTS.DOMAIN,
    ):
        super().__init__()
        self._domain = domain
        self._api_factory = api_factory
        self._auth = auth
        self._ws_assistants: List[WSAssistant] = []
        self._connector = connector
        self._current_listen_key = None
        self._listen_for_user_stream_task = None
        self._last_listen_key_ping_ts = None
        self._trading_pairs: List[str] = trading_pairs

    @property
    def last_recv_time(self) -> float:
        """
        Returns the last time a message was received from the WebSocket.

        :return: Timestamp of last received message
        """
        if self._ws_assistant:
            return self._ws_assistant.last_recv_time
        return 0

    async def _get_ws_assistant(self) -> WSAssistant:
        """
        Gets or creates a WebSocket assistant.

        :return: WSAssistant instance
        """
        if self._ws_assistant is None:
            self._ws_assistant = await self._api_factory.get_ws_assistant()
        return self._ws_assistant

    async def _connected_websocket_assistant(self) -> WSAssistant:
        """
        Creates an instance of WSAssistant connected to the Strike exchange.

        :return: Connected WSAssistant
        """
        ws: WSAssistant = await self._get_ws_assistant()
        url = web_utils.wss_url(self._domain)
        await ws.connect(ws_url=url, ping_timeout=self.HEARTBEAT_TIME_INTERVAL)
        safe_ensure_future(self._ping_thread(ws))
        return ws

    async def _subscribe_channels(self, websocket_assistant: WSAssistant):
        """
        Subscribes to order events and position updates.

        :param websocket_assistant: The WebSocket assistant to use for subscriptions
        """
        try:
            # Subscribe to order updates
            orders_change_payload = {
                "method": "subscribe",
                "channel": CONSTANTS.USER_ORDERS_ENDPOINT_NAME,
                "account_id": self._connector.strike_perpetual_account_id,
            }
            subscribe_order_change_request: WSJSONRequest = WSJSONRequest(
                payload=orders_change_payload,
                is_auth_required=True
            )

            # Subscribe to position updates
            positions_payload = {
                "method": "subscribe",
                "channel": CONSTANTS.USER_POSITIONS_ENDPOINT_NAME,
                "account_id": self._connector.strike_perpetual_account_id,
            }
            subscribe_positions_request: WSJSONRequest = WSJSONRequest(
                payload=positions_payload,
                is_auth_required=True
            )

            # Subscribe to balance updates
            balance_payload = {
                "method": "subscribe",
                "channel": CONSTANTS.USER_BALANCE_ENDPOINT_NAME,
                "account_id": self._connector.strike_perpetual_account_id,
            }
            subscribe_balance_request: WSJSONRequest = WSJSONRequest(
                payload=balance_payload,
                is_auth_required=True
            )

            await websocket_assistant.send(subscribe_order_change_request)
            await websocket_assistant.send(subscribe_positions_request)
            await websocket_assistant.send(subscribe_balance_request)

            self.logger().info("Subscribed to private order, position, and balance channels...")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().exception("Unexpected error occurred subscribing to user streams...")
            raise

    async def _process_event_message(self, event_message: Dict[str, Any], queue: asyncio.Queue):
        """
        Processes incoming WebSocket event messages.

        :param event_message: The event message to process
        :param queue: Queue to put processed messages
        """
        # Skip if message is not a dict (e.g., subscription confirmations)
        if not isinstance(event_message, dict):
            self.logger().debug(f"Skipping non-dict message: {event_message}")
            return

        # Check for errors
        if event_message.get("error") is not None:
            err_msg = event_message.get("error", {}).get("message", event_message.get("error"))
            raise IOError({
                "label": "WSS_ERROR",
                "message": f"Error received via websocket - {err_msg}."
            })

        # Skip subscription response messages (they have "result" field)
        if "result" in event_message and "channel" not in event_message:
            self.logger().debug(f"Skipping subscription response: {event_message}")
            return

        # Process user data messages
        if event_message.get("channel") in [
            CONSTANTS.USER_ORDERS_ENDPOINT_NAME,
            CONSTANTS.USER_POSITIONS_ENDPOINT_NAME,
            CONSTANTS.USER_BALANCE_ENDPOINT_NAME,
        ]:
            queue.put_nowait(event_message)

    async def _ping_thread(self, websocket_assistant: WSAssistant):
        """
        Sends periodic ping messages to keep the WebSocket connection alive.

        :param websocket_assistant: The WebSocket assistant
        """
        try:
            while True:
                ping_request = WSJSONRequest(payload={"method": "ping"})
                await asyncio.sleep(CONSTANTS.HEARTBEAT_TIME_INTERVAL)
                await websocket_assistant.send(ping_request)
        except Exception as e:
            self.logger().debug(f'Ping error: {e}')

    async def _process_websocket_messages(self, websocket_assistant: WSAssistant, queue: asyncio.Queue):
        """
        Processes WebSocket messages with ping/pong handling.

        :param websocket_assistant: The WebSocket assistant
        :param queue: Queue to put processed messages
        """
        while True:
            try:
                await super()._process_websocket_messages(
                    websocket_assistant=websocket_assistant,
                    queue=queue
                )
            except asyncio.TimeoutError:
                ping_request = WSJSONRequest(payload={"method": "ping"})
                await websocket_assistant.send(ping_request)
