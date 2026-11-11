"""Task traces: a per-task timeline built from axis_learning events and central_brain experiences.

Creates no database of its own; it only reads the two existing stores and times spans.
"""
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import axis_learning
import central_brain

MAX_EVENTS = 2000
MAX_EXPERIENCES = 1000
MAX_NOTES = 6
NOTE_LEN = 120
# Select only needed columns and bound text size so one huge row cannot exhaust memory.
EVENT_SQL = ('SELECT task_id, agent, kind, tool, outcome, created, '
             "CASE WHEN length(payload) > 12000 THEN '{}' ELSE payload END AS payload FROM events")
EXP_SQL = ('SELECT task_id, agent, action, tool, status, substr(summary, 1, 300) AS summary, created '
           'FROM experiences')
_FLOOR = datetime.min.replace(tzinfo=timezone.utc)
# The unfiltered load is reused for CACHE_TTL seconds so repeated polls do no DB work.
CACHE_TTL = 4.0
_clock = time.monotonic
_cache_lock = threading.Lock()
_cache = None  # (loaded_at, grouped) for the unfiltered load


class _Span:
    def __init__(self):
        self.notes = {}
        self.partial_flag = False

    def note(self, key, value):
        key = str(key)
        if key not in self.notes and len(self.notes) >= MAX_NOTES:
            return
        self.notes[key] = str(value)[:NOTE_LEN]

    def partial(self):
        self.partial_flag = True


def _record_span(task_id, agent, stage, model, outcome, started, error, s):
    try:
        payload = {'duration_ms': int((time.perf_counter() - started) * 1000),
                   'model': model or None,
                   'error': error}
        if s.notes:
            payload['detail'] = '; '.join(f'{k}={v}' for k, v in s.notes.items())[:300]
        axis_learning.record(task_id, agent, 'span', stage, outcome, payload)
        _reset_cache()  # a span written here must show up on the next read, not after CACHE_TTL
    except BaseException:
        pass  # observability must never change the traced block's result


@contextmanager
def span(task_id, agent, stage, model=None):
    s = _Span()
    started = time.perf_counter()
    try:
        yield s
    except BaseException as exc:
        _record_span(task_id, agent, stage, model, 'failure', started, type(exc).__name__, s)
        raise
    _record_span(task_id, agent, stage, model, 'partial' if s.partial_flag else 'success', started, None, s)


