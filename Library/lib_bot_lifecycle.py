# coding: utf-8
"""main.py / addon_main.py 공용 부트·종료 헬퍼 + tasks.loop 안전화."""
from __future__ import annotations

import asyncio
import inspect
import os
import signal
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, TypeVar

import discord
from discord.ext import tasks as discord_tasks

from DB import db_dailyInform, db_exp, db_recruit, db_setting, db_verify

LogTag = str | Callable[[discord.Bot], str]
ReloadCallback = Callable[[], None]
CleanupCallback = Callable[[], None]
AsyncCleanupCallback = Callable[[], Awaitable[None]]
_T = TypeVar("_T")
IsolatedWork = Callable[[], Awaitable[_T]] | Awaitable[_T]


def write_pid_file(path: Path) -> None:
    try:
        path.write_text(str(os.getpid()), encoding="utf-8")
    except Exception as exc:
        print(f"[pid] write failed: {exc}")


def cleanup_pid_file(path: Path) -> None:
    try:
        if path.exists():
            current = path.read_text(encoding="utf-8").strip()
            if current == str(os.getpid()):
                path.unlink()
    except Exception as exc:
        print(f"[pid] cleanup failed: {exc}")


def _resolve_log_tag(target_bot: discord.Bot, log_tag: LogTag) -> str:
    if callable(log_tag):
        return log_tag(target_bot)
    return log_tag


def cancel_running_cog_tasks(
    target_bot: discord.Bot,
    *,
    log_tag: LogTag = "[shutdown]",
) -> None:
    tag = _resolve_log_tag(target_bot, log_tag)
    for cog in list(target_bot.cogs.values()):
        for name in dir(cog):
            member = getattr(cog, name, None)
            if isinstance(member, discord_tasks.Loop) and member.is_running():
                try:
                    member.cancel()
                except Exception as exc:
                    print(f"{tag} task cancel failed ({name}): {exc}")


def unload_extensions(
    target_bot: discord.Bot,
    *,
    log_tag: LogTag = "[shutdown]",
) -> None:
    tag = _resolve_log_tag(target_bot, log_tag)
    for ext_name in list(target_bot.extensions):
        try:
            target_bot.unload_extension(ext_name)
        except Exception as exc:
            print(f"{tag} extension unload failed ({ext_name}): {exc}")


def register_async_shutdown(
    target_bot: discord.Bot,
    callback: AsyncCleanupCallback,
) -> None:
    callbacks = getattr(target_bot, "_async_shutdown_callbacks", None)
    if not isinstance(callbacks, list):
        callbacks = []
        target_bot._async_shutdown_callbacks = callbacks
    if callback not in callbacks:
        callbacks.append(callback)


def unregister_async_shutdown(
    target_bot: discord.Bot,
    callback: AsyncCleanupCallback,
) -> None:
    callbacks = getattr(target_bot, "_async_shutdown_callbacks", None)
    if not isinstance(callbacks, list):
        return
    try:
        callbacks.remove(callback)
    except ValueError:
        pass


async def run_async_shutdown_callbacks(
    target_bot: discord.Bot,
    *,
    log_tag: LogTag = "[shutdown]",
) -> None:
    callbacks = getattr(target_bot, "_async_shutdown_callbacks", None)
    if not isinstance(callbacks, list) or not callbacks:
        return

    target_bot._async_shutdown_callbacks = []
    tag = _resolve_log_tag(target_bot, log_tag)
    for callback in reversed(callbacks):
        try:
            await callback()
        except asyncio.CancelledError:
            name = getattr(callback, "__qualname__", repr(callback))
            print(f"{tag} async cleanup cancelled ({name})")
        except Exception as exc:
            name = getattr(callback, "__qualname__", repr(callback))
            print(f"{tag} async cleanup failed ({name}): {exc}")


def install_shutdown_hook(
    target_bot: discord.Bot,
    *,
    log_tag: LogTag = "[shutdown]",
    shutting_down_text: str = "종료 중...",
    done_text: str = "종료 완료",
    after_close: CleanupCallback | None = None,
) -> None:
    if getattr(target_bot, "_shutdown_hook_installed", False):
        return

    original_close = target_bot.close

    async def close() -> None:
        if getattr(target_bot, "_shutdown_in_progress", False):
            await original_close()
            return

        target_bot._shutdown_in_progress = True
        tag = _resolve_log_tag(target_bot, log_tag)
        print(f"{tag} {shutting_down_text}")
        await run_async_shutdown_callbacks(target_bot, log_tag=tag)
        cancel_running_cog_tasks(target_bot, log_tag=tag)
        unload_extensions(target_bot, log_tag=tag)
        if not target_bot.is_closed():
            await original_close()
        if after_close is not None:
            after_close()
        print(f"{tag} {done_text}")

    target_bot.close = close
    target_bot._shutdown_hook_installed = True


def ensure_core_db_schemas() -> None:
    """Core DB 스키마 primary ensure (부트 전용).

    setting / exp / verify / recruit / dailyInform.
    Addon DB는 addon_main._ensure_db_schemas() 목록에서만 추가.
    """
    db_setting.ensure_schema()
    db_exp.ensure_schema()
    db_verify.ensure_schema()
    db_recruit.ensure_schema()
    db_dailyInform.ensure_schema()


def install_sigusr1_reload(
    on_reload: ReloadCallback,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
    bots: Sequence[discord.Bot] | None = None,
) -> None:
    """SIGUSR1 시 on_reload를 이벤트 루프에 thread-safe로 스케줄한다.

    on_reload는 성공 로그까지 직접 출력하고, 예외는 여기서 '[tone] reload failed'로 잡는다.
    """

    def _handle_reload(_signum, _frame):
        def _do_reload():
            try:
                on_reload()
            except Exception as exc:
                print(f"[tone] reload failed: {exc}")

        active_loop = loop
        if active_loop is None and bots:
            for bot in bots:
                if not bot.is_closed() and bot.loop is not None:
                    active_loop = bot.loop
                    break

        if active_loop is not None and active_loop.is_running():
            active_loop.call_soon_threadsafe(_do_reload)
        else:
            _do_reload()

    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, _handle_reload)


async def run_isolated(message_prefix: str, work: IsolatedWork[_T]) -> _T | None:
    """await work; 예외 시 '{message_prefix}: {exc}' 로그만 남기고 루프/호출부를 계속한다.

    work는 awaitable이거나 인자 없는 async callable.
    성공 시 결과를 반환하고, 예외 시 None을 반환한다.
    """
    try:
        if inspect.isawaitable(work):
            return await work
        return await work()
    except Exception as exc:
        print(f"{message_prefix}: {exc}")
        return None


def log_loop_error(label: str, error: BaseException) -> None:
    """@tasks.Loop.error 핸들러용 thin wrapper. '{label} loop error: {error}' 출력."""
    print(f"{label} loop error: {error}")


def ensure_loop_running(loop: discord_tasks.Loop) -> None:
    """on_ready 가드: is_running()이 아니면 restart()."""
    if not loop.is_running():
        loop.restart()
