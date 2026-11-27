"""Versioned, ordered EXP log storage, independent of the EXP database."""

from __future__ import annotations

import csv
import gzip
import heapq
import io
import itertools
import json
import logging
import os
import re
import struct
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path


LOG_DIR = Path(__file__).with_name('exp_logs')
LEGACY_LOG = Path(__file__).with_name('log_test.csv')
_OLD_TOOL_DEFAULT = Path(r'C:\Users\ghwls\Documents\Programming\log_test.csv')
KST = timezone(timedelta(hours=9))
INIT_TASKS = frozenset({90, 91, 92})
_MAGIC = b'KEXP'
_HEADER = struct.Struct('<4sH')
_VERSION = 1
_PREFIX = struct.Struct('<I')
_RECORD = struct.Struct('<QqQQHH')
_INTEGER = struct.Struct('<q')
_FOOTER = struct.Struct('<I4s')
_ARCHIVE_MAGIC = b'KEXA'
_ARCHIVE_HEADER = struct.Struct('<4sHH')
_INDEX_VERSION = 1
_BLOCK_RECORDS = 4096
_MONTH_FILE = re.compile(r'(\d{4}-(?:0[1-9]|1[0-2]))\.bin(?:\.gz)?\Z')


class LogError(ValueError):
    """Invalid or unsupported EXP log."""


@dataclass(frozen=True, slots=True)
class Event:
    seq: int
    ts: int
    guild: int
    uid: int
    task: int
    fields: tuple[int | str | bool | None, ...] = ()

    def first_field_text(self) -> str:
        if not self.fields or self.fields[0] is None:
            return ''
        return str(self.fields[0])

    def csv_row(self) -> list[str]:
        fields = ['' if value is None else str(value) for value in self.fields]
        return [str(self.ts), str(self.guild), str(self.uid), str(self.task), *fields]


@dataclass(frozen=True, slots=True)
class InitMarker:
    seq: int
    ts: int
    task: int


