import discord, pathlib, datetime, platform, atexit
from DB import db_tone
from Library import lib_bot_admin, lib_bot_lifecycle, lib_slash_guild_sync
from __version__ import version_str_full
bot = discord.Bot(intents=discord.Intents.all(), auto_sync_commands=False)
bot.ame_ver = version_str_full
bot.loaded = False
bot.dbgChannel = lib_bot_admin.default_debug_channel_id()
PID_FILE = pathlib.Path(__file__).with_name('bot.pid')


def _run_bot(target_bot: discord.Bot, token: str) -> None:
    # py-cord Bot.run()은 내부에서 KeyboardInterrupt를 삼키고 정상 반환하므로,
    # close/종료는 install_shutdown_hook이 담당. finally의 PID 정리는 이중 안전장치.
    try:
        target_bot.run(token)
    finally:
        lib_bot_lifecycle.cleanup_pid_file(PID_FILE)


def _install_tone_reload_signals(target_bot: discord.Bot) -> None:
    def _on_reload():
        db_tone.reload_tone_templates()
        print('[tone] templates reloaded')
        lib_slash_guild_sync.schedule_all_guild_sync(target_bot)

    lib_bot_lifecycle.install_sigusr1_reload(_on_reload, bots=[target_bot])


_install_tone_reload_signals(bot)
lib_bot_lifecycle.install_shutdown_hook(
    bot,
    after_close=lambda: lib_bot_lifecycle.cleanup_pid_file(PID_FILE),
)
lib_bot_lifecycle.ensure_core_db_schemas()
lib_bot_lifecycle.write_pid_file(PID_FILE)
atexit.register(lib_bot_lifecycle.cleanup_pid_file, PID_FILE)

@bot.event
async def on_ready():
    dbg_channel = None
    if not bot.loaded:
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        loadedTime = str(now.strftime("%Y년 %m월 %d일 %H시 %M분 %S.%f"))[:-3]+"초"
        bot.loadedTime = loadedTime
        bot.originalLoadedTime = now
        if platform.system() == 'Linux' and platform.node() in ['AmeNeko', 'ameneko']:
            bot.pf_docker = '아메네코 (Live)'
            bot.at_docker = '아메네코'
        elif platform.system() == "Linux" and platform.node() == 'v2202608397330499012':
            bot.pf_docker = "Amekawa (Live)"
            bot.at_docker = "아메카와"
        elif platform.system() == 'Windows' and platform.node() == 'SE-A-Mk2':
            bot.pf_docker = 'SE-A Mk.2 (Dev)'
            bot.at_docker = '시아'
        elif platform.system() == 'Windows' and platform.node() == 'BOOK-LF4A76G6SH':
            bot.pf_docker = '갤럭시북 (Dev)'
            bot.at_docker = '갤럭시북'
        else:
            bot.pf_docker = '인식할 수 없음'
            bot.at_docker = '어딘가'
        try:
            dbg_channel = await bot.fetch_channel(bot.dbgChannel)
        except Exception as exc:
            print(f'[ready] dbgChannel fetch failed: {exc}')
        try:
            await bot.change_presence(status=discord.Status.online, activity=discord.Game(name=f'{bot.at_docker}에서 동작하는 중'))
        except Exception as e:
            if dbg_channel is not None:
                try:
                    await dbg_channel.send(f'Status 설정에 오류가 있었습니다. 오류 : {e}')
                except Exception as send_exc:
                    print(f'[ready] dbgChannel send failed: {send_exc}')
            else:
                print(f'[ready] presence update failed: {e}')
        if dbg_channel is not None:
            try:
                await dbg_channel.send(f'[봇 시작 알림] 유나봇이 {loadedTime}에  {bot.pf_docker}에서 시작되었습니다. 버전 : {bot.ame_ver}')
            except Exception as exc:
                print(f'[ready] dbgChannel send failed: {exc}')
        bot.loaded=True
    else:
        loadedTime2 = str(datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y년 %m월 %d일 %H시 %M분 %S.%f"))[:-3]+"초"
        bot.loadedTime = str(bot.originalLoadedTime.strftime("%Y년 %m월 %d일 %H시 %M분 %S.%f"))[:-3]+"초" + " (재연결 : " + loadedTime2 + ")"
        try:
            dbg_channel = await bot.fetch_channel(bot.dbgChannel)
        except Exception as exc:
            print(f'[ready] dbgChannel fetch failed: {exc}')
        if dbg_channel is not None:
            try:
                await dbg_channel.send(f'[재연결 알림] 유나봇이 연결이 끊겼다가 {loadedTime2}에 다시 연결되었습니다.')
            except Exception as exc:
                print(f'[ready] dbgChannel send failed: {exc}')
        try:
            await bot.change_presence(status=discord.Status.online, activity=discord.Game(name=f'{bot.at_docker}에서 동작하는 중'))
        except Exception as e:
            if dbg_channel is not None:
                try:
                    await dbg_channel.send(f'Status 설정에 오류가 있었습니다. 오류 : {e}')
                except Exception as send_exc:
                    print(f'[ready] dbgChannel send failed: {send_exc}')
            else:
                print(f'[ready] presence update failed: {e}')
    print(f'{bot.user.name}(#{bot.user.id})으로 로그인되었습니다.')
    print(f'봇이 시작된 시각 : {bot.loadedTime}')
    if not getattr(bot, '_guild_slash_synced', False):
        try:
            failures = await lib_slash_guild_sync.sync_all_guilds(bot)
            bot._guild_slash_synced = not failures
        except Exception as exc:
            print(f'[slash_guild] startup sync failed: {exc}')

lib_slash_guild_sync.install(bot)

for file in sorted((pathlib.Path(__file__).parent / "Cogs").iterdir()):
    if file.name.endswith(".py") and file.name.startswith("c_") and file.name != "__init__.py":
        bot.load_extension(f"Cogs.{file.stem}")

with open(pathlib.PurePath(__file__).with_name('token.txt'), 'r', encoding='utf-8') as token:
    _run_bot(bot, token.readline().strip())
