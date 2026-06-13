import sys, pathlib, os, json, csv
from typing import Literal, Optional, get_args
from datetime import datetime as dt
from datetime import timezone as tz
from datetime import timedelta as td
from datetime import time
from db import _connectDB_raw
chatPoint = 2
chatCooltime = 75
voicePoint = 1
voiceCooltime = 45  # exp 산식: voice_count/(voiceCooltime*10) 회당 voicePoint
voiceTickInterval = 15  # 통화 중 voice_count 주기 반영 간격(초)
voiceTickAmount = 150  # 주기마다 voice_count 가산 (15초×10)
dayPoint = 40

# KST 기준 경험치·출석 날짜 변경 시각 (일일 초기화·day_count 경계)
EXP_TZ = tz(td(hours=9))
EXP_UTC = tz(td(seconds=0))
EXP_DAY_ROLLOVER = time(5, 15)


def exp_day_start(date: dt) -> dt:
    '''주어진 시각이 속하는 경험치 일일 구간의 시작 시각(EXP_DAY_ROLLOVER KST).'''
    base = dt(
        date.year,
        date.month,
        date.day,
        EXP_DAY_ROLLOVER.hour,
        EXP_DAY_ROLLOVER.minute,
        EXP_DAY_ROLLOVER.second,
        tzinfo=EXP_TZ,
    )
    if date.time() >= EXP_DAY_ROLLOVER:
        return base
    return base - td(days=1)


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

DataNameGet = Literal['guild', 'uid', 'first_call', 'last_call', 'total_chat', 'chat_count', 'voice_count', 'day_count', 'exp', 'yesterday_exp', 'yesterday_incr', 'silent', 'increase']
DataNameSet = Literal['last_call', 'total_chat', 'chat_count', 'voice_count', 'day_count', 'exp', 'yesterday_exp', 'yesterday_incr', 'silent']
DataNameAdd = Literal['total_chat', 'chat_count', 'voice_count', 'day_count', 'exp']
DoMany = Literal['get','add','set']

def getTimeStamp(now:dt) -> int:
    return int(now.timestamp() * 1000)

def fromTimeStamp(ts:int) -> dt:
    return dt.fromtimestamp(ts/1000,tz=EXP_TZ)

def getNow() -> dt:
    return dt.now(tz=EXP_TZ)

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

    def register(self, guild:int, uid:int, now:dt):
        '''회원가입 코드'''
        ts = getTimeStamp(now)
        if self.type == 'sqlite3':
            self.cur.execute(
                f'INSERT INTO {self.db_prefix}_exp(guild, uid, first_call, last_call) '
                f'VALUES(:guild, :uid, :ts, :ts);',
                {'guild': guild, 'uid': uid, 'ts': ts},
            )
        else:
            self.cur.execute(
                f'INSERT INTO {self.db_prefix}_exp(guild, uid, first_call, last_call) '
                f'VALUES(%s, %s, %s, %s);',
                (guild, uid, ts, ts),
            )
        __logWrite__(guild, uid, 70, [])

'''
테이블 구조
CREATE TABLE IF NOT EXISTS "ame_exp" (
    "id"             INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild"          INTEGER NOT NULL,
    "uid"            INTEGER NOT NULL,
    "first_call"     INTEGER NOT NULL,
    "last_call"      INTEGER NOT NULL,
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
total_chat : 총 채팅 횟수
chat_count : 점수로 인정되는 채팅 횟수
voice_count : 총 통화 초수 (int(time*10) 해서 소숫점 1자리 Decimal로 저장)
day_count : 출석 일수 (매일 EXP_DAY_ROLLOVER KST 초기화)
exp : 활동점수 raw값
yesterday_exp : 어제의 exp 최종값
yesterday_incr : 어제의 exp 증가값
silent : 멘션 하는지 안 하는지 여부

채팅 한 번 : 2 (75초당 한 번)
통화 중 : 45초마다 1
하루 최초 한 번 : 40

뭔가 채팅이 오면 무조건적으로 event를 발생시켜서
chatCallCalc 함수를 호출
'''

def ensure_schema() -> None:
    with _connectDB() as db:
        db.ensure_schema()


