"""Standalone opt-in demo; production status lives in `hermes jev status`."""

import argparse


def main():
    parser = argparse.ArgumentParser(description="Jev decision demo (no tool execution)")
    parser.add_argument("command", choices=["demo"])
    parser.parse_args()
    from .demo import main as demo

    return demo()


if __name__ == "__main__":
    raise SystemExit(main())
