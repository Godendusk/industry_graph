"""Safe nested copying for candidate metadata and diagnostics."""

from collections.abc import Mapping
from copy import deepcopy
from types import MappingProxyType
from typing import Any


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
