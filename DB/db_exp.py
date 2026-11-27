import sys, os, json
from typing import Literal, Optional, get_args
from datetime import datetime as dt
from datetime import timezone as tz
from datetime import timedelta as td
from datetime import date, time
import threading
from . import exp_log
from .db import _connectDB_raw, execute_upsert
chatPoint = 3
chatCooltime = 45
voicePoint = 1
voiceCooltime = 60  # exp 산식: voice_count/(voiceCooltime*10) 회당 voicePoint
voiceTickInterval = 15  # 통화 중 voice_count 주기 반영 간격(초)
voiceTickAmount = 150  # 주기마다 voice_count 가산 (15초×10)
dayPoint = 50
globalVoiceSessionTtl = voiceTickInterval * 2
_globalVoiceStopPairWindowMs = 5000
_globalVoiceTls = threading.local()

# KST 기준 경험치·출석 날짜 변경 시각 (일일 초기화·day_count 경계)
EXP_TZ = exp_log.KST
EXP_UTC = tz(td(seconds=0))
EXP_DAY_ROLLOVER = time(5, 15)
EXP_DAY_EPOCH = date(2020, 1, 1)  # KST 달력 기준 경험치일 인덱스 원점


def exp_day_index(when: dt) -> int:
    '''2020-01-01부터의 경험치일 인덱스. EXP_DAY_ROLLOVER 이전이면 -1.'''
    d = when.astimezone(EXP_TZ) if when.tzinfo else when.replace(tzinfo=EXP_TZ)
    n = (d.date() - EXP_DAY_EPOCH).days
    if d.time() < EXP_DAY_ROLLOVER:
        n -= 1
    return n


def _rest_days_since_attend(last_attend: int, today_idx: int, last_call_fallback: dt) -> int:
    '''
    출석 간격(restDay). last_attend>0이면 그 경험치일 인덱스 기준,
    0(마이그레이션 전)이면 last_call로 폴백.
    '''
    if last_attend > 0:
        return today_idx - last_attend
    return today_idx - exp_day_index(last_call_fallback)


def via_voice_last_call(now: dt) -> dt:
    '''via_voice/수동 출석용 last_call. now - chatCooltime.'''
    return now - td(seconds=chatCooltime)


def daily_init_utc_time() -> time:
    '''daily_init_exp 태스크 스케줄용 UTC time (EXP_DAY_ROLLOVER KST와 동일 시각).'''
    kst = dt(
        2000,
        1,
        2,
        EXP_DAY_ROLLOVER.hour,
        EXP_DAY_ROLLOVER.minute,
        1,
        tzinfo=EXP_TZ,
    )
    utc = kst.astimezone(EXP_UTC)
    return time(utc.hour, utc.minute, utc.second, tzinfo=EXP_UTC)


def voiceLeaveRemainder(last_voice_add: dt, leave_at: dt) -> int:
    '''
    마지막 voice_count 반영 시각부터 퇴장까지 더할 voice_count.

    delta // 0.1초 — 초의 소수 첫째 자리까지(0.1초=voice_count 1). 예: 7.98초 → 79.
    '''
    delta = leave_at - last_voice_add
    if delta <= td(0):
        return 0
    return delta // td(milliseconds=100)

DataNameGet = Literal['guild', 'uid', 'first_call', 'last_call', 'last_api_call', 'last_attend', 'total_chat', 'chat_count', 'voice_count', 'day_count', 'exp', 'yesterday_exp', 'yesterday_incr', 'silent', 'increase']
DataNameSet = Literal['last_call', 'last_api_call', 'last_attend', 'total_chat', 'chat_count', 'voice_count', 'day_count', 'exp', 'yesterday_exp', 'yesterday_incr', 'silent']
DataNameAdd = Literal['total_chat', 'chat_count', 'voice_count', 'day_count', 'exp']
DoMany = Literal['get','add','set']
GlobalDataNameGet = Literal['uid', 'first_call', 'last_call', 'last_api_call', 'last_attend', 'total_chat', 'chat_count', 'voice_count', 'day_count', 'exp', 'yesterday_exp', 'yesterday_incr', 'increase']
GlobalDataNameSet = Literal['last_call', 'last_api_call', 'last_attend', 'total_chat', 'chat_count', 'voice_count', 'day_count', 'exp', 'yesterday_exp', 'yesterday_incr']
GlobalDataNameAdd = Literal['total_chat', 'chat_count', 'voice_count', 'day_count', 'exp']

def getTimeStamp(now:dt) -> int:
    return int(now.timestamp() * 1000)

def fromTimeStamp(ts:int) -> dt:
    return dt.fromtimestamp(ts/1000,tz=EXP_TZ)

def getNow() -> dt:
    return dt.now(tz=EXP_TZ)


def _setGlobalVoiceStopPair(uid: int, guild: int, now: dt) -> None:
    _globalVoiceTls.stop_pair = (uid, guild, getTimeStamp(now))


def _clearGlobalVoiceStopPair() -> None:
    if hasattr(_globalVoiceTls, 'stop_pair'):
        delattr(_globalVoiceTls, 'stop_pair')


def _clearStaleGlobalVoiceStopPair(now: dt) -> None:
    pair = getattr(_globalVoiceTls, 'stop_pair', None)
    if pair is None:
        return
    if getTimeStamp(now) - pair[2] > _globalVoiceStopPairWindowMs:
        _clearGlobalVoiceStopPair()


def _consumeGlobalVoiceStopPair(uid: int, guild: int, now: dt) -> bool:
    pair = getattr(_globalVoiceTls, 'stop_pair', None)
    if pair is None:
        return False
    p_uid, p_guild, p_ts = pair
    now_ts = getTimeStamp(now)
    if now_ts - p_ts > _globalVoiceStopPairWindowMs:
        _clearGlobalVoiceStopPair()
        return False
    if p_uid == uid and p_guild == guild:
        _clearGlobalVoiceStopPair()
        return True
    return False

# DB 연결하는 클래스

