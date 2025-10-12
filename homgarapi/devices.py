"""Device model definitions for the HomGar API client."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any, ClassVar, Final

from homgarapi.dp_decoder import decode_status_payload

ParsedStats = tuple[int | None, int | None, int | None, int | None]

STATS_VALUE_REGEX: Final[re.Pattern[str]] = re.compile(r"^(\d+)\((\d+)/(\d+)/(\d+)\)")


def _parse_stats_value(value: str) -> ParsedStats:
    """Parse a stats string of the format 'value(max/min/trend)'."""
    match = STATS_VALUE_REGEX.fullmatch(value)
    if match:
        return (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
        )
    return (None, None, None, None)


def _temp_to_mk(raw_fahrenheit_tenths: str | int) -> int:
    """Convert tenths of degrees Fahrenheit to millikelvin."""
    raw_value = int(raw_fahrenheit_tenths)
    celsius = (raw_value * 0.1 - 32.0) * 5 / 9
    return round((celsius + 273.15) * 1000)


def _celsius_to_mk(value: float) -> int:
    """Convert degrees Celsius to millikelvin."""
    return round((value + 273.15) * 1000)


class HomgarHome:
    """Representation of a HomGar home."""

    hid: str
    name: str

    def __init__(self, hid: str | int, name: str | None) -> None:
        """Initialise the home model."""
        self.hid = str(hid)
        self.name = name or ""


class HomgarDevice:
    """Base class for HomGar devices."""

    FRIENDLY_DESC: ClassVar[str] = "Unknown HomGar device"

    def __init__(
        self,
        *,
        model: str | None,
        model_code: int | None,
        name: str | None,
        did: str | int | None,
        mid: str | int | None,
        alerts: Iterable[Any] | None = None,
        device_name: str | None = None,
        product_key: str | None = None,
        **_: Any,
    ) -> None:
        """Initialise a device with metadata returned by the API."""
        self.model: str | None = model
        self.model_code: int | None = int(model_code) if model_code is not None else None
        self.name: str = name or "Unknown"
        self.did: str = str(did) if did is not None else "unknown"
        self.mid: str = str(mid) if mid is not None else "unknown"
        self.alerts: list[Any] = list(alerts or [])
        self.device_name: str | None = device_name
        self.product_key: str | None = product_key
        self.status_fields: dict[str, Any] = {}

        self.address: int | None = None
        self.rf_rssi: int | None = None

    def __str__(self) -> str:
        """Return a human readable description."""
        return f'{self.FRIENDLY_DESC} "{self.name}" (DID {self.did})'

    def get_device_status_ids(self) -> list[str]:
        """Return status identifiers that apply to this device."""
        return []

    def set_device_status(self, api_obj: Mapping[str, Any]) -> None:
        """Update the device state with data from the API."""
        if self.address is None:
            return
        if api_obj.get("id") == f"D{self.address:02d}":
            value = api_obj.get("value", "")
            if isinstance(value, str):
                self._parse_status_d_value(value)

    def _parse_status_d_value(self, payload: str) -> None:
        """Parse the common and device-specific sections of a status payload."""
        if ";" not in payload:
            self._parse_general_status_d_value(payload)
            return
        general_str, specific_str = payload.split(";", 1)
        self._parse_general_status_d_value(general_str)
        self._parse_device_specific_status_d_value(specific_str)

    def _parse_general_status_d_value(self, value: str) -> None:
        """Parse the general section, capturing the RF RSSI if present."""
        parts = value.split(",")
        if len(parts) >= 2:
            try:
                self.rf_rssi = int(parts[1])
            except ValueError:
                self.rf_rssi = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Parse the device-specific section of the payload."""
        raise NotImplementedError


class HomgarHubDevice(HomgarDevice):
    """A hub acts as a gateway for sensors and actuators."""

    def __init__(self, *, subdevices: Iterable[HomgarDevice] | None = None, **kwargs: Any) -> None:
        """Initialise the hub and store its subdevices."""
        super().__init__(**kwargs)
        self.address = 1
        self.subdevices: list[HomgarDevice] = list(subdevices or [])

    def __str__(self) -> str:
        """Return a human readable description for the hub."""
        return f"{super().__str__()} with {len(self.subdevices)} subdevices"

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Store raw payload data produced by the hub."""
        self.alerts.append({"raw_status": value})


class HomgarSubDevice(HomgarDevice):
    """A device that is associated with a hub."""

    def __init__(self, *, address: int, port_number: int, **kwargs: Any) -> None:
        """Initialise the subdevice address and port metadata."""
        super().__init__(**kwargs)
        self.address = address
        self.port_number = port_number

    def __str__(self) -> str:
        """Return a human readable description for the subdevice."""
        return f"{super().__str__()} at address {self.address}"

    def get_device_status_ids(self) -> list[str]:
        """Return identifiers for status updates relevant to this device."""
        return [f"D{self.address:02d}"]

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Store raw payload for subclasses that do not override parsing."""
        self.alerts.append({"raw_status": value})


