import asyncio
import json
import logging
from decimal import Decimal
from typing import Optional

import aiohttp

from hummingbot.core.network_base import NetworkBase
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.logger import HummingbotLogger


class CustomAPIDataFeed(NetworkBase):
    cadf_logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls.cadf_logger is None:
            cls.cadf_logger = logging.getLogger(__name__)
        return cls.cadf_logger

    def __init__(self, api_url, update_interval: float = 5.0):
        super().__init__()
        self._ready_event = asyncio.Event()
        self._shared_client: Optional[aiohttp.ClientSession] = None
        self._api_url = api_url
        self._check_network_interval = 30.0
        self._ev_loop = asyncio.get_event_loop()
        self._price: Decimal = Decimal("0")
        self._update_interval: float = update_interval
        self._fetch_price_task: Optional[asyncio.Task] = None

    @property
    def name(self):
        return "custom_api"

    @property
    def health_check_endpoint(self):
        return self._api_url

    def _http_client(self) -> aiohttp.ClientSession:
        if self._shared_client is None:
            self._shared_client = aiohttp.ClientSession()
        return self._shared_client

    async def check_network(self) -> NetworkStatus:
        client = self._http_client()
        async with client.request("GET", self.health_check_endpoint) as resp:
            status_text = await resp.text()
            if resp.status != 200:
                raise Exception(f"Custom API Feed {self.name} server error: {status_text}")
        return NetworkStatus.CONNECTED

    def get_price(self) -> Decimal:
        return self._price

    async def fetch_price_loop(self):
        while True:
            try:
                await self.fetch_price()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network(f"Error fetching a new price from {self._api_url}.", exc_info=True,
                                      app_warning_msg="Couldn't fetch newest price from CustomAPI. "
                                                      "Check network connection.")

            await asyncio.sleep(self._update_interval)

    async def fetch_price(self):
        client = self._http_client()
        async with client.request("GET", self._api_url) as resp:
            resp_text = await resp.text()
            if resp.status != 200:
                raise Exception(f"Custom API Feed {self.name} server error: {resp_text}")
            try:
                data = json.loads(resp_text)
                if isinstance(data, dict):
                    # Check for orderbook format (Binance depth endpoint)
                    # Format: {"bids": [["price", "qty"], ...], "asks": [["price", "qty"], ...]}
                    if "bids" in data and "asks" in data:
                        bids = data.get("bids", [])
                        asks = data.get("asks", [])
                        if bids and asks:
                            best_bid = Decimal(str(bids[0][0]))
                            best_ask = Decimal(str(asks[0][0]))
                            self._price = (best_bid + best_ask) / Decimal("2")
                    # Check for ticker price format (e.g., {"price": "104000.00"})
                    elif "price" in data:
                        self._price = Decimal(str(data["price"]))
                    # Check for other common price field names
                    else:
                        price_value = data.get("mid_price") or data.get("last_price") or data.get("mark_price")
                        if price_value is not None:
                            self._price = Decimal(str(price_value))
                else:
                    # If JSON but not a dict (e.g., just a number), use directly
                    self._price = Decimal(str(data))
            except json.JSONDecodeError:
                # Not JSON, treat as plain number
                self._price = Decimal(str(resp_text))
        self._ready_event.set()

    async def start_network(self):
        await self.stop_network()
        self._fetch_price_task = safe_ensure_future(self.fetch_price_loop())

    async def stop_network(self):
        if self._fetch_price_task is not None:
            self._fetch_price_task.cancel()
            self._fetch_price_task = None

    def start(self):
        NetworkBase.start(self)

    def stop(self):
        NetworkBase.stop(self)
