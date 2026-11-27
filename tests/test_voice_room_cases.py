# coding: utf-8
'''통화 시간·채팅 경험치가 방 인원에 따라 켜지고 꺼지는지 확인한다.'''
import asyncio
from datetime import timedelta

from Cogs.c_expFE import expFE
from DB import db_exp

GID = 7
NAMES = {
    'A': 1,
    'B': 2,
    'C': 3,
    'D': 4,
    'E': 5,
    'Bot': 99,
}


class Guild:
    def __init__(self):
        self.id = GID
        self.voice_channels = []
        self.stage_channels = []


class Channel:
    def __init__(self, name, guild, *, stage=False):
        self.name = name
        self.id = name
        self.guild = guild
        self.members = []
        if stage:
            guild.stage_channels.append(self)
        else:
            guild.voice_channels.append(self)

    def __eq__(self, other):
        return isinstance(other, Channel) and self.id == other.id

    def __hash__(self):
        return hash(self.id)


class Member:
    def __init__(self, name, guild, *, bot=False):
        self.name = name
        self.id = NAMES[name]
        self.bot = bot
        self.guild = guild
        self.channel = None


class VoiceState:
    def __init__(self, channel):
        self.channel = channel


voice_log: list[tuple[int, int]] = []
clear_log: list[int] = []
clock = [db_exp.getNow()]


def _voice_add(guild, uid, amount, date=None):
    voice_log.append((uid, amount))
    return 1


def _clear(guild, uid):
    clear_log.append(uid)


db_exp.voiceCallAdd = _voice_add
db_exp.clearVoicePresence = _clear
db_exp.touchLastApiCall = lambda *args, **kwargs: None
db_exp.ifUserExist = lambda *args, **kwargs: True


def take_voice():
    got = voice_log[:]
    voice_log.clear()
    return got


def take_clears():
    got = clear_log[:]
    clear_log.clear()
    return got


def advance(seconds):
    clock[0] = clock[0] + timedelta(seconds=seconds)


class World:
    def __init__(self):
        self.guild = Guild()
        self.cog = expFE.__new__(expFE)
        self.cog.bot = type('Bot', (), {'guilds': [self.guild]})()
        self.cog._voice_sessions = {}
        self.cog._voice_present = set()
        self.cog._now_kst = lambda: clock[0]
        self.cog._exp_member_ok = lambda member: True
        self.cog._is_allowed_guild = lambda guild_id: True

        async def welcome(*args, **kwargs):
            return False

        self.cog._send_welcome_embed = welcome
        self.members = {}
        for name, uid in NAMES.items():
            self.members[name] = Member(name, self.guild, bot=(name == 'Bot'))
        self.channels = {}

    def channel(self, name, *, stage=False):
        if name not in self.channels:
            self.channels[name] = Channel(name, self.guild, stage=stage)
        return self.channels[name]

    def m(self, name):
        return self.members[name]

    async def go(self, name, dest_name):
        '''디스코드가 캐시를 먼저 고친 뒤 이벤트를 보내는 순서.'''
        member = self.m(name)
        dest = None if dest_name is None else self.channel(dest_name)
        before_ch = member.channel
        if before_ch is not None:
            before_ch.members.remove(member)
        if dest is not None:
            dest.members.append(member)
        member.channel = dest
        await self.cog.on_voice_state_update(member, VoiceState(before_ch), VoiceState(dest))

    def earning(self, *names):
        return {name: (GID, self.m(name).id) in self.cog._voice_sessions for name in names}

    def session_ids(self, *names):
        out = {}
        for name in names:
            session = self.cog._voice_sessions.get((GID, self.m(name).id))
            out[name] = id(session) if session is not None else None
        return out

    def last_ticks(self, *names):
        out = {}
        for name in names:
            session = self.cog._voice_sessions.get((GID, self.m(name).id))
            out[name] = session.last_tick if session is not None else None
        return out

    def chat_blocked(self, name):
        return self.cog._is_in_voice(GID, self.m(name).id)

    async def close(self):
        for name in list(NAMES):
            if (GID, self.m(name).id) in self.cog._voice_sessions:
                await self.cog._stop_voice_session(GID, self.m(name).id)
        take_voice()
        take_clears()


failures: list[str] = []


