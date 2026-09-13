"""Closed, non-executable wire encoding for Historian's immutable domain types."""

from dataclasses import fields, is_dataclass
from enum import Enum
from historian import types, gold, resolution

CLASSES = {
    name: cls
    for module in (types, gold, resolution)
    for name, cls in vars(module).items()
    if isinstance(cls, type) and (is_dataclass(cls) or issubclass(cls, Enum))
}


def encode(value):
    if isinstance(value, Enum):
        return {"enum": type(value).__name__, "value": value.value}
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            "fields": {f.name: encode(getattr(value, f.name)) for f in fields(value)},
        }
    if isinstance(value, (tuple, list)):
        return [encode(v) for v in value]
    if value is None or type(value) in (str, int, bool, float):
        return value
    raise ValueError("unsupported wire value")


def decode(value):
    if isinstance(value, list):
        return tuple(decode(v) for v in value)
    if isinstance(value, dict):
        if set(value) == {"enum", "value"}:
            cls = CLASSES[value["enum"]]
            if not issubclass(cls, Enum):
                raise ValueError("not an enum")
            return cls(value["value"])
        if set(value) == {"type", "fields"}:
            cls = CLASSES[value["type"]]
            if not is_dataclass(cls):
                raise ValueError("not a domain object")
            return cls(
                **{
                    k: decode(v)
                    for k, v in value["fields"].items()
                    if not (value["type"] == "FrameTaxonomy" and k == "id")
                }
            )
        raise ValueError("invalid wire shape")
    if value is None or type(value) in (str, int, bool, float):
        return value
    raise ValueError("unsupported wire value")
