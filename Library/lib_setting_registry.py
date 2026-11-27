# coding: utf-8
"""Extra /설정 categories registered by addon modules at import time."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SettingItem:
    category: str
    key: str
    kind: str
    clearable: bool = False
    get: Callable[[int], Any] | None = None
    set: Callable[[int, Any], None] | None = None
    format: Callable[..., str] | None = None
    save_message: Callable[..., str] | None = None


_items: dict[str, SettingItem] = {}
_category_order: list[str] = []
_category_access: dict[str, Callable[[Any, int], bool]] = {}


def register_category(
    category: str, *, is_available: Callable[[Any, int], bool] | None = None,
) -> None:
    if category not in _category_order:
        _category_order.append(category)
    if is_available is not None:
        _category_access[category] = is_available


def register_item(item: SettingItem) -> None:
    register_category(item.category)
    _items[item.key] = item


def registered_categories() -> tuple[str, ...]:
    return tuple(_category_order)


def visible_categories(bot, guild_id: int) -> tuple[str, ...]:
    return tuple(
        category for category in _category_order
        if category not in _category_access or _category_access[category](bot, guild_id)
    )


def items_for_category(category: str) -> tuple[str, ...]:
    return tuple(item.key for item in _items.values() if item.category == category)


def get_item(key: str) -> SettingItem | None:
    return _items.get(key)


def clear() -> None:
    _items.clear()
    _category_order.clear()
    _category_access.clear()
