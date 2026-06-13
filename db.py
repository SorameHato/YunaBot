import pathlib, json
from typing import Literal, get_args

def _resolve_db_path(path_str: str) -> pathlib.Path:
    path = pathlib.Path(path_str)
    if path.is_absolute():
        return path
    return pathlib.Path(__file__).parent.joinpath(path)

# db_json을 불러와서, 각 타입 별 설정을 불러옴
with pathlib.Path(__file__).parent.joinpath('db.json').open('r',encoding='utf-8') as db_json_file:
    db_json : dict = json.load(db_json_file)
DBName = Literal['dailyInform', 'exp', 'setting']

db_type = db_json['type'].lower()
db_prefix = db_json.get('prefix','ame')
if db_type == 'sqlite3':
    import sqlite3
    _default_sqlite_path = db_json.get('location', 'db.db')
    _locations_raw: dict = db_json.get('locations', {})
    db_locations: dict[str, pathlib.Path] = {}
    for name in get_args(DBName):
        db_locations[name] = _resolve_db_path(_locations_raw.get(name, _default_sqlite_path))
elif db_type == 'mysql':
    import pymysql
    db_host = db_json.get('host','localhost')
    db_port = int(db_json.get('port',3306))
    db_user = db_json['user']
    db_password = db_json['password']
    db_database = db_json.get('database','sware_bot')
    db_charset = db_json.get('charset','utf-8')

class _connectDB_raw:
    '''
    DB에 연결한 다음 con과 cur을 return하고, 자동으로 commit과 close를 하는 클래스<br>
    con, cur은 db.con, db.cur 로 접근할 수 있다.<br>
    sqlite3이랑 pymysql이랑 너무 달라서 get update 등등도 함수 내부에 만들어야 할 듯
    '''
    def __init__(self,db_name:DBName):
        self.type = db_type
        self.db_prefix = db_prefix
        self.con = (sqlite3.connect(db_locations[db_name]) if db_type == 'sqlite3' else pymysql.connect(host=db_host,port=db_port,
                    user=db_user,password=db_password,database=db_database,charset=db_charset) if db_type == 'mysql' else None)
        if self.con is None:
            raise ConnectionError('DB > _connectDB : Failed to connect DB')
        self.cur = self.con.cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type:
            self.con.rollback()
        else:
            self.con.commit()
        self.con.close()