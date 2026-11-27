import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import discord

from Cogs.c_expFE import expFE, _ExpRankingView
from DB import db_exp
from Library import lib_cog_scope, lib_slash_guild_sync, lib_slash_tone_sync
from tone.default import LANG_PACK


@pytest.fixture(autouse=True)
def public_policy():
    lib_cog_scope.install(lib_cog_scope.PUBLIC_POLICY)
    yield
    lib_cog_scope.install(lib_cog_scope.PUBLIC_POLICY)


def make_cog():
    cog = expFE.__new__(expFE)
    cog.bot = SimpleNamespace()
    cog._t = lambda guild, key, **kwargs: LANG_PACK[key].format(**kwargs)
    return cog


@pytest.mark.parametrize('kind', [0, 1, 2])
def test_public_ranking_queries_selected_period_and_paginates(monkeypatch, kind):
    async def check():
        cog = make_cog()
        rows = [(index, 100, 5) for index in range(cog._RANK_PER_PAGE + 1)]
        today = Mock(return_value=rows)
        yesterday = Mock(return_value=rows)
        monkeypatch.setattr(db_exp, 'getAllData', today)
        monkeypatch.setattr(db_exp, 'getYesterdayData', yesterday)
        cog._build_ranking_content = AsyncMock(return_value='ranking')
        message = SimpleNamespace(edit_original_response=AsyncMock(), original_response=AsyncMock())
        ctx = SimpleNamespace(guild=SimpleNamespace(id=7), author=SimpleNamespace(id=9), respond=AsyncMock(return_value=message))
        await expFE.exp_rank.callback(cog, ctx, kind, 99)
        selected = yesterday if kind == 2 else today
        selected.assert_called_once_with(7, kind != 0)
        (today if kind == 2 else yesterday).assert_not_called()
        assert cog._build_ranking_content.call_args.kwargs['page'] == 2
        view = message.edit_original_response.call_args.kwargs['view']
        assert isinstance(view, _ExpRankingView)
        assert view.next_button.disabled
        assert not view.prev_button.disabled
        intruder = SimpleNamespace(user=SimpleNamespace(id=8), response=SimpleNamespace(send_message=AsyncMock()))
        assert not await view._check_requester(intruder)
        owner = SimpleNamespace(user=ctx.author, response=SimpleNamespace(defer=AsyncMock()), edit_original_response=AsyncMock())
        await view._goto(owner, 1)
        assert view.prev_button.disabled
        assert not view.next_button.disabled
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        assert all(item.disabled for item in view.children)
    asyncio.run(check())


def test_empty_public_ranking_has_no_page_buttons(monkeypatch):
    async def check():
        cog = make_cog()
        monkeypatch.setattr(db_exp, 'getAllData', lambda *args: [])
        message = SimpleNamespace(edit_original_response=AsyncMock())
        ctx = SimpleNamespace(guild=SimpleNamespace(id=7, name='Test'), respond=AsyncMock(return_value=message))
        await expFE.exp_rank.callback(cog, ctx, 0, 1)
        kwargs = message.edit_original_response.call_args.kwargs
        assert kwargs['view'] is None
        assert LANG_PACK['expFE_ranking_result_nomember'] in kwargs['content']
    asyncio.run(check())


def test_web_policy_uses_link_without_querying_rankings(monkeypatch):
    async def check():
        lib_cog_scope.install(replace(lib_cog_scope.PUBLIC_POLICY, ranking_url=lambda bot, guild: 'https://example.com/ranking'))
        query = Mock(side_effect=AssertionError('web mode must not query rankings'))
        monkeypatch.setattr(db_exp, 'getAllData', query)
        monkeypatch.setattr(db_exp, 'getYesterdayData', query)
        ctx = SimpleNamespace(guild=SimpleNamespace(id=7), respond=AsyncMock())
        await expFE.exp_rank.callback(make_cog(), ctx, 2, 99)
        view = ctx.respond.call_args.kwargs['view']
        assert view.children[0].url == 'https://example.com/ranking'
        query.assert_not_called()
    asyncio.run(check())


def test_guild_registration_omits_only_web_ranking_options(monkeypatch):
    web_url = 'https://example.com/ranking'
    lib_cog_scope.install(replace(
        lib_cog_scope.PUBLIC_POLICY,
        ranking_url=lambda bot, guild_id: web_url if guild_id == 10 else None,
    ))
    monkeypatch.setattr(lib_slash_tone_sync, '_t', lambda guild_id, key: LANG_PACK[key])

    def ranking_command(registered_groups):
        group = next(group for group in registered_groups if group.name == '경험치')
        return next(command for command in group.subcommands if command.name == '랭킹')

    async def check():
        bot = discord.Bot()
        cog = make_cog()
        cog.bot = bot
        bot.add_cog(cog)
        try:
            for build in (
                lib_slash_guild_sync._clone_feature_commands,
                lib_slash_tone_sync._build_guild_overrides,
            ):
                web_command = ranking_command(build(bot, 10))
                assert web_command.to_dict()['options'] == []
                discord_command = ranking_command(build(bot, 20))
                assert [option['name'] for option in discord_command.to_dict()['options']] == [
                    '종류', '페이지',
                ]

                ctx = SimpleNamespace(
                    guild=SimpleNamespace(id=10),
                    interaction=SimpleNamespace(data={}),
                    respond=AsyncMock(),
                )
                await web_command._invoke(ctx)
                assert ctx.respond.call_args.kwargs['view'].children[0].url == web_url
        finally:
            await bot.close()

    asyncio.run(check())