class _connectDB(_connectDB_raw):
    def __init__(self):
        super().__init__('exp')

    def ensure_schema(self) -> None:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {self.db_prefix}_exp ('
                f'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                f'guild INTEGER NOT NULL, '
                f'uid INTEGER NOT NULL, '
                f'first_call INTEGER NOT NULL, '
                f'last_call INTEGER NOT NULL, '
                f'last_api_call INTEGER NOT NULL, '
                f'last_attend INTEGER NOT NULL DEFAULT 0, '
                f'total_chat INTEGER NOT NULL DEFAULT 0, '
                f'chat_count INTEGER NOT NULL DEFAULT 1, '
                f'voice_count INTEGER NOT NULL DEFAULT 0, '
                f'day_count INTEGER NOT NULL DEFAULT 1, '
                f'exp INTEGER NOT NULL DEFAULT 0, '
                f'yesterday_exp INTEGER NOT NULL DEFAULT 0, '
                f'yesterday_incr INTEGER NOT NULL DEFAULT 0, '
                f'silent INTEGER NOT NULL DEFAULT 0, '
                f'UNIQUE(guild, uid)'
                f');'
            )
        else:
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {self.db_prefix}_exp ('
                f'id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, '
                f'guild BIGINT NOT NULL, '
                f'uid BIGINT NOT NULL, '
                f'first_call BIGINT NOT NULL, '
                f'last_call BIGINT NOT NULL, '
                f'last_api_call BIGINT NOT NULL, '
                f'last_attend BIGINT NOT NULL DEFAULT 0, '
                f'total_chat INT NOT NULL DEFAULT 0, '
                f'chat_count INT NOT NULL DEFAULT 1, '
                f'voice_count INT NOT NULL DEFAULT 0, '
                f'day_count INT NOT NULL DEFAULT 1, '
                f'exp INT NOT NULL DEFAULT 0, '
                f'yesterday_exp INT NOT NULL DEFAULT 0, '
                f'yesterday_incr INT NOT NULL DEFAULT 0, '
                f'silent TINYINT(1) NOT NULL DEFAULT 0, '
                f'UNIQUE KEY uq_exp_guild_uid (guild, uid)'
                f');'
            )
        self._ensure_last_api_call_column()
        self._ensure_last_attend_column()
        self._ensure_global_schema()
        self._ensure_user_profile_schema()
        self._ensure_daily_init_schema()

    def _ensure_daily_init_schema(self) -> None:
        '''dailyDBInit 멱등용 싱글톤 (같은 경험치일에 두 번 돌리면 yesterday_incr가 0이 됨).'''
        table = f'{self.db_prefix}_exp_daily_init'
        if self.type == 'sqlite3':
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {table} ('
                f'id INTEGER PRIMARY KEY CHECK (id = 1), '
                f'day_index INTEGER NOT NULL, '
                f'updated_at INTEGER NOT NULL'
                f');'
            )
            return
        self.cur.execute(
            f'CREATE TABLE IF NOT EXISTS {table} ('
            f'id TINYINT NOT NULL PRIMARY KEY, '
            f'day_index BIGINT NOT NULL, '
            f'updated_at BIGINT NOT NULL'
            f');'
        )

    def _ensure_user_profile_schema(self) -> None:
        '''웹 순위표용 Discord 닉네임/아바타 캐시 (일일 초기화 시 갱신).'''
        table = f'{self.db_prefix}_user_profile'
        if self.type == 'sqlite3':
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {table} ('
                f'uid INTEGER PRIMARY KEY, '
                f'username TEXT NOT NULL DEFAULT \'\', '
                f'global_name TEXT, '
                f'avatar_hash TEXT, '
                f'updated_at INTEGER NOT NULL'
                f');'
            )
        else:
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {table} ('
                f'uid BIGINT NOT NULL PRIMARY KEY, '
                f'username VARCHAR(64) NOT NULL DEFAULT \'\', '
                f'global_name VARCHAR(64) NULL, '
                f'avatar_hash VARCHAR(128) NULL, '
                f'updated_at BIGINT NOT NULL'
                f');'
            )

    def _ensure_last_api_call_column(self) -> None:
        table = f'{self.db_prefix}_exp'
        if self.type == 'sqlite3':
            self.cur.execute(f'PRAGMA table_info({table});')
            columns = {row[1] for row in self.cur.fetchall()}
            if 'last_api_call' not in columns:
                self.cur.execute(
                    f'ALTER TABLE {table} '
                    f'ADD COLUMN last_api_call INTEGER NOT NULL DEFAULT 0;'
                )
                self.cur.execute(
                    f'UPDATE {table} SET last_api_call=last_call WHERE last_api_call=0;'
                )
            return
        self.cur.execute(f'SHOW COLUMNS FROM {table};')
        columns = {row[0] for row in self.cur.fetchall()}
        if 'last_api_call' not in columns:
            self.cur.execute(
                f'ALTER TABLE {table} '
                f'ADD COLUMN last_api_call BIGINT NOT NULL DEFAULT 0;'
            )
            self.cur.execute(
                f'UPDATE {table} SET last_api_call=last_call WHERE last_api_call=0;'
            )

    def _ensure_last_attend_column(self) -> None:
        table = f'{self.db_prefix}_exp'
        if self.type == 'sqlite3':
            self.cur.execute(f'PRAGMA table_info({table});')
            columns = {row[1] for row in self.cur.fetchall()}
            if 'last_attend' not in columns:
                self.cur.execute(
                    f'ALTER TABLE {table} '
                    f'ADD COLUMN last_attend INTEGER NOT NULL DEFAULT 0;'
                )
            return
        self.cur.execute(f'SHOW COLUMNS FROM {table};')
        columns = {row[0] for row in self.cur.fetchall()}
        if 'last_attend' not in columns:
            self.cur.execute(
                f'ALTER TABLE {table} '
                f'ADD COLUMN last_attend BIGINT NOT NULL DEFAULT 0;'
            )

    def _ensure_global_schema(self) -> None:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {self.db_prefix}_global_exp ('
                f'uid INTEGER PRIMARY KEY, '
                f'first_call INTEGER NOT NULL, '
                f'last_call INTEGER NOT NULL, '
                f'last_api_call INTEGER NOT NULL, '
                f'last_attend INTEGER NOT NULL DEFAULT 0, '
                f'total_chat INTEGER NOT NULL DEFAULT 0, '
                f'chat_count INTEGER NOT NULL DEFAULT 1, '
                f'voice_count INTEGER NOT NULL DEFAULT 0, '
                f'day_count INTEGER NOT NULL DEFAULT 1, '
                f'exp INTEGER NOT NULL DEFAULT 0, '
                f'yesterday_exp INTEGER NOT NULL DEFAULT 0, '
                f'yesterday_incr INTEGER NOT NULL DEFAULT 0'
                f');'
            )
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {self.db_prefix}_global_voice_session ('
                f'uid INTEGER NOT NULL, '
                f'guild INTEGER NOT NULL, '
                f'last_active INTEGER NOT NULL, '
                f'PRIMARY KEY(uid, guild)'
                f');'
            )
        else:
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {self.db_prefix}_global_exp ('
                f'uid BIGINT NOT NULL PRIMARY KEY, '
                f'first_call BIGINT NOT NULL, '
                f'last_call BIGINT NOT NULL, '
                f'last_api_call BIGINT NOT NULL, '
                f'last_attend BIGINT NOT NULL DEFAULT 0, '
                f'total_chat INT NOT NULL DEFAULT 0, '
                f'chat_count INT NOT NULL DEFAULT 1, '
                f'voice_count INT NOT NULL DEFAULT 0, '
                f'day_count INT NOT NULL DEFAULT 1, '
                f'exp INT NOT NULL DEFAULT 0, '
                f'yesterday_exp INT NOT NULL DEFAULT 0, '
                f'yesterday_incr INT NOT NULL DEFAULT 0'
                f');'
            )
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {self.db_prefix}_global_voice_session ('
                f'uid BIGINT NOT NULL, '
                f'guild BIGINT NOT NULL, '
                f'last_active BIGINT NOT NULL, '
                f'PRIMARY KEY(uid, guild), '
                f'KEY idx_global_voice_uid_last_active(uid, last_active)'
                f');'
            )
        self._ensure_global_last_api_call_column()
        self._ensure_global_last_attend_column()

    def _ensure_global_last_api_call_column(self) -> None:
        table = f'{self.db_prefix}_global_exp'
        if self.type == 'sqlite3':
            self.cur.execute(f'PRAGMA table_info({table});')
            columns = {row[1] for row in self.cur.fetchall()}
            if 'last_api_call' not in columns:
                self.cur.execute(
                    f'ALTER TABLE {table} '
                    f'ADD COLUMN last_api_call INTEGER NOT NULL DEFAULT 0;'
                )
                self.cur.execute(
                    f'UPDATE {table} SET last_api_call=last_call WHERE last_api_call=0;'
                )
            return
        self.cur.execute(f'SHOW COLUMNS FROM {table};')
        columns = {row[0] for row in self.cur.fetchall()}
        if 'last_api_call' not in columns:
            self.cur.execute(
                f'ALTER TABLE {table} '
                f'ADD COLUMN last_api_call BIGINT NOT NULL DEFAULT 0;'
            )
            self.cur.execute(
                f'UPDATE {table} SET last_api_call=last_call WHERE last_api_call=0;'
            )

    def _ensure_global_last_attend_column(self) -> None:
        table = f'{self.db_prefix}_global_exp'
        if self.type == 'sqlite3':
            self.cur.execute(f'PRAGMA table_info({table});')
            columns = {row[1] for row in self.cur.fetchall()}
            if 'last_attend' not in columns:
                self.cur.execute(
                    f'ALTER TABLE {table} '
                    f'ADD COLUMN last_attend INTEGER NOT NULL DEFAULT 0;'
                )
            return
        self.cur.execute(f'SHOW COLUMNS FROM {table};')
        columns = {row[0] for row in self.cur.fetchall()}
        if 'last_attend' not in columns:
            self.cur.execute(
                f'ALTER TABLE {table} '
                f'ADD COLUMN last_attend BIGINT NOT NULL DEFAULT 0;'
            )

    def dataCheck(self, typ, dataName):
        if ((typ == 0 and dataName in get_args(DataNameGet)) or # get
        (typ == 1 and dataName in get_args(DataNameAdd)) or # add
        (typ == 2 and dataName in get_args(DataNameSet))): # set
            return True
        else:
            return False
        
    def doMany(self, guild, uid, job:DoMany, dataList:list):
        '''
        여러 개 한꺼번에 조회하거나 추가하는 함수<br>
        job : 뭘 할 지<br>
        dataList : get의 경우 dataName만 담은 1차원 리스트(['exp','chat_count','voice_count' … ])<br>
        dataList : set/add의 경우 dataName과 값을 담은 2차원 리스트 ([['chat_count',1],['voice_count',150] … ])
        '''
        match job:
            case 'get':
                for data in dataList:
                    self.get(guild, uid, data)
            case 'set':
                for data in dataList:
                    self.set(guild, uid, data[0], data[1])
            case 'add':
                for data in dataList:
                    self.add(guild, uid, data[0], data[1])

    def get(self, guild:int, uid:int, dataName:DataNameGet):
        '''
        status나 gamble 테이블에서 지정한 데이터를 가지고 오는 함수<br>
        in  : Guild, UID, 플랫폼 code, 데이터명
        '''
        if not self.dataCheck(0,dataName):
            return None
        if dataName == 'increase':
            dataName = '(exp-yesterday_exp) AS increase'
        if self.type == 'sqlite3':
            self.cur.execute(f'SELECT {dataName} FROM {self.db_prefix}_exp WHERE guild=:guild AND uid=:uid;',{'guild':guild,'uid':uid})
        else:
            self.cur.execute(f'SELECT {dataName} FROM {self.db_prefix}_exp WHERE guild=%s AND uid=%s',(guild, uid))
        result = self.cur.fetchone()
        if result is None:
            raise IndexError('DB > _connectDB.get : row not found')
        return result[0]
    
    def getAll(self, guild:int, uid:int):
        '''
        status나 gamble 테이블에서 해당 유저의 모든 데이터를 가지고 오는 함수<br>
        in  : UID, 플랫폼 code, tableNo<br>...
        '''
        if self.type == 'sqlite3':
            self.cur.execute(f'SELECT * FROM {self.db_prefix}_exp WHERE guild=:guild AND uid=:uid;',{'guild':guild,'uid':uid})
        else:
            self.cur.execute(f'SELECT * FROM {self.db_prefix}_exp WHERE guild=%s AND uid=%s',(guild, uid))
        return self.cur.fetchone()

    def set(self, guild:int, uid:int, dataName:DataNameSet, amount:int)->None:
        '''
        status나 gamble 테이블에서 지정한 데이터를 변경하는 함수<br>
        in  : UID, 데이터명, 설정할 값
        '''
        if not self.dataCheck(2, dataName):
            return None
        if self.type == 'sqlite3':
            self.cur.execute(f'UPDATE {self.db_prefix}_exp SET {dataName}=:amount WHERE guild=:guild AND uid=:uid;',{'guild':guild,'uid':uid,'amount':amount})
        else:
            self.cur.execute(f'UPDATE {self.db_prefix}_exp SET {dataName}=%s WHERE guild=%s AND uid=%s',(amount, guild, uid))

    def add(self, guild:int, uid:int, dataName:DataNameAdd, amount:int)->None:
        '''
        status나 gamble 테이블에서 지정한 데이터에서 주어진 값만큼 더하거나 빼는 함수<br>
        in  : UID, 데이터명, 더하거나 뺄 값(더하려면 양수, 빼려면 음수)
        '''
        if not self.dataCheck(1, dataName):
            return None
        if self.type == 'sqlite3':
            self.cur.execute(f'UPDATE {self.db_prefix}_exp SET {dataName}={dataName}+:amount WHERE guild=:guild AND uid=:uid;',{'guild':guild,'uid':uid,'amount':amount})
        else:
            self.cur.execute(f'UPDATE {self.db_prefix}_exp SET {dataName}={dataName}+%s WHERE guild=%s AND uid=%s',(amount, guild, uid))

    def register(self, guild:int, uid:int, now:dt, *, via_voice: bool = False):
        '''회원가입 코드'''
        first_ts = getTimeStamp(now)
        last_ts = getTimeStamp(via_voice_last_call(now)) if via_voice else first_ts
        api_ts = first_ts
        attend_idx = exp_day_index(now)
        if via_voice:
            if self.type == 'sqlite3':
                self.cur.execute(
                    f'INSERT INTO {self.db_prefix}_exp'
                    f'(guild, uid, first_call, last_call, last_api_call, last_attend, chat_count) '
                    f'VALUES(:guild, :uid, :first_ts, :last_ts, :api_ts, :attend_idx, 0);',
                    {
                        'guild': guild, 'uid': uid, 'first_ts': first_ts,
                        'last_ts': last_ts, 'api_ts': api_ts, 'attend_idx': attend_idx,
                    },
                )
            else:
                self.cur.execute(
                    f'INSERT INTO {self.db_prefix}_exp'
                    f'(guild, uid, first_call, last_call, last_api_call, last_attend, chat_count) '
                    f'VALUES(%s, %s, %s, %s, %s, %s, 0);',
                    (guild, uid, first_ts, last_ts, api_ts, attend_idx),
                )
        elif self.type == 'sqlite3':
            self.cur.execute(
                f'INSERT INTO {self.db_prefix}_exp'
                f'(guild, uid, first_call, last_call, last_api_call, last_attend) '
                f'VALUES(:guild, :uid, :ts, :ts, :api_ts, :attend_idx);',
                {
                    'guild': guild, 'uid': uid, 'ts': first_ts,
                    'api_ts': api_ts, 'attend_idx': attend_idx,
                },
            )
        else:
            self.cur.execute(
                f'INSERT INTO {self.db_prefix}_exp'
                f'(guild, uid, first_call, last_call, last_api_call, last_attend) '
                f'VALUES(%s, %s, %s, %s, %s, %s);',
                (guild, uid, first_ts, first_ts, api_ts, attend_idx),
            )
        __logWrite__(guild, uid, 70, [via_voice])

    def global_get(self, uid: int, dataName: GlobalDataNameGet):
        if dataName not in get_args(GlobalDataNameGet):
            return None
        if dataName == 'increase':
            dataName = '(exp-yesterday_exp) AS increase'
        table = f'{self.db_prefix}_global_exp'
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {dataName} FROM {table} WHERE uid=:uid;',
                {'uid': uid},
            )
        else:
            self.cur.execute(
                f'SELECT {dataName} FROM {table} WHERE uid=%s;',
                (uid,),
            )
        result = self.cur.fetchone()
        if result is None:
            raise IndexError('DB > _connectDB.global_get : row not found')
        return result[0]

    def global_set(self, uid: int, dataName: GlobalDataNameSet, amount: int) -> None:
        if dataName not in get_args(GlobalDataNameSet):
            return None
        table = f'{self.db_prefix}_global_exp'
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {table} SET {dataName}=:amount WHERE uid=:uid;',
                {'uid': uid, 'amount': amount},
            )
        else:
            self.cur.execute(
                f'UPDATE {table} SET {dataName}=%s WHERE uid=%s;',
                (amount, uid),
            )

    def global_add(self, uid: int, dataName: GlobalDataNameAdd, amount: int) -> None:
        if dataName not in get_args(GlobalDataNameAdd):
            return None
        table = f'{self.db_prefix}_global_exp'
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {table} SET {dataName}={dataName}+:amount WHERE uid=:uid;',
                {'uid': uid, 'amount': amount},
            )
        else:
            self.cur.execute(
                f'UPDATE {table} SET {dataName}={dataName}+%s WHERE uid=%s;',
                (amount, uid),
            )

    def global_register(self, uid: int, now: dt, *, via_voice: bool = False) -> None:
        first_ts = getTimeStamp(now)
        last_ts = getTimeStamp(via_voice_last_call(now)) if via_voice else first_ts
        attend_idx = exp_day_index(now)
        table = f'{self.db_prefix}_global_exp'
        if self.type == 'sqlite3':
            if via_voice:
                self.cur.execute(
                    f'INSERT OR IGNORE INTO {table}'
                    f'(uid, first_call, last_call, last_api_call, last_attend, chat_count) '
                    f'VALUES(:uid, :first_ts, :last_ts, :api_ts, :attend_idx, 0);',
                    {
                        'uid': uid, 'first_ts': first_ts, 'last_ts': last_ts,
                        'api_ts': first_ts, 'attend_idx': attend_idx,
                    },
                )
            else:
                self.cur.execute(
                    f'INSERT OR IGNORE INTO {table}'
                    f'(uid, first_call, last_call, last_api_call, last_attend) '
                    f'VALUES(:uid, :ts, :ts, :api_ts, :attend_idx);',
                    {'uid': uid, 'ts': first_ts, 'api_ts': first_ts, 'attend_idx': attend_idx},
                )
        else:
            if via_voice:
                self.cur.execute(
                    f'INSERT IGNORE INTO {table}'
                    f'(uid, first_call, last_call, last_api_call, last_attend, chat_count) '
                    f'VALUES(%s, %s, %s, %s, %s, 0);',
                    (uid, first_ts, last_ts, first_ts, attend_idx),
                )
            else:
                self.cur.execute(
                    f'INSERT IGNORE INTO {table}'
                    f'(uid, first_call, last_call, last_api_call, last_attend) '
                    f'VALUES(%s, %s, %s, %s, %s);',
                    (uid, first_ts, first_ts, first_ts, attend_idx),
                )
        __logWrite__(0, uid, 170, [via_voice])

    def global_upsert_voice_session(self, uid: int, guild: int, last_active: int) -> None:
        table = f'{self.db_prefix}_global_voice_session'
        execute_upsert(
            self,
            table=table,
            columns=('uid', 'guild', 'last_active'),
            values={'uid': uid, 'guild': guild, 'last_active': last_active},
            conflict_columns=('uid', 'guild'),
            update_columns=('last_active',),
        )

    def global_delete_voice_session(self, uid: int, guild: int) -> None:
        table = f'{self.db_prefix}_global_voice_session'
        if self.type == 'sqlite3':
            self.cur.execute(
                f'DELETE FROM {table} WHERE uid=:uid AND guild=:guild;',
                {'uid': uid, 'guild': guild},
            )
        else:
            self.cur.execute(
                f'DELETE FROM {table} WHERE uid=%s AND guild=%s;',
                (uid, guild),
            )

    def global_delete_stale_voice_sessions(self, uid: int, before_ts: int) -> None:
        table = f'{self.db_prefix}_global_voice_session'
        if self.type == 'sqlite3':
            self.cur.execute(
                f'DELETE FROM {table} WHERE uid=:uid AND last_active<:before_ts;',
                {'uid': uid, 'before_ts': before_ts},
            )
        else:
            self.cur.execute(
                f'DELETE FROM {table} WHERE uid=%s AND last_active<%s;',
                (uid, before_ts),
            )

    def global_has_active_voice_session(self, uid: int, cutoff_ts: int) -> bool:
        table = f'{self.db_prefix}_global_voice_session'
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT 1 FROM {table} WHERE uid=:uid AND last_active>=:cutoff_ts LIMIT 1;',
                {'uid': uid, 'cutoff_ts': cutoff_ts},
            )
        else:
            self.cur.execute(
                f'SELECT 1 FROM {table} WHERE uid=%s AND last_active>=%s LIMIT 1;',
                (uid, cutoff_ts),
            )
        return self.cur.fetchone() is not None

