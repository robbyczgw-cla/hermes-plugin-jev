"""Hermes plugin registration. Importing this module does not call TypeSafe."""

import json
import logging
import os

from .config import Config
from .hooks import Router

logger = logging.getLogger(__name__)


def register(ctx):
    try:
        config = Config.from_context(ctx)
    except Exception:
        logger.warning("Invalid TypeSafe settings; plugin disabled")
        config = Config(enabled=False)
    key = os.environ.get("TYPESAFE_API_KEY", "")
    engine = None
    if config.enabled and key:
        try:
            from .client import TypeSafeEngine

            engine = TypeSafeEngine(key, config)
        except Exception as exc:
            logger.warning(
                "TypeSafe unavailable (%s); normal Hermes behavior retained", type(exc).__name__
            )
    elif config.enabled:
        logger.info("TypeSafe API key not configured; plugin is inactive")
    runtime = Router(config, engine, api_key=key)
    if engine is not None:
        engine.telemetry = runtime.telemetry

    def approval_safe():
        try:
            from hermes_cli.plugins import get_plugin_manager

            callbacks = get_plugin_manager().iter_hook_callbacks("pre_tool_call")
            return bool(callbacks) and callbacks[-1] == runtime.pre_tool_call
        except Exception:
            return False

    runtime.approval_order_safe = approval_safe
    for hook in (
        "pre_llm_call",
        "pre_tool_call",
        "post_tool_call",
        "pre_verify",
        "post_llm_call",
        "on_session_end",
    ):
        ctx.register_hook(hook, getattr(runtime, hook))
    ctx.register_middleware("llm_request", runtime.llm_request)
    ctx.register_middleware("tool_request", runtime.tool_request)

    def setup(parser):
        parser.add_argument("action", choices=["status"], nargs="?", default="status")

    def status(args):
        print(json.dumps(runtime.status(), indent=2))

    ctx.register_cli_command("jev", "Jev plugin status", setup, status)
    return runtime
