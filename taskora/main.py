from __future__ import annotations

import argparse

from .ui import run_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="taskora")
    parser.add_argument("--data-dir", help="Override Taskora data directory.")
    args = parser.parse_args()
    run_app(args.data_dir)


if __name__ == "__main__":
    main()