'''
테이블 구조
CREATE TABLE IF NOT EXISTS "ame_exp" (
    "id"             INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild"          INTEGER NOT NULL,
    "uid"            INTEGER NOT NULL,
    "first_call"     INTEGER NOT NULL,
    "last_call"      INTEGER NOT NULL,
    "last_api_call"  INTEGER NOT NULL,
    "last_attend"    INTEGER DEFAULT 0,
    "total_chat"     INTEGER DEFAULT 0,
    "chat_count"     INTEGER DEFAULT 1,
    "voice_count"    INTEGER DEFAULT 0,
    "day_count"      INTEGER DEFAULT 1,
    "exp"            INTEGER DEFAULT 0,
    "yesterday_exp"  INTEGER DEFAULT 0,
    "yesterday_incr" INTEGER DEFAULT 0,
    "silent"         INTEGER DEFAULT 0,
    UNIQUE(guild, uid)
);

uid : 말 그대로 디코 id
guild : 길드 id
first_call : 유나봇에 등록한 날짜(ms Unix timestamp, INTEGER), 이건 절대로 수정되면 안 됨
last_call : 마지막으로 호출한 시간(ms Unix timestamp, INTEGER)
last_api_call : 마지막으로 채팅/통화 처리 API를 호출한 시간(ms Unix timestamp, INTEGER)
last_attend : 마지막 출석한 경험치일 인덱스 (2020-01-01 KST + EXP_DAY_ROLLOVER)
total_chat : 총 채팅 횟수
chat_count : 점수로 인정되는 채팅 횟수
voice_count : 총 통화 초수 (int(time*10) 해서 소숫점 1자리 Decimal로 저장)
day_count : 출석 일수 (매일 EXP_DAY_ROLLOVER KST 초기화)
exp : 활동점수 raw값
yesterday_exp : 어제의 exp 최종값
yesterday_incr : 어제의 exp 증가값
silent : 멘션 하는지 안 하는지 여부

채팅 한 번 : 2 (45초당 한 번)
통화 중 : 60초마다 1
하루 최초 한 번 : 50

뭔가 채팅이 오면 무조건적으로 event를 발생시켜서
chatCallCalc 함수를 호출
'''

