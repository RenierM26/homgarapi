"""Client wrapper for the HomGar REST API."""

from __future__ import annotations

import binascii
from collections.abc import Mapping, MutableMapping, Sequence
from datetime import UTC, datetime, timedelta
import hashlib
import os
from typing import Any, cast

from homgarapi.devices import (
    MODEL_CODE_MAPPING,
    HomgarDevice,
    HomgarHome,
    HomgarHubDevice,
)
from homgarapi.logutil import TRACE, get_logger
import requests

logger = get_logger(__file__)


class HomgarApiException(Exception):
    """Raised when the HomGar API returns a non-success response."""

    def __init__(self, code: int, message: str | None) -> None:
        """Store the API error information."""
        super().__init__(code, message)
        self.code = code
        self.message = message or ""

    def __str__(self) -> str:
        """Return a readable representation of the error."""
        base = f"HomGar API returned code {self.code}"
        return f"{base} ('{self.message}')" if self.message else base


class HomgarApi:
    """Thin client around the HomGar REST endpoints."""

    def __init__(
        self,
        auth_cache: MutableMapping[str, Any] | None = None,
        api_base_url: str = "https://region3.homgarus.com",
        requests_session: requests.Session | None = None,
    ) -> None:
        """Initialise the API client.

        :param auth_cache: Mutable mapping used to persist authentication data between runs.
        :param api_base_url: Base URL for the HomGar API, without a trailing slash.
        :param requests_session: Optional `requests.Session` to reuse; a new one is created when omitted.
        """
        self.session: requests.Session = requests_session or requests.Session()
        self.cache: MutableMapping[str, Any] = auth_cache or {}
        self.base = api_base_url.rstrip("/")

    def _request(
        self,
        method: str,
        url: str,
        *,
        with_auth: bool = True,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """Make an HTTP request against the HomGar API.

        :param method: HTTP verb to use (GET, POST, ...).
        :param url: Fully qualified URL to call.
        :param with_auth: Whether to include the cached authentication token.
        :param headers: Additional HTTP headers to include with the request.
        :param kwargs: Extra keyword arguments forwarded to `requests.Session.request`.
        :returns: The HTTP response object.
        """
        request_headers = {"lang": "en", "appCode": "1", **(headers or {})}
        if with_auth:
            token = self.cache.get("token")
            if not token:
                msg = "Authentication token missing from cache"
                raise HomgarApiException(-1, msg)
            request_headers["auth"] = str(token)

        logger.log(TRACE, "%s %s %s", method, url, kwargs)
        response = self.session.request(method, url, headers=request_headers, **kwargs)
        logger.log(TRACE, "-[%03d]-> %s", response.status_code, response.text)
        return response

    def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        """Perform a JSON request and return the inner `data` payload.

        :param method: HTTP verb to use (GET, POST, ...).
        :param path: Path relative to the configured base URL.
        :param kwargs: Extra keyword arguments forwarded to `_request`.
        :returns: The JSON `data` field when the call succeeds.
        :raises HomgarApiException: If the API reports a non-zero code.
        """
        response = self._request(method, f"{self.base}{path}", **kwargs).json()
        code = int(response.get("code", -1))
        if code != 0:
            raise HomgarApiException(code, response.get("msg"))
        return response.get("data")

    def _get_json(self, path: str, **kwargs: Any) -> Any:
        return self._request_json("GET", path, **kwargs)

    def _post_json(self, path: str, body: Mapping[str, Any], **kwargs: Any) -> Any:
        return self._request_json("POST", path, json=body, **kwargs)

    def get_product_models(self) -> Mapping[str, Any]:
        """Retrieve the list of supported product models from the API.

        :returns: Mapping containing model metadata (`version`, `modelCodes`, `models`, ...).
        """
        return cast(Mapping[str, Any], self._get_json("/app/common/core/productModel/json"))

    def login(self, email: str, password: str, area_code: str = "31") -> None:
        """Perform a login and cache the resulting tokens.

        :param email: HomGar account e-mail address.
        :param password: HomGar account password.
        :param area_code: Phone country code associated with the account (for example ``"31"`` for NL).
        """
        payload = {
            "areaCode": area_code,
            "phoneOrEmail": email,
            "password": hashlib.md5(password.encode("utf-8")).hexdigest(),
            "deviceId": binascii.b2a_hex(os.urandom(16)).decode("utf-8"),
        }
        data = self._post_json("/auth/basic/app/login", payload, with_auth=False)
        expires_in: int = int(data.get("tokenExpired", 0))
        self.cache["email"] = email
        self.cache["token"] = data.get("token")
        self.cache["token_expires"] = datetime.now(tz=UTC).timestamp() + expires_in
        self.cache["refresh_token"] = data.get("refreshToken")

    def get_homes(self) -> list[HomgarHome]:
        """Return all homes linked to the current account.

        :returns: List of `HomgarHome` instances.
        """
        data = self._get_json("/app/member/appHome/list")
        homes: Sequence[Mapping[str, Any]] = data or []
        return [
            HomgarHome(hid=home.get("hid"), name=home.get("homeName"))
            for home in homes
        ]

    def get_devices_for_hid(self, hid: str) -> list[HomgarHubDevice]:
        """Return hubs and subdevices for the provided home id.

        :param hid: The home identifier supplied by HomGar.
        :returns: List of `HomgarHubDevice` objects populated with subdevices.
        """
        data = self._get_json("/app/device/getDeviceByHid", params={"hid": str(hid)})
        hubs: list[HomgarHubDevice] = []
        devices: Sequence[Mapping[str, Any]] = data or []

        def device_base_props(dev_data: Mapping[str, Any]) -> dict[str, Any]:
            return {
                "model": dev_data.get("model"),
                "model_code": dev_data.get("modelCode"),
                "name": dev_data.get("name"),
                "did": dev_data.get("did"),
                "mid": dev_data.get("mid"),
                "address": dev_data.get("addr"),
                "port_number": dev_data.get("portNumber"),
                "alerts": dev_data.get("alerts"),
                "device_name": dev_data.get("deviceName"),
                "product_key": dev_data.get("productKey"),
            }

        def get_device_class(dev_data: Mapping[str, Any]) -> type[HomgarDevice] | None:
            model_code_value = dev_data.get("modelCode")
            if not isinstance(model_code_value, (str, int)):
                return None
            try:
                model_code_int = int(model_code_value)
            except (TypeError, ValueError):
                return None

            device_class = MODEL_CODE_MAPPING.get(model_code_int)
            if device_class is None:
                logger.warning(
                    "Unknown device '%s' with modelCode %s",
                    dev_data.get("model"),
                    model_code_value,
                )
            return cast(type[HomgarDevice] | None, device_class)

        for hub_data in devices:
            subdevices: list[HomgarDevice] = []
            for subdevice_data in hub_data.get("subDevices", []):
                did = subdevice_data.get("did")
                if did == 1:  # display hub
                    continue
                subdevice_class = get_device_class(subdevice_data)
                if subdevice_class is None:
                    continue
                subdevices.append(subdevice_class(**device_base_props(subdevice_data)))

            hub_class = get_device_class(hub_data) or HomgarHubDevice
            hubs.append(hub_class(**device_base_props(hub_data), subdevices=subdevices))

        return hubs

    def get_device_status(self, hub: HomgarHubDevice) -> None:
        """Request status updates for all devices attached to a hub.

        :param hub: Hub whose subdevices should be updated in place.
        """
        status_payload: Sequence[Mapping[str, Any]] | None = None

        if hub.device_name and hub.product_key:
            body = {
                "devices": [
                    {
                        "deviceName": hub.device_name,
                        "mid": str(hub.mid),
                        "productKey": hub.product_key,
                    }
                ]
            }
            try:
                response = self._post_json("/app/device/multipleDeviceStatus", body)
                if isinstance(response, Sequence) and response:
                    first_entry = response[0]
                    if isinstance(first_entry, Mapping):
                        raw_status = first_entry.get("status", [])
                        if isinstance(raw_status, Sequence):
                            status_payload = [
                                item
                                for item in raw_status
                                if isinstance(item, Mapping)
                            ]
            except HomgarApiException as err:
                logger.debug("multipleDeviceStatus failed: %s", err)

        if status_payload is None:
            data = self._get_json("/app/device/getDeviceStatus", params={"mid": str(hub.mid)})
            raw_status = data.get("subDeviceStatus", []) if isinstance(data, Mapping) else []
            if isinstance(raw_status, Sequence):
                status_payload = [item for item in raw_status if isinstance(item, Mapping)]
            else:
                status_payload = []

        id_map = {
            status_id: device
            for device in (hub, *hub.subdevices)
            for status_id in device.get_device_status_ids()
        }

        for subdevice_status in status_payload:
            device = id_map.get(str(subdevice_status.get("id")))
            if device is not None:
                device.set_device_status(subdevice_status)

    def ensure_logged_in(self, email: str, password: str, area_code: str = "31") -> None:
        """Ensure a valid token is present, refreshing if required.

        :param email: HomGar account e-mail address.
        :param password: HomGar account password.
        :param area_code: Phone country code associated with the account.
        """
        cache_email = self.cache.get("email")
        expires_at = float(self.cache.get("token_expires", 0))
        remaining = datetime.fromtimestamp(expires_at, tz=UTC) - datetime.now(tz=UTC)
        if cache_email != email or remaining < timedelta(minutes=60):
            self.login(email, password, area_code=area_code)
