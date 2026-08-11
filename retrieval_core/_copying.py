"""Safe nested copying for candidate metadata and diagnostics."""

from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from numbers import Number
from pathlib import PurePath
from types import MappingProxyType
from typing import Any
from uuid import UUID


def deep_copy_value(value: Any, memo: dict[int, Any] | None = None) -> Any:
    """Copy common nested metadata values, including mapping proxies."""

    if memo is None:
        memo = {}
    value_id = id(value)
    if value_id in memo:
        return memo[value_id]

    if isinstance(value, MappingProxyType):
        copied_values = {}
        memo[value_id] = copied_values
        copied_values.update(
            (deep_copy_value(key, memo), deep_copy_value(item, memo))
            for key, item in value.items()
        )
        copied_proxy = MappingProxyType(copied_values)
        memo[value_id] = copied_proxy
        return copied_proxy
    if isinstance(value, Mapping):
        copied_mapping = {}
        memo[value_id] = copied_mapping
        copied_mapping.update(
            (deep_copy_value(key, memo), deep_copy_value(item, memo))
            for key, item in value.items()
        )
        return copied_mapping
    if isinstance(value, list):
        copied_list = []
        memo[value_id] = copied_list
        copied_list.extend(deep_copy_value(item, memo) for item in value)
        return copied_list
    if isinstance(value, tuple):
        copied_tuple = tuple(deep_copy_value(item, memo) for item in value)
        memo[value_id] = copied_tuple
        return copied_tuple
    if isinstance(value, set):
        copied_set = {deep_copy_value(item, memo) for item in value}
        memo[value_id] = copied_set
        return copied_set
    if isinstance(value, frozenset):
        copied_frozen_set = frozenset(deep_copy_value(item, memo) for item in value)
        memo[value_id] = copied_frozen_set
        return copied_frozen_set

    try:
        copied_value = deepcopy(value, memo)
    except Exception:
        copied_value = value
    memo[value_id] = copied_value
    return copied_value


def deep_copy_mapping(mapping: Mapping) -> dict:
    """Return a mutable top-level dictionary with isolated nested values."""

    copied = deep_copy_value(mapping)
    return dict(copied)


_IMMUTABLE_SCALARS = (
    str,
    bytes,
    Number,
    Decimal,
    Enum,
    date,
    datetime,
    time,
    timedelta,
    PurePath,
    UUID,
)


def deep_freeze_value(
    value: Any,
    memo: dict[int, Any] | None = None,
    active: set[int] | None = None,
) -> Any:
    """Recursively isolate and freeze common JSON-like container values."""

    if value is None or isinstance(value, _IMMUTABLE_SCALARS):
        return value
    if memo is None:
        memo = {}
    if active is None:
        active = set()
    value_id = id(value)
    if value_id in memo:
        return memo[value_id]
    if value_id in active:
        raise ValueError("metadata cycle cannot be represented immutably")

    to_list = getattr(value, "tolist", None)
    if hasattr(value, "shape") and callable(to_list):
        active.add(value_id)
        try:
            frozen = deep_freeze_value(to_list(), memo, active)
        except (TypeError, ValueError):
            raise
        except Exception as error:
            raise TypeError("array-like value could not be made immutable") from error
        finally:
            active.remove(value_id)
        memo[value_id] = frozen
        return frozen

    active.add(value_id)
    if isinstance(value, Mapping):
        frozen = MappingProxyType(
            {
                deep_freeze_value(key, memo, active): deep_freeze_value(
                    item, memo, active
                )
                for key, item in value.items()
            }
        )
    elif isinstance(value, (list, tuple)):
        frozen = tuple(deep_freeze_value(item, memo, active) for item in value)
    elif isinstance(value, (set, frozenset)):
        frozen = frozenset(deep_freeze_value(item, memo, active) for item in value)
    else:
        active.remove(value_id)
        raise TypeError(
            f"value of type {type(value).__name__} cannot be made immutable"
        )
    active.remove(value_id)
    memo[value_id] = frozen
    return frozen


def deep_freeze_mapping(mapping: Mapping) -> Mapping:
    """Return an isolated, recursively immutable mapping."""

    frozen = deep_freeze_value(mapping)
    if not isinstance(frozen, MappingProxyType):
        raise TypeError("mapping must be a mapping")
    return frozen
