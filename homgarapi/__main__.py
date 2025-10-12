"""Command line entry point for the HomGar API demo."""

from argparse import ArgumentParser
from collections.abc import Mapping, MutableMapping
import logging
from pathlib import Path
import pickle
from typing import Any

from homgarapi.api import HomgarApi
from homgarapi.logutil import TRACE, get_logger
from platformdirs import user_cache_dir
import yaml

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
    argparse.add_argument("-v", "--verbose", action="store_true", help="Verbose (DEBUG) mode")
    argparse.add_argument("-vv", "--very-verbose", action="store_true", help="Very verbose (TRACE) mode")
    argparse.add_argument(
        "-c",
        "--cache",
        type=Path,
        help="Cache file to use. Should be writable, will be created if it does not exist.",
    )
    argparse.add_argument(
        "config",
        type=Path,
        help="Yaml file containing email and password to use to log in",
    )
    args = argparse.parse_args()

    logging.basicConfig(level=TRACE if args.very_verbose else logging.DEBUG if args.verbose else logging.INFO)

    cache_file: Path = args.cache or (Path(user_cache_dir("homgarapi", ensure_exists=True)) / "cache.pickle")
    config_file: Path = args.config

    cache: MutableMapping[str, Any] = {}
    try:
        with cache_file.open("rb") as cache_handle:
            cache = pickle.load(cache_handle)
    except OSError:
        logger.info("Could not load cache, starting fresh")

    with config_file.open("rb") as config_handle:
        config = yaml.unsafe_load(config_handle)
    if not isinstance(config, Mapping):
        msg = f"Configuration file {config_file} must contain a mapping"
        raise TypeError(msg)
    config_mapping = {str(key): str(value) for key, value in config.items()}

    try:
        api = HomgarApi(cache)
        demo(api, config_mapping)
    finally:
        with cache_file.open("wb") as cache_handle:
            pickle.dump(cache, cache_handle)


if __name__ == "__main__":
    main()