class RainPointDisplayHub(HomgarHubDevice):
    """RainPoint irrigation display hub."""

    MODEL_CODES: ClassVar[list[int]] = [264]
    FRIENDLY_DESC: ClassVar[str] = "Irrigation Display Hub"

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the display hub."""
        super().__init__(**kwargs)
        self.wifi_rssi: int | None = None
        self.battery_state: int | None = None
        self.connected: bool | None = None

        self.temp_mk_current: int | None = None
        self.temp_mk_daily_max: int | None = None
        self.temp_mk_daily_min: int | None = None
        self.temp_trend: int | None = None
        self.hum_current: int | None = None
        self.hum_daily_max: int | None = None
        self.hum_daily_min: int | None = None
        self.hum_trend: int | None = None
        self.press_pa_current: int | None = None
        self.press_pa_daily_max: int | None = None
        self.press_pa_daily_min: int | None = None
        self.press_trend: int | None = None

    def get_device_status_ids(self) -> list[str]:
        """Return identifiers for hub-specific status updates."""
        return ["connected", "state", "D01"]

    def set_device_status(self, api_obj: Mapping[str, Any]) -> None:
        """Handle hub-specific updates before delegating to the base class."""
        dev_id = api_obj.get("id")
        val = api_obj.get("value")
        if dev_id == "state" and isinstance(val, str):
            parts = [segment for segment in val.split(",") if segment]
            if len(parts) >= 1:
                try:
                    self.battery_state = int(parts[0])
                except ValueError:
                    self.battery_state = None
            if len(parts) >= 2:
                try:
                    self.wifi_rssi = int(parts[1])
                except ValueError:
                    self.wifi_rssi = None
        elif dev_id == "connected":
            self.connected = str(val) == "1"
        else:
            super().set_device_status(api_obj)

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Parse the display hub payload into temperature, humidity, and pressure statistics.

        Observed example value: ``781(781/723/1),52(64/50/1),P=10213(10222/10205/1)``.

        Deduced meaning: temperature, humidity, and pressure with day statistics.
        """

        temp_str, hum_str, press_str, *_ = value.split(",")
        temp_stats = _parse_stats_value(temp_str)
        converted_temp = tuple(_temp_to_mk(stat) if stat is not None else None for stat in temp_stats)
        (
            self.temp_mk_current,
            self.temp_mk_daily_max,
            self.temp_mk_daily_min,
            self.temp_trend,
        ) = converted_temp
        self.hum_current, self.hum_daily_max, self.hum_daily_min, self.hum_trend = _parse_stats_value(hum_str)
        press_stats = _parse_stats_value(press_str[2:])
        (
            self.press_pa_current,
            self.press_pa_daily_max,
            self.press_pa_daily_min,
            self.press_trend,
        ) = press_stats

    def __str__(self) -> str:
        """Return a human readable description including current readings."""
        base = super().__str__()
        if self.temp_mk_current is not None:
            celsius = self.temp_mk_current * 1e-3 - 273.15
            base += f": {celsius:.1f}°C / {self.hum_current}% / {self.press_pa_current}Pa"
        return base


