"""Helpers for decoding HomGar/Tuya raw device status payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homgarapi.api import load_product_models


@dataclass(frozen=True)
class DecodedStatus:
    """Container with decoded datapoint values."""

    values: dict[str, Any]
    raw_items: list[tuple[int, bytes]]


_PRODUCT_MODELS = load_product_models()
_DP_SPECS_BY_MODEL: dict[int, dict[int, Mapping[str, Any]]] = {
    model_code: {
        int(entry["dpCode"]): entry["specs"] for entry in model.get("dp", [])
    }
    for model_code, model in _PRODUCT_MODELS.items()
}


def _strip_prefix(value: str) -> tuple[bytes, bool]:
    """Strip the leading header (`10#…`) and return bytes + z3 flag."""
    if not value:
        return b"", False

    z3 = False
    payload_hex = value
    if "#" in value:
        hdr, payload_hex = value.split("#", 1)
        if len(hdr) >= 2:
            z3 = hdr[1] == "1"
    payload_hex = payload_hex.strip()
    if len(payload_hex) % 2 == 1:
        payload_hex = "0" + payload_hex
    return bytes.fromhex(payload_hex), z3


def _iter_tlv_items(data: bytes, z3: bool) -> list[tuple[int, bytes]]:
    """Yield `(dp_code, raw_bytes)` pairs from the encoded payload."""
    items: list[tuple[int, bytes]] = []
    idx = 0

    if z3 and idx < len(data):
        idx += 1  # drop leading dp id for z3 streams

    while idx < len(data):
        header = data[idx]
        idx += 1

        if (header >> 7) & 1 == 0:
            dp_code = (header >> 4) & 0x07
            items.append((dp_code, b""))
            continue

        code_bits = (header >> 2) & 0x1F
        length = (header & 0x03) + 1

        if code_bits <= 30:
            dp_code = code_bits + 8
        else:
            if idx >= len(data):
                break
            dp_code = data[idx]
            idx += 1

        if idx + length > len(data):
            break

        value = data[idx : idx + length]
        idx += length
        items.append((dp_code, value))

    return items


def _decode_numeric(value: bytes, specs: Mapping[str, Any]) -> float | int:
    """Decode Tuya numeric value respecting decimal and signedness."""
    decimal_raw = specs.get("decimal")
    decimal: int
    if isinstance(decimal_raw, int):
        decimal = decimal_raw
    elif isinstance(decimal_raw, str) and decimal_raw.isdigit():
        decimal = int(decimal_raw)
    else:
        decimal = 0

    data_type_sub = specs.get("dataTypeSub")
    signed = data_type_sub == 6 or data_type_sub == "6"

    raw: int = int.from_bytes(value, byteorder="little", signed=signed)
    if decimal:
        result: float = float(raw) / (10 ** decimal)
        return result
    return raw


def decode_status_payload(
    value: str,
    *,
    model_code: int,
    prefer_celsius: bool = True,
) -> DecodedStatus:
    """Decode a HomGar raw status payload."""
    data, z3 = _strip_prefix(value)
    items = _iter_tlv_items(data, z3)
    specs_map = _DP_SPECS_BY_MODEL.get(model_code, {})

    decoded: dict[str, Any] = {}

    for dp_code, raw in items:
        specs = specs_map.get(dp_code)
        identity = specs.get("identity") if specs else None

        if not specs or not identity:
            decoded[f"dp_{dp_code}"] = raw
            continue

        data_type = specs.get("dataType")

        processed: Any
        if data_type == 1 and raw:
            processed = _decode_numeric(raw, specs)
        elif data_type == 2 and raw:
            processed = int.from_bytes(raw, byteorder="little", signed=False)
        else:
            processed = raw

        if identity == "STA_TEM":
            temp_f = float(processed)
            decoded["temperature_f"] = temp_f
            if prefer_celsius:
                decoded["temperature_c"] = round((temp_f - 32.0) * 5.0 / 9.0, 1)
            else:
                decoded["temperature_c"] = temp_f
        elif identity == "STA_RH":
            decoded["humidity_pct"] = processed
        elif identity == "STA_ILLUMINANCE":
            decoded["illuminance_lux"] = processed
        elif identity == "STA_BAT":
            decoded["battery_state_raw"] = processed
            decoded["battery_state"] = {
                1: "normal",
                2: "low",
                3: "lack",
            }.get(processed, processed)
        elif identity == "STA_RSSI":
            decoded["signal_strength"] = processed
        elif identity == "STA_TREND":
            decoded["trend_raw"] = processed
        else:
            decoded[identity] = processed

    return DecodedStatus(values=decoded, raw_items=items)