def ensure_schema() -> None:
    # Primary: lib_bot_lifecycle.ensure_core_db_schemas() (부트)
    with _connectDB() as db:
        db.ensure_schema()


def __logWrite__(guild:int, uid:int, task:int, text:list):
    """기록 시각의 KST 달력 월에 이벤트를 추가한다. 길드·사용자가 없으면 0."""
    exp_log.append(exp_log.LOG_DIR, getTimeStamp(getNow()), guild, uid, task, text)


def archive_exp_logs() -> None:
    exp_log.archive_closed(exp_log.LOG_DIR, getNow(), EXP_DAY_ROLLOVER)

DataNameGetOutside = Literal['first_call', 'last_call', 'last_api_call', 'last_attend', 'total_chat', 'chat_count', 'voice_count', 'day_count', 'exp', 'yesterday_exp', 'yesterday_incr', 'silent', 'increase']
GlobalDataNameGetOutside = Literal['first_call', 'last_call', 'last_api_call', 'last_attend', 'total_chat', 'chat_count', 'voice_count', 'day_count', 'exp', 'yesterday_exp', 'yesterday_incr', 'increase']

def getData(guild:int, uid:int, attribute:DataNameGetOutside):
    '''코드가 비슷한 것 같아서 그냥 전부 합쳐버림'''
    with _connectDB() as db:
        try:
            result = db.get(guild, uid, attribute)
        except IndexError:
            result = None
    __logWrite__(guild, uid, 1, [attribute, result])
    return result
    #날짜도 str형으로 반환, 내부에서 작업할 때는 %Y-%m-%d %H:%M:%S.%f%z 형식으로 datetime형으로 변환해야 함