class RainPointGatewayHub(HomgarHubDevice):
    """RainPoint gateway hub used by newer hardware revisions."""

    MODEL_CODES: ClassVar[list[int]] = [273]
    FRIENDLY_DESC: ClassVar[str] = "RainPoint Gateway Hub"

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the gateway hub."""
        super().__init__(**kwargs)
        self.battery_level: int | None = None
        self.wifi_rssi: int | None = None
        self.connected: bool | None = None

    def get_device_status_ids(self) -> list[str]:
        """Return identifiers for gateway-specific status updates."""
        return ["connected", "state", "D01"]

    def set_device_status(self, api_obj: Mapping[str, Any]) -> None:
        """Handle gateway specific updates before delegating to the base class."""
        dev_id = api_obj.get("id")
        val = api_obj.get("value")
        if dev_id == "state" and isinstance(val, str):
            parts = [segment for segment in val.split(",") if segment]
            if parts:
                try:
                    self.battery_level = int(parts[0])
                except ValueError:
                    self.battery_level = None
            if len(parts) > 1:
                try:
                    self.wifi_rssi = int(parts[1])
                except ValueError:
                    self.wifi_rssi = None
        elif dev_id == "connected":
            self.connected = str(val) == "1"
        else:
            super().set_device_status(api_obj)


class RainPointSoilMoistureSensor(HomgarSubDevice):
    """RainPoint soil moisture sensor."""

    MODEL_CODES: ClassVar[list[int]] = [72]
    FRIENDLY_DESC: ClassVar[str] = "Soil Moisture Sensor"

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the soil sensor."""
        super().__init__(**kwargs)
        self.temp_mk_current: int | None = None
        self.moist_percent_current: int | None = None
        self.light_lux_current: float | None = None
        self.battery_state: str | None = None
        self.battery_level_raw: int | None = None
        self.signal_strength: int | None = None
        self.raw_status: str | None = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Parse the soil moisture payload into temperature, soil, and light readings."""
        if value.startswith(("10#", "11#")):
            decoded = decode_status_payload(value, model_code=72)
            vals = decoded.values
            self.status_fields.update(vals)
            if (temp_c := vals.get("temperature_c")) is not None:
                self.temp_mk_current = _celsius_to_mk(temp_c)
            if (moist := vals.get("humidity_pct")) is not None:
                self.moist_percent_current = int(moist)
            if (lux := vals.get("illuminance_lux")) is not None:
                self.light_lux_current = float(lux)
            if (battery_raw := vals.get("battery_state_raw")) is not None:
                self.battery_level_raw = int(battery_raw)
            if "battery_state" in vals:
                self.battery_state = vals["battery_state"]
            if (rssi := vals.get("signal_strength")) is not None:
                self.signal_strength = int(rssi)
            self.raw_status = value
            return

        temp_str, moist_str, light_str = value.split(",")
        self.temp_mk_current = _temp_to_mk(temp_str)
        self.moist_percent_current = int(moist_str)
        self.light_lux_current = int(light_str[2:]) * 0.1
        self.raw_status = value

    def __str__(self) -> str:
        """Return a human readable description including current readings."""
        base = super().__str__()
        if self.temp_mk_current is not None and self.moist_percent_current is not None:
            celsius = self.temp_mk_current * 1e-3 - 273.15
            base += f": {celsius:.1f}°C / {self.moist_percent_current}% / {self.light_lux_current:.1f}lx"
        return base


class RainPointRainSensor(HomgarSubDevice):
    """RainPoint rainfall sensor."""

    MODEL_CODES: ClassVar[list[int]] = [87]
    FRIENDLY_DESC: ClassVar[str] = "High Precision Rain Sensor"

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the rain sensor."""
        super().__init__(**kwargs)
        self.rainfall_mm_total: float | None = None
        self.rainfall_mm_hour: float | None = None
        self.rainfall_mm_daily: float | None = None
        self.rainfall_mm_7days: float | None = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Parse the rainfall payload into rolling accumulation metrics."""
        total, hour, daily, seven_day = _parse_stats_value(value[2:])
        if total is not None:
            self.rainfall_mm_total = total * 0.1
        if hour is not None:
            self.rainfall_mm_hour = hour * 0.1
        if daily is not None:
            self.rainfall_mm_daily = daily * 0.1
        if seven_day is not None:
            self.rainfall_mm_7days = seven_day * 0.1

    def __str__(self) -> str:
        """Return a human readable description including rainfall totals."""
        base = super().__str__()
        if self.rainfall_mm_total is not None:
            base += (
                f": {self.rainfall_mm_total}mm total / {self.rainfall_mm_hour}mm 1h / "
                f"{self.rainfall_mm_daily}mm 24h / {self.rainfall_mm_7days}mm 7days"
            )
        return base


class RainPointAirSensor(HomgarSubDevice):
    """RainPoint outdoor air sensor."""

    MODEL_CODES: ClassVar[list[int]] = [262]
    FRIENDLY_DESC: ClassVar[str] = "Outdoor Air Humidity Sensor"

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the air sensor."""
        super().__init__(**kwargs)
        self.temp_mk_current: int | None = None
        self.temp_mk_daily_max: int | None = None
        self.temp_mk_daily_min: int | None = None
        self.temp_trend: int | None = None
        self.hum_current: int | None = None
        self.hum_daily_max: int | None = None
        self.hum_daily_min: int | None = None
        self.hum_trend: int | None = None
        self.battery_state: str | None = None
        self.battery_level_raw: int | None = None
        self.raw_status: str | None = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Parse the air sensor payload into temperature and humidity statistics."""
        if value.startswith(("10#", "11#")):
            decoded = decode_status_payload(value, model_code=262)
            vals = decoded.values
            self.status_fields.update(vals)
            if (temp_c := vals.get("temperature_c")) is not None:
                self.temp_mk_current = _celsius_to_mk(temp_c)
            if (humidity := vals.get("humidity_pct")) is not None:
                self.hum_current = int(humidity)
            if (battery_raw := vals.get("battery_state_raw")) is not None:
                self.battery_level_raw = int(battery_raw)
            if "battery_state" in vals:
                self.battery_state = vals["battery_state"]
            self.raw_status = value
            return

        temp_str, hum_str, *_ = value.split(",")
        temp_stats = _parse_stats_value(temp_str)
        converted_temp = tuple(_temp_to_mk(stat) if stat is not None else None for stat in temp_stats)
        (
            self.temp_mk_current,
            self.temp_mk_daily_max,
            self.temp_mk_daily_min,
            self.temp_trend,
        ) = converted_temp
        self.hum_current, self.hum_daily_max, self.hum_daily_min, self.hum_trend = _parse_stats_value(hum_str)
        self.raw_status = value

    def __str__(self) -> str:
        """Return a human readable description including temperature and humidity."""
        base = super().__str__()
        if self.temp_mk_current is not None:
            celsius = self.temp_mk_current * 1e-3 - 273.15
            base += f": {celsius:.1f}°C / {self.hum_current}%"
        return base


class RainPointPoolSensor(HomgarSubDevice):
    """RainPoint pool temperature sensor."""

    MODEL_CODES: ClassVar[list[int]] = [268]
    FRIENDLY_DESC: ClassVar[str] = "Pool Temperature Sensor"

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the pool sensor."""
        super().__init__(**kwargs)
        self.water_temp_c: float | None = None
        self.temp_mk_current: int | None = None
        self.water_temp_f: float | None = None
        self.battery_level: int | None = None
        self.raw_status: str | None = None
        self.trend_raw: int | None = None
        self.battery_state: str | None = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Decode the raw payload using the product model definitions."""
        if value.startswith(("10#", "11#")):
            decoded = decode_status_payload(value, model_code=268)
            vals = decoded.values
            self.status_fields.update(vals)
            if (temp_c := vals.get("temperature_c")) is not None:
                self.water_temp_c = temp_c
                self.temp_mk_current = _celsius_to_mk(temp_c)
            if (temp_f := vals.get("temperature_f")) is not None:
                self.water_temp_f = temp_f
            if (battery_raw := vals.get("battery_state_raw")) is not None:
                self.battery_level = int(battery_raw)
            if "battery_state" in vals:
                self.battery_state = vals["battery_state"]
            if (trend := vals.get("trend_raw")) is not None:
                self.trend_raw = int(trend)
            self.raw_status = value
            return

        self.raw_status = value


class RainPoint2ZoneTimer(HomgarSubDevice):
    """RainPoint two-zone water timer."""

    MODEL_CODES: ClassVar[list[int]] = [261]
    FRIENDLY_DESC: ClassVar[str] = "2-Zone Water Timer"

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the timer."""
        super().__init__(**kwargs)
        self.zone_status: str | None = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Store the raw zone status for further analysis.

        Observed example value: ``0,9,0,0,0,0|0,1291,0,0,0,0``.
        """

        self.zone_status = value


MODEL_CODE_MAPPING: dict[int, type[HomgarDevice]] = {
    code: device_class
    for device_class in (
        RainPointDisplayHub,
        RainPointGatewayHub,
        RainPointSoilMoistureSensor,
        RainPointRainSensor,
        RainPointAirSensor,
        RainPointPoolSensor,
        RainPoint2ZoneTimer,
    )
    for code in device_class.MODEL_CODES
}