def __logWrite__(guild:int, uid:int, task:int, text:list):
    '''
    로그에 데이터를 기록하는 함수
    시각(ms Unix timestamp), guild, uid, task(ID), 변수… 형식의 csv로 저장된다.
    guild·uid가 해당 없으면 0.
    task : 로그 메시지 ID (변수 없으면 text는 빈 리스트)
    text : ID별 부가 변수 (순서 고정)
    '''
    with open(pathlib.PurePath(__file__).with_name('log_test.csv'),'a',encoding='utf-8',newline='') as a:
        writer = csv.writer(a)
        row = [getTimeStamp(getNow()), guild, uid, task]
        row.extend(text)
        writer.writerow(row)

DataNameGetOutside = Literal['first_call', 'last_call', 'total_chat', 'chat_count', 'voice_count', 'day_count', 'exp', 'yesterday_exp', 'yesterday_incr', 'silent', 'increase']

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
    출석일(day_count) 경계(EXP_DAY_ROLLOVER KST) 처리.

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
        except IndexError:
            db.register(guild, uid, date)
            last_call = date
            recalc = True
        except Exception as e:
            raise e
        else:
            if not in_voice and date - last_call >= td(seconds=chatCooltime):
                db.set(guild, uid, 'last_call', getTimeStamp(date))
                db.add(guild, uid, 'chat_count', 1)
                recalc = True
        finally:
            db.add(guild, uid, 'total_chat', 1)

            todayStart = exp_day_start(date)
            if last_call < todayStart:
                db.add(guild, uid, 'day_count', 1)
                restDay = abs((last_call - todayStart).days)
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


def dailyDBInit():
    '''DB 일일 초기화 코드'''
    __logWrite__(0, 0, 90, [])
    with _connectDB() as db:
        db.cur.execute(f'UPDATE {db.db_prefix}_exp SET yesterday_incr=(exp-yesterday_exp);')
        db.cur.execute(f'UPDATE {db.db_prefix}_exp SET yesterday_exp=exp;')
    __logWrite__(0, 0, 91, [])

def voiceCallAdd(guild:int, uid:int, amount:int) -> Optional[int]:
    '''
    voice_count를 amount만큼 더하고 exp를 재계산하는 함수
    유저가 DB에 없으면 None을 반환
    '''
    if amount <= 0:
        return None
    __logWrite__(guild, uid, 50, [amount])
    with _connectDB() as db:
        try:
            db.get(guild, uid, 'uid')
        except IndexError:
            return None
        db.add(guild, uid, 'voice_count', amount)
        return __calcFriendlyRate__(guild, uid, db=db)

def chatCallCalc(
    guild: int,
    uid: int,
    date: dt,
    *,
    in_voice: bool = False,
) -> tuple[int, int]:
    '''
    __updateLastCallDate__을 호출해서 날짜 관련 계산을 하고
    __calcFriendlyRate__를 호출해서 친밀도를 계산한 다음
    모든 것을 커밋하고 sql 연결을 닫고
    친밀도와 lastCallArg을 리턴하는 함수
    return값은 두 개! friendlyRateArg, lastCallArg = chatCallCalc(uid, dt) 이런 식으로 적어야 함
    friendlyRateArg : 변경된 경험치
    lastCallArg : __updateLastCallDate__의 주석 참고
    '''
    __logWrite__(guild, uid, 60, [in_voice])
    with _connectDB() as db:
        lastCallArg = __updateLastCallDate__(guild, uid, date, db=db, in_voice=in_voice)
        if lastCallArg != -1:
            __calcFriendlyRate__(guild, uid, db=db)
    __logWrite__(guild, uid, 61, [lastCallArg])
    return lastCallArg

def changeSilentStatus(guild:int, uid:int, arg=None):
    '''
    매일 첫 채팅 시의 멘션을 켜고 끄는 기능
    uid : 유저의 id
    arg : 켤 건지(True) 끌 건지(False) 아니면 반대로 바꿀건지(None)
    리턴값 : 껐으면 0, 켰으면 1, 오류가 발생했으면 -1(arg가 bool인 경우), -2(arg가 None인 경우)
    '''
    if arg is None:
        with _connectDB() as db:
            try:
                silentStatus = db.get(guild, uid, 'silent')
            except IndexError:
                return -2
            if silentStatus is None:
                return -2
            db.set(guild, uid, 'silent',0 if silentStatus == 1 else 1)
            return 0 if silentStatus == 1 else 1
    else:
        if arg: arg = 1
        else: arg = 0
        with _connectDB() as db:
            try:
                db.set(guild, uid, 'silent', arg)
            except Exception:
                return -1
        return arg
    