def getGlobalData(uid: int, attribute: GlobalDataNameGetOutside):
    '''글로벌 경험치 테이블에서 uid 기준 단일 속성을 조회한다.'''
    with _connectDB() as db:
        try:
            result = db.global_get(uid, attribute)
        except IndexError:
            result = None
    __logWrite__(0, uid, 101, [attribute, result])
    return result

def ifUserExist(guild:int, uid:int) -> bool:
    '''
    해당 guild에 해당 유저가 존재하는지 확인하는 코드
    '''
    with _connectDB() as db:
        try:
            db.get(guild, uid,'uid')
        except IndexError:
            result = False
        except Exception as e:
            raise e
        else:
            result = True
    __logWrite__(guild, uid, 6, [result])
    return result
        
def __updateLastCallDate__(
    guild: int,
    uid: int,
    date: dt,
    sep: bool = False,
    db: Optional["_connectDB"] = None,
    *,
    in_voice: bool = False,
):
    '''
    채팅 1회 처리: total_chat +1, (통화 중이 아니면) 쿨다운 시 chat_count·last_call 갱신,
    출석일(day_count) 경계(EXP_DAY_ROLLOVER KST) 처리 — last_attend 기준.

    return (출석 관련):
    -1 : 점수가 안 바뀐 경우 (통화방 안에 있거나 쿨타임 안 지났거나 등등)
    0 : 오늘 이미 출석 처리됨(날짜가 바뀌지 않았음)
    1+ : 오늘 첫 출석, restDay(며칠 만에 복귀)
    '''
    def _update(db:_connectDB):
        __logWrite__(guild, uid, 10, [])
        recalc = False
        try:
            last_call = fromTimeStamp(db.get(guild, uid, 'last_call'))
            last_attend = int(db.get(guild, uid, 'last_attend') or 0)
        except IndexError:
            db.register(guild, uid, date)
            last_call = date
            last_attend = exp_day_index(date)
            recalc = True
        except Exception as e:
            raise e
        else:
            if not in_voice and date - last_call >= td(seconds=chatCooltime):
                db.set(guild, uid, 'last_call', getTimeStamp(date))
                db.add(guild, uid, 'chat_count', 1)
                recalc = True
        finally:
            db.set(guild, uid, 'last_api_call', getTimeStamp(date))
            db.add(guild, uid, 'total_chat', 1)

            today_idx = exp_day_index(date)
            if last_attend != today_idx:
                db.add(guild, uid, 'day_count', 1)
                db.set(guild, uid, 'last_attend', today_idx)
                restDay = _rest_days_since_attend(last_attend, today_idx, last_call)
                __logWrite__(guild, uid, 11, [restDay])
                returnArg = restDay
            elif not recalc:
                returnArg = -1
            else:
                returnArg = 0
            if sep:
                __calcFriendlyRate__(guild, uid, db=db)
        return returnArg

    if db is None:
        with _connectDB() as db:
            return _update(db)
    return _update(db)

