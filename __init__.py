"""Directory-plugin entry point for the Hermes loader."""


def register(ctx):
    from .jev_router import register as register_plugin

    return register_plugin(ctx)
