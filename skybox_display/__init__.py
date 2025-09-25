from importlib import metadata

APP_NAME = "skybox-display"

try:
    from ._version import __version__
except ImportError:
    try:
        __version__ = metadata.version(APP_NAME)
    except metadata.PackageNotFoundError:
        __version__ = "0"

USER_AGENT = f"{APP_NAME}/{__version__}"