def __updateVoiceAttendance__(
    guild: int,
    uid: int,
    date: dt,
    db: _connectDB,
) -> int:
    '''
    통화 처리 시 출석일(day_count) 갱신. last_call은 변경하지 않음.
    last_attend로 하루 1회만 출석 처리.

    return:
    0 : 오늘 이미 출석 처리됨
    1+ : 오늘 첫 출석, restDay(며칠 만에 복귀)
    '''
    last_attend = int(db.get(guild, uid, 'last_attend') or 0)
    today_idx = exp_day_index(date)
    if last_attend != today_idx:
        last_call = fromTimeStamp(db.get(guild, uid, 'last_call'))
        db.add(guild, uid, 'day_count', 1)
        db.set(guild, uid, 'last_attend', today_idx)
        restDay = _rest_days_since_attend(last_attend, today_idx, last_call)
        __logWrite__(guild, uid, 12, [restDay])
        return restDay
    return 0


def __ensureGlobalUser__(uid: int, date: dt, db: _connectDB, *, via_voice: bool = False) -> None:
    try:
        db.global_get(uid, 'uid')
    except IndexError:
        db.global_register(uid, date, via_voice=via_voice)


def __isGlobalInVoice__(uid: int, date: dt, db: _connectDB) -> bool:
    cutoff_ts = getTimeStamp(date - td(seconds=globalVoiceSessionTtl))
    db.global_delete_stale_voice_sessions(uid, cutoff_ts)
    return db.global_has_active_voice_session(uid, cutoff_ts)


def __updateGlobalLastCallDate__(uid: int, date: dt, db: _connectDB) -> int:
    recalc = False
    try:
        last_call = fromTimeStamp(db.global_get(uid, 'last_call'))
        last_attend = int(db.global_get(uid, 'last_attend') or 0)
    except IndexError:
        __logWrite__(0, uid, 110, [False])
        db.global_register(uid, date)
        last_call = date
        last_attend = exp_day_index(date)
        recalc = True
    else:
        in_voice = __isGlobalInVoice__(uid, date, db=db)
        __logWrite__(0, uid, 110, [in_voice])
        if not in_voice and date - last_call >= td(seconds=chatCooltime):
            db.global_set(uid, 'last_call', getTimeStamp(date))
            db.global_add(uid, 'chat_count', 1)
            recalc = True
    finally:
        db.global_set(uid, 'last_api_call', getTimeStamp(date))
        db.global_add(uid, 'total_chat', 1)
        today_idx = exp_day_index(date)
        if last_attend != today_idx:
            db.global_add(uid, 'day_count', 1)
            db.global_set(uid, 'last_attend', today_idx)
            restDay = _rest_days_since_attend(last_attend, today_idx, last_call)
            __logWrite__(0, uid, 111, [restDay])
            returnArg = restDay
        elif not recalc:
            returnArg = -1
        else:
            returnArg = 0
    return returnArg


def __updateGlobalVoiceAttendance__(uid: int, date: dt, db: _connectDB) -> int:
    last_attend = int(db.global_get(uid, 'last_attend') or 0)
    today_idx = exp_day_index(date)
    if last_attend != today_idx:
        last_call = fromTimeStamp(db.global_get(uid, 'last_call'))
        db.global_add(uid, 'day_count', 1)
        db.global_set(uid, 'last_attend', today_idx)
        restDay = _rest_days_since_attend(last_attend, today_idx, last_call)
        __logWrite__(0, uid, 112, [restDay])
        return restDay
    return 0


def __calcFriendlyRate__(guild:int, uid:int, db:Optional["_connectDB"]=None) -> int:
    '''
    현재 기록된 command_count, day_count, total_penalty의 값을 기준으로 friendly_rate를 계산하고 올바른 값으로 갱신하는 함수
    return값은 변경된 friendly_rate
    '''
    def _calc(db:_connectDB) -> int:
        chat_count : int = db.get(guild, uid, 'chat_count')
        day_count : int = db.get(guild, uid, 'day_count')
        voice_count : int = db.get(guild, uid, 'voice_count')
        friendly_rate = chat_count * chatPoint + int(voice_count / voiceCooltime / 10) * voicePoint + day_count * dayPoint
        __logWrite__(guild, uid, 20, [friendly_rate])
        db.set(guild, uid, 'exp', friendly_rate)
        return friendly_rate

    if db is None:
        with _connectDB() as db:
            return _calc(db)
    return _calc(db)


def __calcGlobalFriendlyRate__(uid: int, db: _connectDB) -> int:
    chat_count: int = db.global_get(uid, 'chat_count')
    day_count: int = db.global_get(uid, 'day_count')
    voice_count: int = db.global_get(uid, 'voice_count')
    friendly_rate = chat_count * chatPoint + int(voice_count / voiceCooltime / 10) * voicePoint + day_count * dayPoint
    __logWrite__(0, uid, 120, [friendly_rate])
    db.global_set(uid, 'exp', friendly_rate)
    return friendly_rate

def getAllData(guild: int, todayOrder: bool = False) -> list[tuple[int, int, int, int]]:
    '''
    길드 내 활동 경험치 랭킹용 데이터.
    HanulBot Exp.getAllData 참고: exp_ashita → yesterday_exp.

    Returns:
        (uid, exp, increase, day_count) — increase = exp - yesterday_exp
    '''
    __logWrite__(guild, 0, 80, [todayOrder])
    with _connectDB() as db:
        table = f'{db.db_prefix}_exp'
        if todayOrder:
            order = 'increase DESC, uid ASC'
        else:
            order = 'exp DESC, uid ASC'
        if db.type == 'sqlite3':
            db.cur.execute(
                f'SELECT uid, exp, (exp - yesterday_exp) AS increase, day_count '
                f'FROM {table} WHERE guild=:guild ORDER BY {order};',
                {'guild': guild},
            )
        else:
            db.cur.execute(
                f'SELECT uid, exp, (exp - yesterday_exp) AS increase, day_count '
                f'FROM {table} WHERE guild=%s ORDER BY {order};',
                (guild,),
            )
        data = db.cur.fetchall()
    __logWrite__(guild, 0, 81, [])
    return data


def getYesterdayData(guild: int, todayOrder: bool = False) -> list[tuple[int, int, int, int]]:
    '''
    길드 내 **어제** 활동 경험치 랭킹용 데이터.
    HanulBot Exp.getYesterdayData + hanul_exp_final 참고:
    exp_final → yesterday_exp, increase → yesterday_incr (dailyDBInit 시 스냅샷).

    Returns:
        (uid, yesterday_exp, yesterday_incr, day_count)
    '''
    __logWrite__(guild, 0, 85, [todayOrder])
    with _connectDB() as db:
        table = f'{db.db_prefix}_exp'
        if todayOrder:
            order = 'yesterday_incr DESC, uid ASC'
        else:
            order = 'yesterday_exp DESC, uid ASC'
        if db.type == 'sqlite3':
            db.cur.execute(
                f'SELECT uid, yesterday_exp, yesterday_incr, day_count '
                f'FROM {table} WHERE guild=:guild ORDER BY {order};',
                {'guild': guild},
            )
        else:
            db.cur.execute(
                f'SELECT uid, yesterday_exp, yesterday_incr, day_count '
                f'FROM {table} WHERE guild=%s ORDER BY {order};',
                (guild,),
            )
        data = db.cur.fetchall()
    __logWrite__(guild, 0, 86, [])
    return data


