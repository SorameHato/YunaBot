import asyncio
import discord, os, pathlib, datetime, platform, signal, atexit
from discord.ext import tasks as discord_tasks
import db_tone, db_exp, db_setting
import lib_slash_guild_sync
from __version__ import version_str_full
bot = discord.Bot(intents=discord.Intents.all(), auto_sync_commands=False)
bot.ame_ver = version_str_full
bot.loaded = False
bot.dbgChannel = 1504509915123945474
PID_FILE = pathlib.Path(__file__).with_name('bot.pid')


def _write_pid_file() -> None:
    try:
        PID_FILE.write_text(str(os.getpid()), encoding='utf-8')
    except Exception as exc:
        print(f'[pid] write failed: {exc}')


def _cleanup_pid_file() -> None:
    try:
        if PID_FILE.exists():
            current = PID_FILE.read_text(encoding='utf-8').strip()
            if current == str(os.getpid()):
                PID_FILE.unlink()
    except Exception as exc:
        print(f'[pid] cleanup failed: {exc}')


def _cancel_running_cog_tasks(target_bot: discord.Bot) -> None:
    for cog in list(target_bot.cogs.values()):
        for name in dir(cog):
            member = getattr(cog, name, None)
            if isinstance(member, discord_tasks.Loop) and member.is_running():
                try:
                    member.cancel()
                except Exception as exc:
                    print(f'[shutdown] task cancel failed ({name}): {exc}')


def _unload_extensions(target_bot: discord.Bot) -> None:
    for ext_name in list(target_bot.extensions):
        try:
            target_bot.unload_extension(ext_name)
        except Exception as exc:
            print(f'[shutdown] extension unload failed ({ext_name}): {exc}')


def _install_shutdown_hook(target_bot: discord.Bot) -> None:
    if getattr(target_bot, '_shutdown_hook_installed', False):
        return

    original_close = target_bot.close

    async def close() -> None:
        if getattr(target_bot, '_shutdown_in_progress', False):
            await original_close()
            return

        target_bot._shutdown_in_progress = True
        print('[shutdown] 종료 중...')
        _cancel_running_cog_tasks(target_bot)
        _unload_extensions(target_bot)
        if not target_bot.is_closed():
            await original_close()
        _cleanup_pid_file()
        print('[shutdown] 종료 완료')

    target_bot.close = close
    target_bot._shutdown_hook_installed = True


def _run_bot(target_bot: discord.Bot, token: str) -> None:
    try:
        target_bot.run(token)
    except KeyboardInterrupt:
        print('[shutdown] Ctrl+C로 종료합니다.')
        if not target_bot.is_closed():
            loop = target_bot.loop
            try:
                if loop.is_running():
                    loop.run_until_complete(target_bot.close())
                else:
                    asyncio.run(target_bot.close())
            except Exception as exc:
                print(f'[shutdown] close failed: {exc}')
                _cleanup_pid_file()
    finally:
        _cleanup_pid_file()


def _install_tone_reload_signals(target_bot: discord.Bot) -> None:
    def _handle_reload(_signum, _frame):
        def _do_reload():
            try:
                db_tone.reload_tone_templates()
                print('[tone] templates reloaded')
                lib_slash_guild_sync.schedule_all_guild_sync(target_bot)
            except Exception as exc:
                print(f'[tone] reload failed: {exc}')

        if target_bot.loop.is_running():
            target_bot.loop.call_soon_threadsafe(_do_reload)
        else:
            _do_reload()

    if hasattr(signal, 'SIGUSR1'):
        signal.signal(signal.SIGUSR1, _handle_reload)

def _ensure_db_schemas() -> None:
    db_setting.ensure_schema()
    db_exp.ensure_schema()


_install_tone_reload_signals(bot)
_install_shutdown_hook(bot)
_ensure_db_schemas()
_write_pid_file()
atexit.register(_cleanup_pid_file)

@bot.event
async def on_ready():
    if not bot.loaded:
        loadedTime = str(datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y년 %m월 %d일 %H시 %M분 %S.%f"))[:-3]+"초"
        bot.loadedTime = loadedTime
        if platform.system() == 'Linux' and platform.node() in ['AmeNeko', 'ameneko']:
            bot.pf_docker = '아메네코 (Live)'
            bot.at_docker = '아메네코'
        elif platform.system() == 'Windows' and platform.node() == 'SE-A-Mk2':
            bot.pf_docker = 'SE-A Mk.2 (Dev)'
            bot.at_docker = '시아'
        else:
            bot.pf_docker = '인식할 수 없음'
            bot.at_docker = '어딘가'
        dbgChannel = await bot.fetch_channel(bot.dbgChannel)
        try:
            await bot.change_presence(status=discord.Status.online, activity=discord.Game(name=f'{bot.at_docker}에서 동작'))
        except Exception as e:
            await dbgChannel.send(f'Status 설정에 오류가 있었습니다. 오류 : {e}')
        await dbgChannel.send(f'[봇 시작 알림] 유나봇이 {loadedTime}에  {bot.pf_docker}에서 시작되었습니다. 버전 : {bot.ame_ver}')
        bot.loaded=True
    else:
        loadedTime2 = str(datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y년 %m월 %d일 %H시 %M분 %S.%f"))[:-3]+"초"
        bot.loadedTime = loadedTime + " (재연결 : " + loadedTime2 + ")"
        dbgChannel = await bot.fetch_channel(bot.dbgChannel)
        await dbgChannel.send(f'[재연결 알림] 유나봇이 연결이 끊겼다가 {loadedTime2}에 다시 연결되었습니다.')
        try:
            await bot.change_presence(status=discord.Status.online, activity=discord.Game(name=f'{bot.at_docker}에서 동작'))
        except Exception as e:
            await dbgChannel.send(f'Status 설정에 오류가 있었습니다. 오류 : {e}')
    print(f'{bot.user.name}(#{bot.user.id})으로 로그인되었습니다.')
    print(f'봇이 시작된 시각 : {bot.loadedTime}')
    if not getattr(bot, '_guild_slash_synced', False):
        try:
            await lib_slash_guild_sync.sync_all_guilds(bot)
            bot._guild_slash_synced = True
        except Exception as exc:
            print(f'[slash_guild] startup sync failed: {exc}')

lib_slash_guild_sync.install(bot)

for file in pathlib.Path(__file__).parent.iterdir():
    if file.name.endswith(".py") and file.name.startswith("c_"):
        bot.load_extension(f"{file.name.replace('.py','')}")

# for filename in os.listdir(pathlib.PurePath(__file__).parent.joinpath('Cogs')):
#     if filename.endswith('.py'):
#         bot.load_extension('Cogs.{}'.format(filename[:-3]))

with open(pathlib.PurePath(__file__).with_name('token.txt'), 'r', encoding='utf-8') as token:
    _run_bot(bot, token.readline().strip())
