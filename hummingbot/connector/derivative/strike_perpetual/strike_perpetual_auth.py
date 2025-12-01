import json
from collections import OrderedDict
from typing import Dict

from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest, WSRequest


class StrikePerpetualAuth(AuthBase):
    """
    Auth class for Strike Perpetual API
    Strike supports two authentication methods:
    1. Account ID based (for manual testing)
    2. API Key based (for bot/automated trading)
    """

    def __init__(self, account_id: str, api_key: str = None):
        """
        :param account_id: The Strike account ID for authentication
        :param api_key: Optional API key for bot authentication (recommended for market making)
        """
        self._account_id: str = account_id
        self._api_key: str = api_key

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def api_key(self) -> str:
        return self._api_key

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """
        Adds authentication to REST API requests.

        If API key is provided, it uses X-API-Key header authentication (bot mode).
        Otherwise, it falls back to account_id based authentication (manual mode).

        :param request: The REST request to authenticate
        :return: The authenticated REST request
        """
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info("[STRIKE AUTH DEBUG] rest_authenticate called")
        logger.info("[STRIKE AUTH DEBUG] API key present: %s", self._api_key is not None and len(str(self._api_key)) > 0)
        logger.info("[STRIKE AUTH DEBUG] API key value (first 10 chars): %s", str(self._api_key)[:10] if self._api_key else 'None')

        # If API key is provided, use API key authentication
        if self._api_key:
            logger.info("[STRIKE AUTH DEBUG] Using API key authentication, adding X-API-Key header")
            # Add X-API-Key header for bot authentication
            if request.headers is None:
                request.headers = {}
            request.headers["X-API-Key"] = self._api_key
            logger.info(f"[STRIKE AUTH DEBUG] X-API-Key header added: {request.headers.get('X-API-Key', 'MISSING')[:10]}...")
            # Note: account_id is automatically set from the API key's associated account
        else:
            logger.warning("[STRIKE AUTH DEBUG] NO API KEY! Falling back to account_id authentication")
            # Fallback to account_id based authentication
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
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Add API key to headers if provided
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        return headers