def dailyDBInit(*, force: bool = False) -> bool:
    '''
    DB 일일 초기화. yesterday_incr = exp - yesterday_exp, yesterday_exp = exp.

    같은 경험치일에 두 번 실행하면 두 번째가 yesterday_incr를 0으로 덮으므로,
    {prefix}_exp_daily_init 로 하루 1회만 수행한다. force=True 면 다시 스냅샷.

    Returns:
        True  if the snapshot ran, False if skipped as already done today.
    '''
    today_idx = exp_day_index(getNow())
    now_ts = getTimeStamp(getNow())
    __logWrite__(0, 0, 90, [today_idx, int(force)])
    ran = False
    with _connectDB() as db:
        db._ensure_daily_init_schema()
        meta = f'{db.db_prefix}_exp_daily_init'
        if db.type == 'sqlite3':
            db.cur.execute(
                f'INSERT OR IGNORE INTO {meta} (id, day_index, updated_at) VALUES (1, -1, 0);'
            )
            if force:
                db.cur.execute(
                    f'UPDATE {meta} SET day_index=?, updated_at=? WHERE id=1;',
                    (today_idx, now_ts),
                )
            else:
                db.cur.execute(
                    f'UPDATE {meta} SET day_index=?, updated_at=? '
                    f'WHERE id=1 AND day_index<>?;',
                    (today_idx, now_ts, today_idx),
                )
        else:
            db.cur.execute(
                f'INSERT IGNORE INTO {meta} (id, day_index, updated_at) VALUES (1, -1, 0);'
            )
            if force:
                db.cur.execute(
                    f'UPDATE {meta} SET day_index=%s, updated_at=%s WHERE id=1;',
                    (today_idx, now_ts),
                )
            else:
                db.cur.execute(
                    f'UPDATE {meta} SET day_index=%s, updated_at=%s '
                    f'WHERE id=1 AND day_index<>%s;',
                    (today_idx, now_ts, today_idx),
                )
        claimed = force or (db.cur.rowcount or 0) > 0
        if claimed:
            db.cur.execute(
                f'UPDATE {db.db_prefix}_exp SET yesterday_incr=(exp-yesterday_exp);'
            )
            db.cur.execute(f'UPDATE {db.db_prefix}_exp SET yesterday_exp=exp;')
            db.cur.execute(
                f'UPDATE {db.db_prefix}_global_exp SET yesterday_incr=(exp-yesterday_exp);'
            )
            db.cur.execute(f'UPDATE {db.db_prefix}_global_exp SET yesterday_exp=exp;')
            ran = True
    __logWrite__(0, 0, 91, ['ok' if ran else 'skip', today_idx])
    return ran


def listProfileCandidateUids() -> list[int]:
    '''경험치 테이블에 등장하는 uid 목록 (글로벌 ∪ 서버). 프로필 일일 갱신용.'''
    with _connectDB() as db:
        global_table = f'{db.db_prefix}_global_exp'
        server_table = f'{db.db_prefix}_exp'
        uids: set[int] = set()
        try:
            db.cur.execute(f'SELECT uid FROM {global_table};')
            uids.update(int(r[0]) for r in db.cur.fetchall())
        except Exception:
            pass
        try:
            db.cur.execute(f'SELECT DISTINCT uid FROM {server_table};')
            uids.update(int(r[0]) for r in db.cur.fetchall())
        except Exception:
            pass
    return sorted(uids)


def upsertUserProfile(
    uid: int,
    *,
    username: str,
    global_name: str | None,
    avatar_hash: str | None,
    updated_at: int | None = None,
) -> None:
    '''Discord 닉네임/아바타 캐시를 upsert (웹 순위표 표시용).'''
    if updated_at is None:
        updated_at = getTimeStamp(getNow())
    with _connectDB() as db:
        table = f'{db.db_prefix}_user_profile'
        execute_upsert(
            db,
            table=table,
            columns=['uid', 'username', 'global_name', 'avatar_hash', 'updated_at'],
            values={
                'uid': uid,
                'username': username or '',
                'global_name': global_name,
                'avatar_hash': avatar_hash,
                'updated_at': updated_at,
            },
            conflict_columns=['uid'],
            update_columns=['username', 'global_name', 'avatar_hash', 'updated_at'],
        )
    __logWrite__(0, uid, 93, [username, global_name, avatar_hash])


def getUserProfiles(uids: list[int]) -> dict[int, tuple[str, str | None, str | None, int]]:
    '''uid -> (username, global_name, avatar_hash, updated_at_ms).'''
    if not uids:
        return {}
    with _connectDB() as db:
        table = f'{db.db_prefix}_user_profile'
        out: dict[int, tuple[str, str | None, str | None, int]] = {}
        # SQLite/MySQL 모두 IN 절 사용
        chunk = 400
        for i in range(0, len(uids), chunk):
            part = uids[i : i + chunk]
            placeholders = ','.join(['%s' if db.type != 'sqlite3' else '?'] * len(part))
            if db.type == 'sqlite3':
                db.cur.execute(
                    f'SELECT uid, username, global_name, avatar_hash, updated_at '
                    f'FROM {table} WHERE uid IN ({placeholders});',
                    part,
                )
            else:
                db.cur.execute(
                    f'SELECT uid, username, global_name, avatar_hash, updated_at '
                    f'FROM {table} WHERE uid IN ({placeholders});',
                    tuple(part),
                )
            for row in db.cur.fetchall():
                out[int(row[0])] = (
                    row[1] or '',
                    row[2],
                    row[3],
                    int(row[4] or 0),
                )
    return out


def logDailyInitExp(loop_count: int, next_iteration) -> None:
    '''daily_init_exp 태스크 실행 로그 (task 92).'''
    __logWrite__(0, 0, 92, [loop_count, str(next_iteration)])

