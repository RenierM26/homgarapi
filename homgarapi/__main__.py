"""Command line entry point for the HomGar API demo."""

from argparse import ArgumentParser
from collections.abc import Mapping, MutableMapping
import logging
from pathlib import Path
import pickle
from typing import Any

from platformdirs import user_cache_dir
import yaml

from .api import HomgarApi
from .logutil import TRACE, get_logger

logging.addLevelName(TRACE, "TRACE")
logger = get_logger(__file__)


def demo(api: HomgarApi, config: Mapping[str, str]) -> None:
    """Run a simple demonstration against the HomGar API.

    :param api: Instantiated `HomgarApi` client.
    :param config: Mapping containing at least ``email`` and ``password`` keys.
    """
    api.ensure_logged_in(config["email"], config["password"])
    for home in api.get_homes():
        logger.info("Home (%s) %s", home.hid, home.name)

        for hub in api.get_devices_for_hid(home.hid):
            logger.info("  Hub %s", hub)
            api.get_device_status(hub)
            for subdevice in hub.subdevices:
                logger.info("    Subdevice %s", subdevice)


def main() -> None:
    """Parse CLI arguments and run the demo.

    :raises TypeError: If the configuration file does not contain a mapping.
    """
    argparse = ArgumentParser(
        description="Demo of HomGar API client library",
        prog="homgarapi",
    )
    argparse.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose (DEBUG) mode"
    )
    argparse.add_argument(
        "-vv", "--very-verbose", action="store_true", help="Very verbose (TRACE) mode"
    )
    argparse.add_argument(
        "-c",
        "--cache",
        type=Path,
        help="Cache file to use. Should be writable, will be created if it does not exist.",
    )
    argparse.add_argument(
        "--email",
        help="HomGar account email address (overrides value in configuration file)",
    )
    argparse.add_argument(
        "--password",
        help="HomGar account password (overrides value in configuration file)",
    )
    argparse.add_argument(
        "--unknown-output",
        type=Path,
        help="Optional path to write unsupported device report (YAML)",
    )
    argparse.add_argument(
        "config",
        nargs="?",
        type=Path,
        help="Optional YAML file containing authentication details",
    )
    args = argparse.parse_args()

    logging.basicConfig(
        level=TRACE
        if args.very_verbose
        else logging.DEBUG
        if args.verbose
        else logging.INFO
    )

    cache_file: Path = args.cache or (
        Path(user_cache_dir("homgarapi", ensure_exists=True)) / "cache.pickle"
    )
    config_file: Path | None = args.config

    cache: MutableMapping[str, Any] = {}
    try:
        with cache_file.open("rb") as cache_handle:
            cache = pickle.load(cache_handle)
    except OSError:
        logger.info("Could not load cache, starting fresh")

    config_mapping: dict[str, str] = {}
    if config_file is not None:
        with config_file.open("rb") as config_handle:
            try:
                config = yaml.safe_load(config_handle)
            except yaml.YAMLError as exc:
                raise ValueError(
                    f"Failed parsing configuration file {config_file}"
                ) from exc
        if not isinstance(config, Mapping):
            msg = f"Configuration file {config_file} must contain a mapping"
            raise TypeError(msg)
        config_mapping.update({str(key): str(value) for key, value in config.items()})

    if args.email is not None:
        config_mapping["email"] = args.email
    if args.password is not None:
        config_mapping["password"] = args.password

    required_keys = {"email", "password"}
    missing = required_keys - set(config_mapping)
    if missing:
        msg = (
            "Authentication details must include both email and password. "
            f"Missing: {', '.join(sorted(missing))}"
        )
        raise ValueError(msg)

    try:
        api = HomgarApi(cache)
        demo(api, config_mapping)
        unknown_devices_raw = api.get_unknown_devices()
        if unknown_devices_raw:
            unknown_devices: list[dict[str, Any]] = []
            for device in unknown_devices_raw:
                enriched = dict(device)
                if status_values := enriched.pop("status_values", None):
                    enriched["status_payloads"] = status_values
                unknown_devices.append(enriched)
            output_path = args.unknown_output or cache_file.with_name(
                "unknown_devices.yaml"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as output_handle:
                yaml.safe_dump(
                    {"unknown_devices": unknown_devices},
                    output_handle,
                    sort_keys=False,
                    allow_unicode=True,
                )
            logger.warning(
                "Unsupported devices detected. Details written to %s. "
                "Please share this file when requesting support for new hardware.",
                output_path,
            )
    finally:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with cache_file.open("wb") as cache_handle:
            pickle.dump(cache, cache_handle)


if __name__ == "__main__":
    main()
