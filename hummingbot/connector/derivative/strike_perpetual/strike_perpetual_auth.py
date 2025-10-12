import json
from collections import OrderedDict
from typing import Dict

from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest, WSRequest


class StrikePerpetualAuth(AuthBase):
    """
    Auth class for Strike Perpetual API
    Strike uses a simple account_id based authentication system.
    """

    def __init__(self, account_id: str):
        """
        :param account_id: The Strike account ID for authentication
        """
        self._account_id: str = account_id

    @property
    def account_id(self) -> str:
        return self._account_id

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """
        Adds authentication to REST API requests by injecting account_id into request data.

        :param request: The REST request to authenticate
        :return: The authenticated REST request
        """
        if request.method == RESTMethod.POST:
            # Add account_id to POST request body
            request.data = self._add_account_id_to_params(request.data)
        elif request.method == RESTMethod.GET:
            # Add account_id to GET request params
            if request.params is None:
                request.params = {}
            request.params["account_id"] = self._account_id
        elif request.method == RESTMethod.DELETE:
            # Add account_id to DELETE request body
            request.data = self._add_account_id_to_params(request.data)

        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        """
        Adds authentication to WebSocket messages.

        :param request: The WebSocket request to authenticate
        :return: The authenticated WebSocket request
        """
        if request.payload is None:
            request.payload = {}

        # Add account_id to WebSocket subscription message
        if isinstance(request.payload, dict):
            request.payload["account_id"] = self._account_id

        return request

    def _add_account_id_to_params(self, params: str) -> str:
        """
        Adds account_id to request parameters.

        :param params: JSON string of request parameters
        :return: Modified JSON string with account_id added
        """
        try:
            data = json.loads(params) if params else {}
        except (json.JSONDecodeError, TypeError):
            data = {}

        request_params = OrderedDict(data or {})

        # Add account_id if not already present
        if "account_id" not in request_params:
            request_params["account_id"] = self._account_id

        return json.dumps(request_params)

    def get_headers(self) -> Dict[str, str]:
        """
        Returns the headers required for Strike API requests.

        :return: Dictionary of HTTP headers
        """
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
