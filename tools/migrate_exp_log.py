#!/usr/bin/env python3
"""Convert an offline EXP CSV, or export a CSV for rollback."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from contextlib import ExitStack, closing
from dataclasses import replace
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from DB import exp_log  # noqa: E402


_MANIFEST = 'migration.json'
_INTEGER_FIELDS = {
    **dict.fromkeys((11, 12, 13, 20, 50, 61, 111, 112, 113, 120), (0,)),
    90: (0, 1), 91: (1,), 92: (0,),
}
_BOOLEAN_TASKS = {6, 60, 70, 80, 85, 110, 170}


def _source_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _typed(event: exp_log.Event) -> exp_log.Event:
    fields = list(event.fields)
    for index in _INTEGER_FIELDS.get(event.task, ()):
        if index >= len(fields):
            continue
        raw = fields[index]
        try:
            value = int(raw)
        except ValueError:
            continue
        if str(value) == raw and -(1 << 63) <= value < 1 << 63:
            fields[index] = value
    if event.task in _BOOLEAN_TASKS and fields and fields[0] in ('True', 'False'):
        fields[0] = fields[0] == 'True'
    return replace(event, fields=tuple(fields))


def _manifest(directory: Path):
    with (directory / _MANIFEST).open(encoding='utf-8') as stream:
        return json.load(stream)


def _verify(source: Path, directory: Path, manifest: dict, *, exact: bool) -> None:
    counts = Counter()
    with ExitStack() as stack:
        old_events = stack.enter_context(closing(exp_log.csv_events(source, strict=True)))
        new_events = stack.enter_context(closing(exp_log.iter_events(directory)))
        output = new_events if exact else itertools.islice(new_events, manifest['rows'])
        for old, new in itertools.zip_longest(old_events, output):
            if old is None or new is None or old.seq != new.seq or old.csv_row() != new.csv_row():
                raise exp_log.LogError(f'CSV conversion differs at record {sum(counts.values()) + 1}')
            counts[exp_log.month_of(old.ts)] += 1
    if counts != manifest['months'] or sum(counts.values()) != manifest['rows']:
        raise exp_log.LogError('CSV conversion row counts differ')


def migrate(source: Path, destination: Path, *, now: datetime | None = None) -> dict:
    """Publish a verified store once. Both CSV and destination must be offline."""
    source = source.resolve(strict=True)
    destination = destination.resolve()
    now = now or datetime.now(exp_log.KST)
    current_month = now.astimezone(exp_log.KST).strftime('%Y-%m')
    with exp_log.store_lock(destination.with_name(f'.{destination.name}.migration.lock')):
        digest = _source_hash(source)
        if destination.exists():
            try:
                manifest = _manifest(destination)
            except FileNotFoundError as exc:
                raise exp_log.LogError(f'destination already exists: {destination}') from exc
            if manifest['sha256'] != digest:
                raise exp_log.LogError('destination was migrated from a different CSV')
            _verify(source, destination, manifest, exact=False)
            return manifest

        with tempfile.TemporaryDirectory(
            dir=destination.parent, prefix=f'.{destination.name}.migrate-',
        ) as staging:
            prepared = Path(staging) / 'store'
            prepared.mkdir()
            counts = Counter()
            streams = {}
            with ExitStack() as files:
                for event in exp_log.csv_events(source, strict=True):
                    month = exp_log.month_of(event.ts)
                    if month > current_month:
                        raise exp_log.LogError(f'CSV record {event.seq} is in a future month')
                    if month not in streams:
                        stream = files.enter_context((prepared / f'{month}.bin').open('wb'))
                        exp_log.write_header(stream)
                        streams[month] = stream
                    exp_log.write_event(streams[month], _typed(event))
                    counts[month] += 1
                for stream in streams.values():
                    stream.flush()
                    os.fsync(stream.fileno())
            exp_log.archive_closed(prepared, now, time(0))
            manifest = {'sha256': digest, 'rows': sum(counts.values()), 'months': dict(counts)}
            _verify(source, prepared, manifest, exact=True)
            if _source_hash(source) != digest:
                raise exp_log.LogError('source CSV changed during migration')
            exp_log.write_json(prepared / _MANIFEST, manifest)
            os.replace(prepared, destination)
            exp_log.sync_directory(destination.parent)
    return manifest


def export_rollback(source: Path, directory: Path, output: Path) -> int:
    """Copy the original CSV and append events written after the migration."""
    manifest = _manifest(directory)
    if _source_hash(source) != manifest['sha256']:
        raise exp_log.LogError('rollback CSV differs from the migrated source')
    with exp_log.store_lock(output.with_name(f'.{output.name}.rollback.lock')):
        if output.exists():
            raise FileExistsError(output)
        with tempfile.TemporaryDirectory(dir=output.parent, prefix='.exp-rollback-') as staging:
            temp = Path(staging) / 'rollback.csv'
            shutil.copyfile(source, temp)
            if _source_hash(temp) != manifest['sha256']:
                raise exp_log.LogError('rollback CSV changed during export')
            with temp.open('rb') as stream:
                if stream.seek(0, os.SEEK_END):
                    stream.seek(-1, os.SEEK_END)
                last_byte = stream.read(1)
            with temp.open('a', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream)
                count = 0
                for event in exp_log.iter_events(directory, after=manifest['rows']):
                    if event.seq != manifest['rows'] + count + 1:
                        raise exp_log.LogError(f'noncontiguous rollback sequence at {event.seq}')
                    if count == 0 and last_byte not in (b'', b'\r', b'\n'):
                        stream.write('\r\n')
                    writer.writerow(event.csv_row())
                    count += 1
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, output)
            exp_log.sync_directory(output.parent)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    convert = modes.add_parser('convert', help='convert and verify a legacy CSV')
    convert.add_argument('source', type=Path)
    convert.add_argument('--dest', type=Path, default=exp_log.LOG_DIR)
    rollback = modes.add_parser('rollback', help='export original CSV plus new events')
    rollback.add_argument('source', type=Path)
    rollback.add_argument('output', type=Path)
    rollback.add_argument('--log', type=Path, default=exp_log.LOG_DIR)
    args = parser.parse_args()
    try:
        if args.mode == 'convert':
            manifest = migrate(args.source, args.dest)
            print(f"verified {manifest['rows']:,} records in {args.dest}")
            for month, count in sorted(manifest['months'].items()):
                print(f'{month} {count:,}')
        else:
            count = export_rollback(args.source, args.log, args.output)
            print(f'exported {count:,} post-migration records to {args.output}')
    except (OSError, ValueError, csv.Error) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
