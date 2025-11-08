#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""Utility script to initialise the 7.3"F panel and clear the frame."""
import logging
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
picdir = os.path.join(ROOT_DIR, "pic")
libdir = os.path.join(ROOT_DIR, "lib")
if os.path.exists(libdir):
    sys.path.append(libdir)

from waveshare_epd import epd7in3f  # type: ignore  # noqa: E402


def parse_args():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--color",
        default="white",
        choices=(
            "white",
            "black",
            "red",
            "green",
            "blue",
            "yellow",
            "orange",
        ),
        help="Fill colour used for Clear() (default: white)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def resolve_color(epd, name: str) -> int:
    return {
        "white": epd.WHITE,
        "black": epd.BLACK,
        "red": epd.RED,
        "green": epd.GREEN,
        "blue": epd.BLUE,
        "yellow": epd.YELLOW,
        "orange": epd.ORANGE,
    }[name]


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    try:
        logging.info("Initialising epd7in3f...")
        epd = epd7in3f.EPD()
        epd.init()

        fill = resolve_color(epd, args.color)
        logging.info("Clearing display with %s", args.color)
        epd.Clear(fill)

        logging.info("Putting display to sleep")
        epd.sleep()
    except KeyboardInterrupt:
        logging.info("ctrl + c")
        epd7in3f.epdconfig.module_exit(cleanup=True)
        return 1
    except Exception as exc:  # pragma: no cover - hardware failure path
        logging.exception("Failed to clear display: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