def month_of(ts: int) -> str:
    return datetime.fromtimestamp(ts // 1000, KST).strftime('%Y-%m')


def resolve_log(path: Path | None = None) -> Path:
    if path is not None:
        return path
    if LOG_DIR.is_dir():
        return LOG_DIR
    if LEGACY_LOG.is_file() or not _OLD_TOOL_DEFAULT.is_file():
        return LEGACY_LOG
    return _OLD_TOOL_DEFAULT


def _encode_fields(fields) -> bytes:
    parts = []
    for value in fields:
        if value is None:
            parts.append(b'n')
        elif isinstance(value, bool):
            parts.append(b't' if value else b'f')
        elif isinstance(value, int):
            parts.append(b'i' + _INTEGER.pack(value))
        elif isinstance(value, str):
            raw = value.encode('utf-8')
            parts.append(b's' + _PREFIX.pack(len(raw)) + raw)
        else:
            raise TypeError(f'unsupported EXP log field: {type(value).__name__}')
    return b''.join(parts)


def write_event(stream, event: Event) -> None:
    payload = _RECORD.pack(
        event.seq, event.ts, event.guild, event.uid, event.task, len(event.fields),
    ) + _encode_fields(event.fields)
    size = len(payload)
    stream.write(_PREFIX.pack(size) + payload + _FOOTER.pack(size, _MAGIC))


def write_header(stream) -> None:
    stream.write(_HEADER.pack(_MAGIC, _VERSION))


def _check_header(stream) -> None:
    header = stream.read(_HEADER.size)
    if header != _HEADER.pack(_MAGIC, _VERSION):
        raise LogError('invalid EXP log header or unsupported version')


def _decode_fields(payload: bytes, pos: int, count: int) -> tuple[tuple, int]:
    fields = []
    for _ in range(count):
        kind = payload[pos]
        pos += 1
        if kind == ord('i'):
            fields.append(_INTEGER.unpack_from(payload, pos)[0])
            pos += _INTEGER.size
        elif kind == ord('s'):
            size = _PREFIX.unpack_from(payload, pos)[0]
            pos += _PREFIX.size
            fields.append(payload[pos:pos + size].decode('utf-8'))
            pos += size
        elif kind in b'ntf':
            fields.append({ord('n'): None, ord('t'): True, ord('f'): False}[kind])
        else:
            raise LogError(f'unknown EXP log field type {kind}')
    return tuple(fields), pos


def _decode(payload: bytes) -> Event:
    try:
        seq, ts, guild, uid, task, count = _RECORD.unpack_from(payload)
        fields, pos = _decode_fields(payload, _RECORD.size, count)
        if pos != len(payload) or not seq:
            raise LogError('invalid EXP log record')
    except (IndexError, UnicodeError, struct.error) as exc:
        raise LogError('invalid EXP log record') from exc
    return Event(seq, ts, guild, uid, task, fields)


def _records(stream, end: int, *, allow_torn_tail: bool = False):
    while stream.tell() < end:
        start = stream.tell()
        raw_size = stream.read(_PREFIX.size)
        if len(raw_size) == _PREFIX.size:
            size = _PREFIX.unpack(raw_size)[0]
            if size + _FOOTER.size <= end - stream.tell():
                payload = stream.read(size)
                footer = stream.read(_FOOTER.size)
                if footer != _FOOTER.pack(size, _MAGIC):
                    raise LogError('invalid EXP log record footer')
                yield _decode(payload)
                continue
        if allow_torn_tail:
            stream.seek(start)
            return
        raise LogError('truncated EXP log record')


def _previous(stream, end: int) -> Event:
    """Read one framed record backwards and leave the stream at its start."""
    if end < _HEADER.size + _PREFIX.size + _RECORD.size + _FOOTER.size:
        raise LogError('invalid EXP log record position')
    stream.seek(end - _FOOTER.size)
    size, magic = _FOOTER.unpack(stream.read(_FOOTER.size))
    start = end - _FOOTER.size - size - _PREFIX.size
    if magic != _MAGIC or start < _HEADER.size:
        raise LogError('invalid EXP log record footer')
    stream.seek(start)
    if stream.read(_PREFIX.size) != _PREFIX.pack(size):
        raise LogError('invalid EXP log record length')
    event = _decode(stream.read(size))
    stream.seek(start)
    return event


def _active_tail(stream) -> tuple[int, int]:
    """Return the end and sequence of the last complete record."""
    stream.seek(0, os.SEEK_END)
    end = stream.tell()
    if end < _HEADER.size:
        stream.seek(0)
        if _HEADER.pack(_MAGIC, _VERSION).startswith(stream.read()):
            return 0, 0
        raise LogError('invalid partial EXP log header')
    stream.seek(0)
    _check_header(stream)
    if end == _HEADER.size:
        return end, 0
    try:
        return end, _previous(stream, end).seq
    except LogError:
        stream.seek(_HEADER.size)
        seq = 0
        for event in _records(stream, end, allow_torn_tail=True):
            seq = event.seq
        return stream.tell(), seq


def _active_events(stream, end: int, after: int):
    if not end:
        return
    start = _HEADER.size
    if after:
        start = end
        while start > _HEADER.size:
            event = _previous(stream, start)
            if event.seq <= after:
                break
            start = stream.tell()
    stream.seek(start)
    yield from _records(stream, end)


@contextmanager
def store_lock(path: Path):
    """Serialize appends and file publication across bot and admin processes."""
    with path.open('a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _months(directory: Path) -> list[str]:
    return sorted({
        match[1] for path in directory.iterdir() if (match := _MONTH_FILE.fullmatch(path.name))
    })


def _identity(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns


def sync_directory(path: Path) -> None:
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_json(path: Path, obj) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.part', delete=False) as stream:
        temp = Path(stream.name)
    try:
        with temp.open('w', encoding='utf-8') as stream:
            json.dump(obj, stream, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        sync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _block(events: list[Event], offset: int, size: int) -> dict:
    latest = next(((e.seq, e.ts, e.task) for e in reversed(events) if e.task in INIT_TASKS), None)
    return {
        'offset': offset, 'size': size, 'count': len(events),
        'first': events[0].seq, 'last': events[-1].seq,
        'min_ts': min(e.ts for e in events), 'max_ts': max(e.ts for e in events),
        'init': latest,
    }


def _encode_block(events: list[Event]) -> bytes:
    """Group similar fields so gzip can compress them across adjacent events."""
    count = len(events)
    pairs = list(itertools.pairwise(events))
    uint64 = struct.Struct(f'<{count}Q')
    int64 = struct.Struct(f'<{count}q')
    uint16 = struct.Struct(f'<{count}H')
    return b''.join((
        _ARCHIVE_HEADER.pack(_ARCHIVE_MAGIC, _VERSION, count),
        uint64.pack(events[0].seq, *(b.seq - a.seq for a, b in pairs)),
        int64.pack(events[0].ts, *(b.ts - a.ts for a, b in pairs)),
        uint64.pack(*(event.guild for event in events)),
        uint64.pack(*(event.uid for event in events)),
        uint16.pack(*(event.task for event in events)),
        uint16.pack(*(len(event.fields) for event in events)),
        *(_encode_fields(event.fields) for event in events),
    ))


def _decode_block(raw: bytes) -> list[Event]:
    try:
        magic, version, count = _ARCHIVE_HEADER.unpack_from(raw)
        if magic != _ARCHIVE_MAGIC or version != _VERSION or not 0 < count <= _BLOCK_RECORDS:
            raise LogError('invalid EXP archive header or unsupported version')
        pos = _ARCHIVE_HEADER.size
        columns = []
        for kind in ('Q', 'q', 'Q', 'Q', 'H', 'H'):
            column = struct.Struct(f'<{count}{kind}')
            columns.append(column.unpack_from(raw, pos))
            pos += column.size
        seq_deltas, ts_deltas, guilds, uids, tasks, counts = columns
        if 0 in seq_deltas:
            raise LogError('invalid EXP archive sequence')
        events = []
        for seq, ts, guild, uid, task, field_count in zip(
            itertools.accumulate(seq_deltas), itertools.accumulate(ts_deltas), guilds, uids, tasks, counts,
        ):
            fields, pos = _decode_fields(raw, pos, field_count)
            events.append(Event(seq, ts, guild, uid, task, fields))
        if pos != len(raw):
            raise LogError('invalid EXP archive record length')
    except (IndexError, UnicodeError, struct.error) as exc:
        raise LogError('invalid EXP archive block') from exc
    return events


def _archive_events(stream, blocks, after: int = 0, start_ts=None, end_ts=None):
    for block in blocks:
        if block['last'] <= after:
            continue
        if start_ts is not None and block['max_ts'] < start_ts:
            continue
        if end_ts is not None and block['min_ts'] >= end_ts:
            continue
        stream.seek(block['offset'])
        raw = gzip.decompress(stream.read(block['size']))
        yield from (event for event in _decode_block(raw) if event.seq > after)


@lru_cache(maxsize=128)
def _read_index(index_path: Path, index_id: tuple, archive_id: tuple):
    with index_path.open(encoding='utf-8') as stream:
        data = json.load(stream)
    if data['version'] != _INDEX_VERSION or tuple(data['archive']) != archive_id:
        raise LogError('stale EXP archive index')
    return data['blocks']


def _index(archive: Path):
    """Recover an index if an interruption published gzip before its index."""
    index_path = archive.with_suffix('.idx')
    archive_id = _identity(archive)
    try:
        return _read_index(index_path, _identity(index_path), archive_id)
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        pass
    # A missing index is recoverable from the self-contained gzip members.
    import zlib
    offset = 0
    pending = b''
    blocks = []
    with archive.open('rb') as stream:
        while pending or offset < archive_id[1]:
            decoder = zlib.decompressobj(wbits=31)
            data = io.BytesIO()
            compressed_size = 0
            while not decoder.eof:
                chunk = pending or stream.read(65536)
                if not chunk:
                    raise LogError(f'truncated gzip archive: {archive}')
                data.write(decoder.decompress(chunk))
                pending = decoder.unused_data
                compressed_size += len(chunk) - len(pending)
            events = _decode_block(data.getvalue())
            blocks.append(_block(events, offset, compressed_size))
            offset += compressed_size
    write_json(index_path, {'version': _INDEX_VERSION, 'archive': archive_id, 'blocks': blocks})
    return blocks


def _archive_index(directory: Path, month: str):
    archive = directory / f'{month}.bin.gz'
    if not archive.is_file():
        return []
    return _index(archive)


def append(directory: Path, ts: int, guild: int, uid: int, task: int, fields=()) -> None:
    try:
        directory.mkdir()
    except FileExistsError:
        pass
    else:
        sync_directory(directory.parent)
    with store_lock(directory / '.lock'):
        seq = 0
        target = directory / f'{month_of(ts)}.bin'
        target_end = 0
        for month in _months(directory):
            blocks = _archive_index(directory, month)
            if blocks:
                seq = max(seq, blocks[-1]['last'])
            path = directory / f'{month}.bin'
            if path.is_file():
                with path.open('rb') as stream:
                    end, last = _active_tail(stream)
                seq = max(seq, last)
                if path == target:
                    target_end = end
        with target.open('a+b') as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() != target_end:
                logging.getLogger(__name__).warning('Trimming incomplete EXP log record in %s', target)
                stream.truncate(target_end)
            if not target_end:
                write_header(stream)
            write_event(stream, Event(seq + 1, ts, guild, uid, task, tuple(fields)))
            stream.flush()
            os.fsync(stream.fileno())
        if not target_end:
            sync_directory(directory)


def csv_events(path: Path, *, strict: bool = False):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for seq, row in enumerate(csv.reader(stream, strict=strict), 1):
            try:
                ts, guild, uid, task = map(int, row[:4])
            except ValueError as exc:
                if strict:
                    raise LogError(f'invalid CSV record {seq} in {path}') from exc
                continue
            yield Event(seq, ts, guild, uid, task, tuple(row[4:]))


def iter_events(path: Path, *, after: int = 0, start_ts: int | None = None,
                end_ts: int | None = None):
    """Read in original record order, optionally selecting an EXP time range."""
    if not path.is_dir():
        events = csv_events(path)
        for event in events:
            if event.seq > after and (start_ts is None or event.ts >= start_ts) and (
                end_ts is None or event.ts < end_ts
            ):
                yield event
        return

    first_month = month_of(start_ts) if start_ts is not None else ''
    last_month = month_of(end_ts - 1) if end_ts is not None else '9999-12'
    with ExitStack() as files:
        sources = []
        with store_lock(path / '.lock'):
            for month in _months(path):
                if not first_month <= month <= last_month:
                    continue
                blocks = _archive_index(path, month)
                covered = blocks[-1]['last'] if blocks else 0
                if covered > after:
                    stream = files.enter_context((path / f'{month}.bin.gz').open('rb'))
                    sources.append(_archive_events(stream, blocks, after, start_ts, end_ts))
                active = path / f'{month}.bin'
                if active.is_file():
                    stream = files.enter_context(active.open('rb'))
                    end, last = _active_tail(stream)
                    if last > max(covered, after):
                        sources.append(_active_events(stream, end, max(covered, after)))
        for event in heapq.merge(*sources, key=lambda event: event.seq):
            if (start_ts is None or event.ts >= start_ts) and (end_ts is None or event.ts < end_ts):
                yield event


def latest_init(path: Path) -> InitMarker | None:
    latest = None
    if not path.is_dir():
        for event in iter_events(path):
            if event.task in INIT_TASKS:
                latest = InitMarker(event.seq, event.ts, event.task)
        return latest

    with ExitStack() as files:
        pending = []
        with store_lock(path / '.lock'):
            for month in reversed(_months(path)):
                blocks = _archive_index(path, month)
                for block in reversed(blocks):
                    if block['init'] is not None:
                        marker = InitMarker(*block['init'])
                        if latest is None or marker.seq > latest.seq:
                            latest = marker
                        break
                active = path / f'{month}.bin'
                if active.is_file():
                    stream = files.enter_context(active.open('rb'))
                    end, seq = _active_tail(stream)
                    pending.append((seq, end, stream, blocks[-1]['last'] if blocks else 0))
        for last, end, stream, covered in sorted(pending, key=lambda item: item[0], reverse=True):
            floor = max(latest.seq if latest else 0, covered)
            while last > floor and end > _HEADER.size:
                event = _previous(stream, end)
                if event.seq <= floor:
                    break
                if event.task in INIT_TASKS:
                    latest = InitMarker(event.seq, event.ts, event.task)
                    break
                end = stream.tell()
    return latest


def _compress(events, target: Path):
    blocks = []
    with target.open('wb') as stream:
        while batch := list(itertools.islice(events, _BLOCK_RECORDS)):
            compressed = gzip.compress(_encode_block(batch), compresslevel=6, mtime=0)
            blocks.append(_block(batch, stream.tell(), len(compressed)))
            stream.write(compressed)
        stream.flush()
        os.fsync(stream.fileno())
    return blocks


def archive_closed(directory: Path, now: datetime, rollover: time) -> None:
    if not directory.is_dir():
        return
    now = now.astimezone(KST)
    # The previous calendar month becomes eligible at the first EXP rollover.
    cutoff = (now - timedelta(hours=rollover.hour, minutes=rollover.minute)).strftime('%Y-%m')
    with store_lock(directory / '.archive.lock'):
        for month in _months(directory):
            if month < cutoff:
                _archive_month(directory, month)


def _archive_month(directory: Path, month: str) -> None:
    active = directory / f'{month}.bin'
    archive = active.with_suffix('.bin.gz')
    lock = directory / '.lock'
    temp = archive.with_suffix('.gz.part')
    try:
        with ExitStack() as files:
            with store_lock(lock):
                if not active.is_file():
                    return
                stream = files.enter_context(active.open('rb'))
                end, last = _active_tail(stream)
                blocks = _archive_index(directory, month)
                covered = blocks[-1]['last'] if blocks else 0
                archived = files.enter_context(archive.open('rb')) if blocks else None
            if last > covered:
                def source():
                    if archived is not None:
                        yield from _archive_events(archived, blocks)
                    yield from _active_events(stream, end, covered)

                new_blocks = _compress(source(), temp)
                with temp.open('rb') as compressed:
                    for expected, actual in itertools.zip_longest(source(), _archive_events(compressed, new_blocks)):
                        if expected != actual:
                            raise LogError(f'EXP archive verification failed for {month}')
        with store_lock(lock):
            if last > covered:
                os.replace(temp, archive)
                sync_directory(directory)
                write_json(archive.with_suffix('.idx'), {
                    'version': _INDEX_VERSION, 'archive': _identity(archive), 'blocks': new_blocks,
                })
            _retire_prefix(active, max(last, covered))
    finally:
        temp.unlink(missing_ok=True)


def _retire_prefix(active: Path, covered: int) -> None:
    temp = active.with_suffix('.bin.part')
    try:
        with active.open('rb') as stream:
            end, last = _active_tail(stream)
            if last > covered:
                with temp.open('wb') as remaining:
                    write_header(remaining)
                    for event in _active_events(stream, end, covered):
                        write_event(remaining, event)
                    remaining.flush()
                    os.fsync(remaining.fileno())
        if last > covered:
            os.replace(temp, active)
        else:
            active.unlink()
        sync_directory(active.parent)
    finally:
        temp.unlink(missing_ok=True)