def _parse_time(value):
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _payload(raw):
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _int_or_none(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if 0 <= number <= 10 ** 12 else None


def _event_step(row):
    data = _payload(row.get('payload'))
    model = data.get('model')
    return {
        't': str(row.get('created') or ''),
        'agent': str(row.get('agent') or ''),
        'kind': str(row.get('kind') or ''),
        'tool': str(row.get('tool') or ''),
        'outcome': str(row.get('outcome') or ''),
        'summary': str(data.get('detail') or data.get('error') or '')[:300],
        'duration_ms': _int_or_none(data.get('duration_ms')),
        'model': str(model) if model else None,
        'source': 'event',
    }


def _experience_step(row):
    return {
        't': str(row.get('created') or ''),
        'agent': str(row.get('agent') or ''),
        'kind': str(row.get('action') or ''),
        'tool': str(row.get('tool') or ''),
        'outcome': str(row.get('status') or ''),
        'summary': str(row.get('summary') or '')[:300],
        'duration_ms': None,
        'model': None,
        'source': 'experience',
    }


def _load(task_id=None):
    """Return {task_id: [steps]} with each task's steps sorted by time."""
    with axis_learning.connect() as db:
        if task_id:
            rows = db.execute(EVENT_SQL + ' WHERE task_id=? ORDER BY rowid DESC LIMIT ?', (task_id, MAX_EVENTS))
        else:
            rows = db.execute(EVENT_SQL + ' ORDER BY rowid DESC LIMIT ?', (MAX_EVENTS,))
        events = [dict(r) for r in rows]
    with central_brain.conn() as db:
        if task_id:
            rows = db.execute(EXP_SQL + ' WHERE task_id=? ORDER BY created DESC LIMIT ?', (task_id, MAX_EXPERIENCES))
        else:
            rows = db.execute(EXP_SQL + ' ORDER BY created DESC LIMIT ?', (MAX_EXPERIENCES,))
        experiences = [dict(r) for r in rows]
    grouped = {}
    # Stores return newest first; reverse so the stable sort below keeps insertion order on ties.
    for row in reversed(events):
        if row.get('task_id'):
            grouped.setdefault(str(row['task_id']), []).append(_event_step(row))
    for row in reversed(experiences):
        if row.get('task_id'):
            grouped.setdefault(str(row['task_id']), []).append(_experience_step(row))
    for steps in grouped.values():
        steps.sort(key=lambda s: _parse_time(s['t']) or _FLOOR)
    return grouped


def _reset_cache():
    global _cache
    with _cache_lock:
        _cache = None


def _load_all():
    """Unfiltered _load(), reused within CACHE_TTL. Holding the lock during the load also stops
    concurrent polls from loading the same rows twice."""
    global _cache
    with _cache_lock:
        now = _clock()
        if _cache is not None and 0 <= now - _cache[0] < CACHE_TTL:
            return _cache[1]
        grouped = _load()
        _cache = (now, grouped)
        return grouped


def _status(steps):
    outcomes = {s['outcome'] for s in steps}
    if 'failure' in outcomes:
        return 'failure'
    return 'partial' if 'partial' in outcomes else 'success'


def _timing(steps):
    """A span is written when it ends, so a step with duration_ms started at t - duration_ms."""
    starts, ends = [], []
    for step in steps:
        end = _parse_time(step['t'])
        if end is None:
            continue
        ends.append(end)
        starts.append(end - timedelta(milliseconds=step['duration_ms'] or 0))
    if not ends:
        return '', '', (steps[0]['duration_ms'] or 0) if len(steps) == 1 else 0
    started, finished = min(starts), max(ends)
    return started.isoformat(), finished.isoformat(), max(0, (finished - started) // timedelta(milliseconds=1))


def _summaries(grouped, include_api=False):
    """All task summaries from one loaded {task_id: [steps]} mapping, newest finish first."""
    result = []
    for task_id, steps in grouped.items():
        if not include_api and all(s['source'] == 'event' and s['kind'] == 'api_request' for s in steps):
            continue
        started, finished, duration = _timing(steps)
        title = next((s['summary'] for s in steps if s['source'] == 'experience' and s['summary'].strip()), '')
        if not title:
            title = steps[0]['agent'] + ': ' + steps[0]['tool']
        result.append({
            'task_id': task_id, 'started': started, 'finished': finished, 'duration_ms': duration,
            'status': _status(steps), 'agents': sorted({s['agent'] for s in steps}),
            'steps': len(steps), 'title': title[:120],
        })
    result.sort(key=lambda t: _parse_time(t['finished']) or _FLOOR, reverse=True)
    return result


def tasks(limit=30, include_api=False):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(100, limit))
    return _summaries(_load_all(), include_api)[:limit]


def trace(task_id):
    steps = _load(task_id).get(task_id) if isinstance(task_id, str) and task_id.strip() else None
    if not steps:
        raise ValueError('Görev bulunamadı')
    started, finished, duration = _timing(steps)
    return {'task_id': task_id, 'status': _status(steps), 'started': started, 'finished': finished,
            'duration_ms': duration, 'steps': steps}


def summary():
    # Same rows and filter as tasks(limit=100), built from one load instead of a second one.
    items = _summaries(_load_all())[:100]
    durations = [t['duration_ms'] for t in items]
    slowest = sorted(items, key=lambda t: t['duration_ms'], reverse=True)[:3]
    return {
        'tasks': len(items),
        'failed': sum(1 for t in items if t['status'] == 'failure'),
        'avg_duration_ms': int(sum(durations) / len(durations)) if durations else 0,
        'slowest': [{'task_id': t['task_id'], 'title': t['title'], 'duration_ms': t['duration_ms']} for t in slowest],
    }
