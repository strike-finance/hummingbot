from decimal import Decimal
from typing import Optional

from pydantic import ConfigDict, Field, SecretStr

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap
from hummingbot.core.data_type.trade_fee import TradeFeeSchema

# Default fees for Strike Perpetual
# Maker and taker fees - adjust these based on Strike's actual fee structure
DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.0002"),  # 0.02% maker fee
    taker_percent_fee_decimal=Decimal("0.0005"),  # 0.05% taker fee
    buy_percent_fee_deducted_from_returns=True
)

CENTRALIZED = True

EXAMPLE_PAIR = "BTC-USDT"

BROKER_ID = "HBOT"


class StrikePerpetualConfigMap(BaseConnectorConfigMap):
    """Configuration map for Strike Perpetual connector."""

    connector: str = "strike_perpetual"
    strike_perpetual_account_id: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Strike account ID",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    strike_perpetual_base_url: str = Field(
        default="http://localhost:8080",
        json_schema_extra={
            "prompt": "Enter Strike API base URL (default: http://localhost:8080)",
            "is_secure": False,
            "is_connect_key": False,
            "prompt_on_new": False,
        }
    )
    strike_perpetual_ws_url: str = Field(
        default="ws://localhost:8081/ws",
        json_schema_extra={
            "prompt": "Enter Strike WebSocket URL (default: ws://localhost:8081/ws)",
            "is_secure": False,
            "is_connect_key": False,
            "prompt_on_new": False,
        }
    )

    model_config = ConfigDict(title="strike_perpetual")


KEYS = StrikePerpetualConfigMap.model_construct()
