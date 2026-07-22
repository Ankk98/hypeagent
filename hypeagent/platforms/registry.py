"""Platform connector loading by built-in name or file path."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from pathlib import Path

from hypeagent.platforms.base import PlatformConnector

BUILTIN_CONNECTORS: dict[str, str] = {
    "reddit": "hypeagent.platforms.reddit:RedditConnector",
}


class ConnectorLoadError(Exception):
    """Raised when a connector cannot be imported or resolved."""


def _import_from_path(module_path: str) -> type[PlatformConnector]:
    if ":" in module_path:
        module_name, class_name = module_path.rsplit(":", 1)
        module = importlib.import_module(module_name)
        connector_cls = getattr(module, class_name, None)
        if connector_cls is None:
            msg = f"Connector class {class_name!r} not found in {module_name}"
            raise ConnectorLoadError(msg)
        if not inspect.isclass(connector_cls) or not issubclass(connector_cls, PlatformConnector):
            msg = f"{class_name!r} is not a PlatformConnector subclass"
            raise ConnectorLoadError(msg)
        return connector_cls

    path = Path(module_path).resolve()
    if not path.is_file():
        msg = f"Connector file not found: {path}"
        raise ConnectorLoadError(msg)

    module_name = f"hypeagent_user_connector_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        msg = f"Cannot load connector module from {path}"
        raise ConnectorLoadError(msg)

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    stem_camel = "".join(part.capitalize() for part in path.stem.split("_"))
    preferred_name = f"{stem_camel}Connector"
    preferred = getattr(module, preferred_name, None)
    if (
        preferred is not None
        and inspect.isclass(preferred)
        and issubclass(preferred, PlatformConnector)
    ):
        return preferred

    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, PlatformConnector) and obj is not PlatformConnector:
            return obj

    msg = (
        f"No PlatformConnector subclass found in {path}; "
        f"expected {preferred_name} or any PlatformConnector subclass"
    )
    raise ConnectorLoadError(msg)


def load_connector(name_or_path: str) -> type[PlatformConnector]:
    """Load a built-in connector by name or a user module from a file path."""
    if name_or_path in BUILTIN_CONNECTORS:
        return _import_from_path(BUILTIN_CONNECTORS[name_or_path])

    if name_or_path.endswith(".py") or "/" in name_or_path or name_or_path.startswith("."):
        return _import_from_path(name_or_path)

    if ":" in name_or_path:
        return _import_from_path(name_or_path)

    msg = f"Unknown connector {name_or_path!r}; built-ins: {', '.join(sorted(BUILTIN_CONNECTORS))}"
    raise ConnectorLoadError(msg)