def check(label, cond, detail=''):
    if cond:
        print(f'  ok  {label}')
        return
    failures.append(f'{label} {detail}')
    print(f'  FAIL {label} {detail}')


async def main():
    # 1. 혼자, 또는 봇과만
    w = World()
    take_voice()
    take_clears()
    await w.go('A', 'music')
    await w.go('Bot', 'music')
    advance(20)
    check('혼자+봇: 통화 시간 없음', take_voice() == [])
    check('혼자+봇: A 채팅 가능', w.chat_blocked('A') is False)
    check('혼자+봇: A는 방에는 있음', (GID, w.m('A').id) in w.cog._voice_present)
    await w.close()

    # 2. 혼자 있던 A에게 B가 들어옴. 그 전 20초는 없고, 같이 있는 5초만.
    w = World()
    await w.go('A', 'room')
    await w.go('Bot', 'room')
    advance(20)
    take_voice()
    started = clock[0]
    await w.go('B', 'room')
    ticks = w.last_ticks('A', 'B')
    check('B 입장: 그 순간부터 A,B 집계', w.earning('A', 'B') == {'A': True, 'B': True})
    check('B 입장: 시작 시각이 입장 시각', ticks['A'] == started and ticks['B'] == started)
    check('B 입장: 직전 혼자 시간은 없음', take_voice() == [])
    check('같이 있음: 채팅 막힘', w.chat_blocked('A') and w.chat_blocked('B'))
    advance(5)
    await w.go('B', None)
    got = sorted(take_voice())
    check('B 퇴장: A,B 모두 5초만', got == [(1, 50), (2, 50)], got)
    check('B 퇴장: A는 채팅 다시 가능', w.chat_blocked('A') is False and w.earning('A')['A'] is False)
    await w.close()

    # 3. A B C 방에서 C가 D만 있는 방으로 이동
    w = World()
    await w.go('A', 'r1')
    await w.go('B', 'r1')
    await w.go('C', 'r1')
    await w.go('D', 'r2')
    advance(10)
    take_voice()
    before = w.session_ids('A', 'B', 'C')
    ticks_before = w.last_ticks('A', 'B', 'C')
    d_was = w.earning('D')['D']
    await w.go('C', 'r2')
    after = w.session_ids('A', 'B', 'C', 'D')
    ticks_after = w.last_ticks('A', 'B', 'C', 'D')
    check('C→D: 이동 전 D는 안 쌓임', d_was is False)
    check('C→D: A,B,C 세션 유지', after['A'] == before['A'] and after['B'] == before['B'] and after['C'] == before['C'])
    check('C→D: A,B,C 시작 시각 유지', ticks_after['A'] == ticks_before['A'] and ticks_after['C'] == ticks_before['C'])
    check('C→D: D는 이동 시각부터', ticks_after['D'] == clock[0] and after['D'] is not None)
    check('C→D: 이동 순간 추가 정산 없음', take_voice() == [])
    check('C→D: 네 명 채팅 막힘', all(w.chat_blocked(n) for n in 'ABCD'))
    advance(4)
    # D가 나가 C가 혼자가 되면 C는 그때 정산된다.
    # C는 방을 옮겨도 세션이 이어지므로 앞의 10초+4초이고, D는 같이 있던 4초만이다.
    await w.go('D', None)
    got = sorted(take_voice())
    check('D 퇴장: C는 이어진 14초, D는 4초', got == [(3, 140), (4, 40)], got)
    check('D 퇴장: A,B 세션 유지', w.session_ids('A', 'B')['A'] == before['A'])
    check('D 퇴장: C 채팅 가능', w.chat_blocked('C') is False)
    await w.close()

    # 4. A B C 방에서 C가 D,E 방으로 이동. 다섯 명 전부 이어서.
    w = World()
    await w.go('A', 'r1')
    await w.go('B', 'r1')
    await w.go('C', 'r1')
    await w.go('D', 'r2')
    await w.go('E', 'r2')
    advance(8)
    take_voice()
    before = w.session_ids('A', 'B', 'C', 'D', 'E')
    ticks_before = w.last_ticks('A', 'B', 'C', 'D', 'E')
    await w.go('C', 'r2')
    after = w.session_ids('A', 'B', 'C', 'D', 'E')
    ticks_after = w.last_ticks('A', 'B', 'C', 'D', 'E')
    check('C→DE: 다섯 세션 모두 유지', before == after, (before, after))
    check('C→DE: 시작 시각 유지', ticks_before == ticks_after)
    check('C→DE: 이동 순간 정산 없음', take_voice() == [])
    check('C→DE: 다섯 명 채팅 막힘', all(w.chat_blocked(n) for n in 'ABCDE'))
    advance(3)
    await w.go('C', None)
    got = sorted(take_voice())
    # C는 처음부터 11초, A,B,D,E는 세션 유지
    check('C 퇴장: C만 11초', got == [(3, 110)], got)
    check('C 퇴장: 나머지 네 세션 유지', w.session_ids('A', 'B', 'D', 'E') == {n: before[n] for n in 'ABDE'})
    await w.close()

    # 5. 둘이 있던 방에서 한 명이 다른 혼자에게 이동하면, 남은 사람은 멈춤
    w = World()
    await w.go('A', 'r1')
    await w.go('C', 'r1')
    await w.go('D', 'r2')
    advance(6)
    take_voice()
    c_before = w.session_ids('C')['C']
    await w.go('C', 'r2')
    got = sorted(take_voice())
    check('AC→D: 남은 A는 6초 후 멈춤', got == [(1, 60)], got)
    check('AC→D: C 세션은 유지', w.session_ids('C')['C'] == c_before)
    check('AC→D: D는 지금 시작', w.last_ticks('D')['D'] == clock[0])
    check('AC→D: A 채팅 가능, C,D 막힘', (not w.chat_blocked('A')) and w.chat_blocked('C') and w.chat_blocked('D'))
    await w.close()

    # 6. 셋이 있는 방에서 한 명이 빈 방(봇만)으로 이동
    w = World()
    await w.go('A', 'r1')
    await w.go('B', 'r1')
    await w.go('C', 'r1')
    await w.go('Bot', 'music')
    advance(2)
    take_voice()
    before = w.session_ids('A', 'B')
    await w.go('C', 'music')
    got = sorted(take_voice())
    check('C→봇방: C만 2초', got == [(3, 20)], got)
    check('C→봇방: A,B 유지', w.session_ids('A', 'B') == before)
    check('C→봇방: C 채팅 가능', w.chat_blocked('C') is False)
    await w.close()

    # 7. 빈 방에서 사람이 있는 방으로 이동
    w = World()
    await w.go('A', 'alone')
    await w.go('B', 'group')
    await w.go('C', 'group')
    advance(9)
    take_voice()
    bc = w.session_ids('B', 'C')
    await w.go('A', 'group')
    check('혼자→그룹: A만 지금 시작', w.last_ticks('A')['A'] == clock[0])
    check('혼자→그룹: B,C 유지', w.session_ids('B', 'C') == bc)
    check('혼자→그룹: 이동 순간 정산 없음', take_voice() == [])
    await w.close()

    # 8. 셋에서 한 명 퇴장, 둘 남으면 계속
    w = World()
    await w.go('A', 'r1')
    await w.go('B', 'r1')
    await w.go('C', 'r1')
    advance(7.98)
    take_voice()
    before = w.session_ids('A', 'B')
    await w.go('C', None)
    got = sorted(take_voice())
    check('셋에서 C 퇴장: C만 7.98초', got == [(3, 79)], got)
    check('셋에서 C 퇴장: A,B 유지', w.session_ids('A', 'B') == before)
    await w.close()

    # 9. 음소거는 인원 그대로
    w = World()
    await w.go('A', 'r1')
    await w.go('B', 'r1')
    advance(1)
    take_voice()
    before = w.session_ids('A', 'B')
    member = w.m('A')
    state = VoiceState(member.channel)
    await w.cog.on_voice_state_update(member, state, state)
    check('음소거: 세션 유지', w.session_ids('A', 'B') == before)
    check('음소거: 정산 없음', take_voice() == [])
    await w.close()

    # 10. 봇이 들락날락해도 사람 수는 그대로
    w = World()
    await w.go('A', 'music')
    advance(3)
    await w.go('Bot', 'music')
    await w.go('Bot', None)
    check('봇 출입: A는 계속 안 쌓임', w.earning('A')['A'] is False)
    check('봇 출입: 시간 없음', take_voice() == [])
    await w.go('B', 'music')
    await w.go('Bot', 'music')
    advance(1)
    before = w.session_ids('A', 'B')
    await w.go('Bot', None)
    check('봇 퇴장: A,B 유지', w.session_ids('A', 'B') == before)
    check('봇 퇴장: 정산 없음', take_voice() == [])
    await w.close()

    # 11. 네 명이 있는 방에서 한 명이, 혼자 있는 사람에게 이동
    w = World()
    await w.go('A', 'r1')
    await w.go('B', 'r1')
    await w.go('C', 'r1')
    await w.go('D', 'r1')
    await w.go('E', 'r2')
    advance(2)
    take_voice()
    before = w.session_ids('A', 'B', 'C', 'D')
    await w.go('D', 'r2')
    after = w.session_ids('A', 'B', 'C', 'D', 'E')
    check('ABCD→E: A,B,C,D 세션 유지', all(after[n] == before[n] for n in 'ABCD'))
    check('ABCD→E: E 시작', after['E'] is not None and w.last_ticks('E')['E'] == clock[0])
    check('ABCD→E: 이동 순간 정산 없음', take_voice() == [])
    await w.close()

    # 12. 이어서 한 명 더 빠져 남은 방이 혼자가 되면 그 사람만 멈춤
    w = World()
    await w.go('A', 'r1')
    await w.go('B', 'r1')
    await w.go('C', 'r1')
    await w.go('D', 'r2')
    advance(5)
    take_voice()
    await w.go('C', 'r2')  # A,B continue, C continue, D starts
    ab = w.session_ids('A', 'B')
    await w.go('B', 'r2')  # r1 left with A alone
    got = sorted(take_voice())
    check('한 명 더 이동: 남은 A만 5초', got == [(1, 50)], got)
    check('한 명 더 이동: B,C,D는 쌓임', w.earning('B', 'C', 'D') == {'B': True, 'C': True, 'D': True})
    check('한 명 더 이동: B 세션은 처음 것과 같음', w.session_ids('B')['B'] == ab['B'])
    await w.close()

    # 13. 재시작 복구. 같이 있는 방만 다시 집계.
    w = World()
    await w.go('A', 'r1')
    await w.go('B', 'r1')
    await w.go('C', 'r1')
    await w.go('D', 'music')
    await w.go('Bot', 'music')
    w.channel('stage', stage=True)
    await w.go('E', 'stage')
    await w.go('A', 'stage')  # this pulls A out of r1. Don't. Rebuild cleanly.
    await w.close()

    w = World()
    r1 = w.channel('r1')
    music = w.channel('music')
    stage = w.channel('stage', stage=True)
    for name, ch in (('A', r1), ('B', r1), ('C', r1), ('D', music), ('Bot', music), ('E', stage)):
        member = w.m(name)
        member.channel = ch
        ch.members.append(member)
    # F is not in NAMES. Stage needs two humans: put B? Then r1 loses a person.
    # Stage E + a duplicate path: add member B stays in r1. Use C also? 
    # Put E and a new situation: stage has E only so E should NOT earn. r1 ABC earn. music D+bot no.
    take_voice()
    await w.cog._recover_voice_sessions()
    check('복구: A,B,C만 집계', w.earning('A', 'B', 'C', 'D', 'E') == {
        'A': True, 'B': True, 'C': True, 'D': False, 'E': False,
    })
    check('복구: 시작 시각은 복구 시각', w.last_ticks('A', 'B', 'C')['A'] == clock[0])
    check('복구: 즉시 정산 없음', take_voice() == [])
    await w.close()

    # 14. 경험치 대상이 아닌 사람도 인원에는 포함
    w = World()
    w.cog._exp_member_ok = lambda member: member.name != 'A'

    async def go_raw():
        await w.go('A', 'r1')
        await w.go('B', 'r1')

    await go_raw()
    check('권한 없는 A: 본인은 안 쌓임', w.earning('A', 'B') == {'A': False, 'B': True})
    check('권한 없는 A: B 채팅은 막힘', w.chat_blocked('B') is True)
    advance(3)
    await w.go('B', None)
    got = sorted(take_voice())
    check('권한 없는 A: B만 3초', got == [(2, 30)], got)
    await w.close()

    if failures:
        print(f'\n{len(failures)} failed')
        for item in failures:
            print(' -', item)
        raise SystemExit(1)
    print('\nall cases passed')


if __name__ == '__main__':
    asyncio.run(main())
