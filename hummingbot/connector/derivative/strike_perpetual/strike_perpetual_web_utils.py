import time
from typing import Any, Dict, Optional

import hummingbot.connector.derivative.strike_perpetual.strike_perpetual_constants as CONSTANTS
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest
from hummingbot.core.web_assistant.rest_pre_processors import RESTPreProcessorBase
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


class StrikePerpetualRESTPreProcessor(RESTPreProcessorBase):
    """Pre-processes REST requests to add required headers."""

    async def pre_process(self, request: RESTRequest) -> RESTRequest:
        if request.headers is None:
            request.headers = {}
        request.headers["Content-Type"] = "application/json"
        request.headers["Accept"] = "application/json"
        return request


def private_rest_url(path_url: str, domain: str = CONSTANTS.DOMAIN) -> str:
    """
    Builds the full URL for private REST API endpoints.

    :param path_url: The API endpoint path
    :param domain: The exchange domain
    :return: The complete URL
    """
    return rest_url(path_url, domain)


def public_rest_url(path_url: str, domain: str = CONSTANTS.DOMAIN) -> str:
    """
    Builds the full URL for public REST API endpoints.

    :param path_url: The API endpoint path
    :param domain: The exchange domain
    :return: The complete URL
    """
    return rest_url(path_url, domain)


def rest_url(path_url: str, domain: str = CONSTANTS.DOMAIN, base_url: Optional[str] = None) -> str:
    """
    Builds the complete REST API URL.
    Routes requests to the appropriate service based on the endpoint.

    Market data endpoints go to Price Service (port 8082):
    - /v2/depth, /v2/trades, /v2/ticker/*, /v2/exchangeInfo, /v2/premiumIndex, /v2/klines

    All other endpoints go to Trading API (port 8080):
    - /v2/order, /v2/account, /v2/positions, etc.

    :param path_url: The API endpoint path
    :param domain: The exchange domain
    :param base_url: Optional override for base URL
    :return: The complete URL
    """
    if base_url is None:
        # Determine which service to use based on the endpoint
        market_data_endpoints = [
            "/v2/depth",
            "/v2/trades",
            "/v2/ticker/",
            "/v2/exchangeInfo",
            "/v2/premiumIndex",
            "/v2/klines",
        ]

        # Check if this is a market data endpoint
        is_market_data = any(path_url.startswith(endpoint) for endpoint in market_data_endpoints)

        if is_market_data:
            base_url = CONSTANTS.PERPETUAL_PRICE_URL  # Port 8082 - Price Service
        else:
            base_url = CONSTANTS.PERPETUAL_BASE_URL  # Port 8080 - Trading API

    return base_url + path_url


def wss_url(domain: str = CONSTANTS.DOMAIN) -> str:
    """
    Returns the WebSocket URL for the exchange.

    :param domain: The exchange domain
    :return: The WebSocket URL
    """
    return CONSTANTS.PERPETUAL_WS_URL


def build_api_factory(
    throttler: Optional[AsyncThrottler] = None,
    auth: Optional[AuthBase] = None
) -> WebAssistantsFactory:
    """
    Builds the WebAssistantsFactory with throttler and auth.

    :param throttler: The API throttler instance
    :param auth: The authentication instance
    :return: The WebAssistantsFactory instance
    """
    throttler = throttler or create_throttler()
    api_factory = WebAssistantsFactory(
        throttler=throttler,
        rest_pre_processors=[StrikePerpetualRESTPreProcessor()],
        auth=auth
    )
    return api_factory


def build_api_factory_without_time_synchronizer_pre_processor(
    throttler: AsyncThrottler
) -> WebAssistantsFactory:
    """
    Builds the WebAssistantsFactory without time synchronizer.

    :param throttler: The API throttler instance
    :return: The WebAssistantsFactory instance
    """
    api_factory = WebAssistantsFactory(
        throttler=throttler,
        rest_pre_processors=[StrikePerpetualRESTPreProcessor()]
    )
    return api_factory


def create_throttler() -> AsyncThrottler:
    """
    Creates the API throttler with rate limits from constants.

    :return: The AsyncThrottler instance
    """
    return AsyncThrottler(CONSTANTS.RATE_LIMITS)


async def get_current_server_time(
    throttler: AsyncThrottler,
    domain: str = CONSTANTS.DOMAIN
) -> float:
    """
    Gets the current server time.
    Strike API doesn't provide a dedicated time endpoint, so we use local time.

    :param throttler: The API throttler instance
    :param domain: The exchange domain
    :return: Current timestamp in seconds
    """
    return time.time()


def is_exchange_information_valid(exchange_info: Dict[str, Any]) -> bool:
    """
    Verifies if trading pair information from the exchange is valid.

    :param exchange_info: The exchange information dictionary
    :return: True if valid, False otherwise
    """
    # For Strike, we consider all markets valid if they have a symbol
    return "symbol" in exchange_info and exchange_info.get("status") == 1


def convert_hb_order_type_to_strike(order_type_str: str) -> int:
    """
    Converts Hummingbot order type to Strike API order type.

    :param order_type_str: Hummingbot order type string
    :return: Strike API order type integer
    """
    mapping = {
        "market": CONSTANTS.ORDER_TYPE_MARKET,
        "limit": CONSTANTS.ORDER_TYPE_LIMIT,
        "stop": CONSTANTS.ORDER_TYPE_STOP,
        "stop_limit": CONSTANTS.ORDER_TYPE_STOP_LIMIT,
        "take_profit": CONSTANTS.ORDER_TYPE_TAKE_PROFIT,
        "take_profit_limit": CONSTANTS.ORDER_TYPE_TAKE_PROFIT_LIMIT,
    }
    return mapping.get(order_type_str.lower(), CONSTANTS.ORDER_TYPE_LIMIT)


def convert_strike_order_type_to_hb(order_type: int) -> str:
    """
    Converts Strike API order type to Hummingbot order type string.

    :param order_type: Strike API order type integer
    :return: Hummingbot order type string
    """
    mapping = {
        CONSTANTS.ORDER_TYPE_MARKET: "MARKET",
        CONSTANTS.ORDER_TYPE_LIMIT: "LIMIT",
        CONSTANTS.ORDER_TYPE_STOP: "STOP",
        CONSTANTS.ORDER_TYPE_STOP_LIMIT: "STOP_LIMIT",
        CONSTANTS.ORDER_TYPE_TAKE_PROFIT: "TAKE_PROFIT",
        CONSTANTS.ORDER_TYPE_TAKE_PROFIT_LIMIT: "TAKE_PROFIT_LIMIT",
    }
    return mapping.get(order_type, "LIMIT")