def voiceCallAdd(guild:int, uid:int, amount:int, date: Optional[dt] = None) -> Optional[int]:
    '''
    voice_count를 amount만큼 더하고 exp를 재계산하는 함수.
    유저가 없으면 통화 경로로 회원가입·출석 처리 후 voice_count 반영.
    last_call은 통화 처리·출석 시 갱신하지 않음.
    '''
    if amount <= 0:
        return None
    if date is None:
        date = getNow()
    __logWrite__(guild, uid, 50, [amount])
    with _connectDB() as db:
        try:
            db.get(guild, uid, 'uid')
        except IndexError:
            db.register(guild, uid, date, via_voice=True)
        else:
            __updateVoiceAttendance__(guild, uid, date, db)
        db.set(guild, uid, 'last_api_call', getTimeStamp(date))
        db.add(guild, uid, 'voice_count', amount)
        server_rate = __calcFriendlyRate__(guild, uid, db=db)

        try:
            db.global_get(uid, 'uid')
        except IndexError:
            db.global_register(uid, date, via_voice=True)
        else:
            __updateGlobalVoiceAttendance__(uid, date, db)
        db.global_set(uid, 'last_api_call', getTimeStamp(date))
        db.global_add(uid, 'voice_count', amount)
        __calcGlobalFriendlyRate__(uid, db=db)

        if _consumeGlobalVoiceStopPair(uid, guild, date):
            db.global_delete_voice_session(uid, guild)
        else:
            db.global_upsert_voice_session(uid, guild, getTimeStamp(date))
        return server_rate

def touchLastApiCall(guild: int, uid: int, date: Optional[dt] = None) -> None:
    '''
    채팅/통화 처리 API 호출 시각(last_api_call)을 갱신한다.
    유저가 없으면 통화 경로 회원가입(via_voice=True)으로 생성한다.
    '''
    if date is None:
        date = getNow()
    with _connectDB() as db:
        try:
            db.get(guild, uid, 'uid')
        except IndexError:
            db.register(guild, uid, date, via_voice=True)
        else:
            db.set(guild, uid, 'last_api_call', getTimeStamp(date))

        __ensureGlobalUser__(uid, date, db, via_voice=True)
        db.global_set(uid, 'last_api_call', getTimeStamp(date))
        _setGlobalVoiceStopPair(uid, guild, date)
        db.global_upsert_voice_session(uid, guild, getTimeStamp(date))

def clearVoicePresence(guild: int, uid: int) -> None:
    '''통화방을 나갔을 때 글로벌 통화 중 표시를 지운다.'''
    with _connectDB() as db:
        db.global_delete_voice_session(uid, guild)

def manualAttend(guild: int, uid: int, date: Optional[dt] = None) -> int:
    '''
    수동 출석: day_count·last_attend·last_api_call만 갱신한다 (chatCallCalc 미사용).
    last_call은 via_voice_last_call(now) 과 동일하게 맞춘다(쿨타임 호환).

    return:
    0 : 오늘 이미 출석 처리됨
    1+ : 오늘 첫 출석, restDay(며칠 만에 복귀)
    '''
    if date is None:
        date = getNow()
    today_idx = exp_day_index(date)
    api_ts = getTimeStamp(date)
    last_ts = getTimeStamp(via_voice_last_call(date))
    with _connectDB() as db:
        try:
            last_attend = int(db.get(guild, uid, 'last_attend') or 0)
            last_call = fromTimeStamp(db.get(guild, uid, 'last_call'))
        except IndexError:
            db.register(guild, uid, date, via_voice=True)
            __ensureGlobalUser__(uid, date, db, via_voice=True)
            __logWrite__(guild, uid, 13, [1])
            return 1

        if last_attend == today_idx:
            return 0

        db.add(guild, uid, 'day_count', 1)
        db.set(guild, uid, 'last_attend', today_idx)
        db.set(guild, uid, 'last_call', last_ts)
        db.set(guild, uid, 'last_api_call', api_ts)
        rest_day = _rest_days_since_attend(last_attend, today_idx, last_call)
        __logWrite__(guild, uid, 13, [rest_day])

        try:
            g_last_attend = int(db.global_get(uid, 'last_attend') or 0)
        except IndexError:
            db.global_register(uid, date, via_voice=True)
        else:
            if g_last_attend != today_idx:
                db.global_add(uid, 'day_count', 1)
                db.global_set(uid, 'last_attend', today_idx)
            db.global_set(uid, 'last_call', last_ts)
            db.global_set(uid, 'last_api_call', api_ts)
            __logWrite__(0, uid, 113, [rest_day])

        return rest_day

def getInactiveUsersByLastApi(guild: int, before_ts: int) -> list[tuple[int, int]]:
    '''
    last_api_call 이 before_ts 이하인 유저 목록을 (uid, last_api_call)로 반환.
    '''
    with _connectDB() as db:
        table = f'{db.db_prefix}_exp'
        if db.type == 'sqlite3':
            db.cur.execute(
                f'SELECT uid, last_api_call FROM {table} '
                f'WHERE guild=:guild AND last_api_call<=:before_ts '
                f'ORDER BY last_api_call ASC;',
                {'guild': guild, 'before_ts': before_ts},
            )
        else:
            db.cur.execute(
                f'SELECT uid, last_api_call FROM {table} '
                f'WHERE guild=%s AND last_api_call<=%s '
                f'ORDER BY last_api_call ASC;',
                (guild, before_ts),
            )
        return [(int(uid), int(last_api_call)) for uid, last_api_call in db.cur.fetchall()]

def chatCallCalc(
    guild: int,
    uid: int,
    date: dt,
    *,
    in_voice: bool = False,
) -> int:
    '''
    __updateLastCallDate__을 호출해서 날짜 관련 계산을 하고
    __calcFriendlyRate__를 호출해서 친밀도를 계산한 다음
    모든 것을 커밋하고 sql 연결을 닫고
    lastCallArg만 리턴하는 함수
    lastCallArg : __updateLastCallDate__의 주석 참고
    '''
    __logWrite__(guild, uid, 60, [in_voice])
    _clearStaleGlobalVoiceStopPair(date)
    with _connectDB() as db:
        lastCallArg = __updateLastCallDate__(guild, uid, date, db=db, in_voice=in_voice)
        globalArg = __updateGlobalLastCallDate__(uid, date, db=db)
        if lastCallArg != -1:
            __calcFriendlyRate__(guild, uid, db=db)
        if globalArg != -1:
            __calcGlobalFriendlyRate__(uid, db=db)
    __logWrite__(guild, uid, 61, [lastCallArg])
    return lastCallArg

def changeSilentStatus(guild:int, uid:int, arg):
    '''
    매일 첫 채팅 시의 멘션을 켜고 끄는 기능
    uid : 유저의 id
    arg : 켤 건지(True) 끌 건지(False) 아니면 현재 silent를 조회해 반대로 바꿀건지(None)
    리턴값 : 껐으면 0, 켰으면 1, DB에 오류가 발생했으면 -1
    '''
    with _connectDB() as db:
        try:
            try:
                db.get(guild, uid, 'uid')
            except IndexError:
                db.register(guild, uid, getNow(), via_voice=True)
            if arg is None:
                current = db.get(guild, uid, 'silent')
                arg = 0 if current else 1
            else:
                arg = 1 if arg else 0
            db.set(guild, uid, 'silent', arg)
        except Exception:
            return -1
    return arg
    
