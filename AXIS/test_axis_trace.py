"""Tests for axis_trace. Both stores are isolated in a temp folder."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import axis_learning
import axis_trace
import central_brain


def add_event(task, agent, kind, tool, outcome, created, payload='{}'):
    with axis_learning.connect() as db:
        db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?)',
                   (f'{task}-{agent}-{created}', task, agent, kind, tool, outcome, payload, created))
        db.commit()


def add_exp(task, agent, action, status, summary, created):
    with central_brain.conn() as db:
        db.execute('INSERT INTO experiences VALUES (?,?,?,?,?,?,?,?,?)',
                   (f'e-{task}-{created}', task, agent, action, 'research', status, summary, '{}', created))
        db.commit()


class Isolated(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        for mod, val in ((axis_learning, d / 'learning.sqlite3'), (central_brain, d / 'brain.sqlite3')):
            p = patch.object(mod, 'DB', val)
            p.start()
            self.addCleanup(p.stop)
        axis_trace._reset_cache()  # the load cache is process-wide; never let rows leak between tests
        self.addCleanup(axis_trace._reset_cache)

    def events(self, task_id=None):
        return axis_learning.events(task_id)


class SpanTests(Isolated):
    def test_success_records_one_event(self):
        with axis_trace.span('t1', 'coder', 'write', model='m1') as s:
            s.note('k', 'v')
        rows = self.events('t1')
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row['agent'], row['kind'], row['tool'], row['outcome']), ('coder', 'span', 'write', 'success'))
        payload = json.loads(row['payload'])
        self.assertEqual(payload['model'], 'm1')
        self.assertIsNone(payload['error'])
        self.assertIsInstance(payload['duration_ms'], int)

    def test_failure_propagates_and_records(self):
        with self.assertRaises(KeyError):
            with axis_trace.span('t2', 'coder', 'write'):
                raise KeyError('x')
        row = self.events('t2')[0]
        self.assertEqual(row['outcome'], 'failure')
        payload = json.loads(row['payload'])
        self.assertEqual(payload['error'], 'KeyError')
        self.assertIsNone(payload['model'])

    def test_partial(self):
        with axis_trace.span('t3', 'tester', 'run') as s:
            s.partial()
        self.assertEqual(self.events('t3')[0]['outcome'], 'partial')

    def test_duration_measured(self):
        with patch.object(axis_trace.time, 'perf_counter', side_effect=[10.0, 10.25]):
            with axis_trace.span('t4', 'coder', 'x'):
                pass
        self.assertEqual(json.loads(self.events('t4')[0]['payload'])['duration_ms'], 250)

    def test_real_sleep_duration(self):
        with axis_trace.span('t4b', 'coder', 'x'):
            time.sleep(0.03)
        self.assertGreaterEqual(json.loads(self.events('t4b')[0]['payload'])['duration_ms'], 20)

    def test_recording_failure_does_not_mask_result(self):
        with patch.object(axis_learning, 'record', side_effect=RuntimeError('db down')):
            with axis_trace.span('t5', 'coder', 'x') as s:
                result = 42
            self.assertEqual(result, 42)
            with self.assertRaises(ValueError):
                with axis_trace.span('t5', 'coder', 'x'):
                    raise ValueError('own')

    def test_base_exception_in_recording_does_not_mask(self):
        class Stop(BaseException):
            pass
        with patch.object(axis_learning, 'record', side_effect=Stop()):
            with axis_trace.span('t6', 'coder', 'x'):
                result = 1
            self.assertEqual(result, 1)
            with self.assertRaises(ValueError):
                with axis_trace.span('t6', 'coder', 'x'):
                    raise ValueError('own')

    def test_note_limits(self):
        s = axis_trace._Span()
        for i in range(10):
            s.note(f'k{i}', i)
        self.assertEqual(len(s.notes), 6)
        s.note('long', 'a' * 500)  # over the cap and new: ignored
        self.assertNotIn('long', s.notes)
        s.note('k0', 'b' * 500)  # existing key may be updated, trimmed
        self.assertEqual(len(s.notes['k0']), 120)
        self.assertEqual(s.notes['k1'], '1')


class TaskTests(Isolated):
    def test_merge_order_status_and_title(self):
        add_event('A', 'planner', 'span', 'plan', 'success', '2026-01-01T10:00:00+00:00')
        add_exp('A', 'research', 'search', 'partial', 'Araştırma özeti', '2026-01-01T10:00:05+00:00')
        add_event('B', 'coder', 'span', 'write', 'success', '2026-01-01T11:00:00+00:00')
        add_event('B', 'tester', 'span', 'run', 'failure', '2026-01-01T11:00:02+00:00')
        add_event('C', 'coder', 'span', 'x', 'success', '2026-01-01T09:00:00+00:00',
                  json.dumps({'duration_ms': 777}))
        out = axis_trace.tasks()
        self.assertEqual([t['task_id'] for t in out], ['B', 'A', 'C'])
        by = {t['task_id']: t for t in out}
        self.assertEqual(by['A']['status'], 'partial')
        self.assertEqual(by['A']['title'], 'Araştırma özeti')
        self.assertEqual(by['A']['agents'], ['planner', 'research'])
        self.assertEqual(by['A']['steps'], 2)
        self.assertEqual(by['A']['duration_ms'], 5000)
        self.assertEqual(by['B']['status'], 'failure')
        self.assertEqual(by['B']['title'], 'coder: write')
        self.assertEqual(by['C']['status'], 'success')
        self.assertEqual(by['C']['duration_ms'], 777)
        self.assertEqual(by['C']['steps'], 1)

    def test_single_step_without_duration_is_zero(self):
        add_event('S', 'coder', 'span', 'x', 'success', '2026-01-01T09:00:00+00:00')
        self.assertEqual(axis_trace.tasks()[0]['duration_ms'], 0)

    def test_api_request_filtering(self):
        add_event('api1', 'server', 'api_request', 'POST /x', 'success', '2026-01-01T09:00:00+00:00')
        add_event('mix', 'server', 'api_request', 'POST /x', 'success', '2026-01-01T09:00:01+00:00')
        add_event('mix', 'coder', 'span', 'w', 'success', '2026-01-01T09:00:02+00:00')
        ids = [t['task_id'] for t in axis_trace.tasks()]
        self.assertEqual(ids, ['mix'])
        ids = {t['task_id'] for t in axis_trace.tasks(include_api=True)}
        self.assertEqual(ids, {'api1', 'mix'})

    def test_limit_clamp(self):
        for i in range(105):
            add_event(f'T{i}', 'coder', 'span', 'x', 'success', f'2026-01-01T09:{i // 60:02d}:{i % 60:02d}+00:00')
        self.assertEqual(len(axis_trace.tasks(limit=0)), 1)
        self.assertEqual(len(axis_trace.tasks(limit=-5)), 1)
        self.assertEqual(len(axis_trace.tasks(limit=1000)), 100)
        self.assertEqual(len(axis_trace.tasks(limit=7)), 7)
        self.assertEqual(axis_trace.tasks(limit=1)[0]['task_id'], 'T104')

    def test_malformed_data_does_not_raise(self):
        add_event('bad', 'coder', 'span', 'x', 'success', 'not-a-date', '{oops')
        add_event('bad', 'coder', 'span', 'y', 'success', 'also-bad', '[1,2]')
        out = axis_trace.tasks()
        self.assertEqual(out[0]['task_id'], 'bad')
        self.assertEqual(out[0]['duration_ms'], 0)


class TraceTests(Isolated):
    def test_trace_order_and_payload(self):
        add_event('Z', 'coder', 'span', 'second', 'failure', '2026-01-01T10:00:02+00:00',
                  json.dumps({'duration_ms': 1500, 'model': 'gpt', 'error': 'KeyError'}))
        add_event('Z', 'planner', 'span', 'first', 'success', '2026-01-01T10:00:00+00:00', '{not json')
        add_exp('Z', 'research', 'search', 'success', 'x' * 400, '2026-01-01T10:00:01+00:00')
        t = axis_trace.trace('Z')
        self.assertEqual([s['tool'] for s in t['steps']], ['first', 'research', 'second'])
        first, mid, last = t['steps']
        self.assertEqual((first['duration_ms'], first['model'], first['summary']), (None, None, ''))
        self.assertEqual(first['source'], 'event')
        self.assertEqual(mid['source'], 'experience')
        self.assertEqual((mid['kind'], mid['outcome']), ('search', 'success'))
        self.assertEqual(len(mid['summary']), 300)
        self.assertEqual((last['duration_ms'], last['model'], last['summary']), (1500, 'gpt', 'KeyError'))
        self.assertEqual(t['status'], 'failure')
        self.assertEqual(t['duration_ms'], 2000)
        self.assertEqual(t['started'], '2026-01-01T10:00:00+00:00')

    def test_unknown_or_empty_id(self):
        for bad in ('nope', '', None, '   '):
            with self.assertRaises(ValueError) as cm:
                axis_trace.trace(bad)
            self.assertEqual(str(cm.exception), 'Görev bulunamadı')

    def test_span_then_trace(self):
        with axis_trace.span('live', 'coder', 'write', model='m') as s:
            s.note('files', 3)
        t = axis_trace.trace('live')
        self.assertEqual(t['steps'][0]['model'], 'm')
        self.assertEqual(t['steps'][0]['summary'], 'files=3')


class DurationTests(Isolated):
    def test_single_span_uses_own_duration(self):
        add_event('D1', 'coder', 'span', 'x', 'success', '2026-01-01T10:00:10+00:00', json.dumps({'duration_ms': 8000}))
        t = axis_trace.tasks()[0]
        self.assertEqual(t['duration_ms'], 8000)
        self.assertEqual(t['started'], '2026-01-01T10:00:02+00:00')
        self.assertEqual(t['finished'], '2026-01-01T10:00:10+00:00')
        tr = axis_trace.trace('D1')
        self.assertEqual(tr['duration_ms'], 8000)
        self.assertEqual(tr['steps'][0]['t'], '2026-01-01T10:00:10+00:00')

    def test_span_then_experience_milliseconds_later(self):
        add_event('D2', 'coder', 'span', 'x', 'success', '2026-01-01T10:00:10+00:00', json.dumps({'duration_ms': 6567}))
        add_exp('D2', 'research', 'search', 'success', 'bitti', '2026-01-01T10:00:10.015000+00:00')
        self.assertEqual(axis_trace.tasks()[0]['duration_ms'], 6582)
        self.assertEqual(axis_trace.trace('D2')['duration_ms'], 6582)

    def test_overlapping_spans(self):
        add_event('D3', 'coder', 'span', 'a', 'success', '2026-01-01T10:00:10+00:00', json.dumps({'duration_ms': 6000}))
        add_event('D3', 'tester', 'span', 'b', 'success', '2026-01-01T10:00:12+00:00', json.dumps({'duration_ms': 7000}))
        # spans cover 10:00:04..10:00:10 and 10:00:05..10:00:12
        self.assertEqual(axis_trace.tasks()[0]['duration_ms'], 8000)

    def test_summary_uses_corrected_durations(self):
        add_event('S1', 'coder', 'span', 'x', 'success', '2026-01-01T10:00:10+00:00', json.dumps({'duration_ms': 8000}))
        add_event('S2', 'coder', 'span', 'x', 'success', '2026-01-01T11:00:10+00:00', json.dumps({'duration_ms': 2000}))
        add_exp('S2', 'research', 'search', 'success', 'ok', '2026-01-01T11:00:10.010000+00:00')
        s = axis_trace.summary()
        self.assertEqual(s['avg_duration_ms'], 5005)
        self.assertEqual(s['slowest'][0]['task_id'], 'S1')


class LoadCacheTests(Isolated):
    def setUp(self):
        super().setUp()
        self.clock = [1000.0]
        p = patch.object(axis_trace, '_clock', lambda: self.clock[0])
        p.start()
        self.addCleanup(p.stop)
        add_event('C1', 'coder', 'span', 'x', 'success', '2026-01-01T10:00:00+00:00')
        p = patch.object(axis_trace, '_load', wraps=axis_trace._load)
        self.load = p.start()
        self.addCleanup(p.stop)

    def test_summary_performs_single_load(self):
        s = axis_trace.summary()
        self.assertEqual(s['tasks'], 1)
        self.assertEqual(self.load.call_count, 1)

    def test_cache_hit_within_ttl_avoids_second_load(self):
        axis_trace.tasks()
        self.clock[0] += axis_trace.CACHE_TTL - 0.5
        axis_trace.tasks()
        axis_trace.summary()
        self.assertEqual(self.load.call_count, 1)

    def test_expiry_reloads(self):
        axis_trace.tasks()
        self.clock[0] += axis_trace.CACHE_TTL + 0.1
        axis_trace.tasks()
        self.assertEqual(self.load.call_count, 2)

    def test_trace_by_id_is_not_cached(self):
        axis_trace.trace('C1')
        axis_trace.trace('C1')
        self.assertEqual(self.load.call_count, 2)


class HostilePayloadTests(Isolated):
    def test_overflow_nested_and_huge_payloads(self):
        add_event('H', 'coder', 'span', 'a', 'success', '2026-01-01T10:00:00+00:00', '{"duration_ms": Infinity}')
        add_event('H', 'coder', 'span', 'b', 'success', '2026-01-01T10:00:01+00:00', '{"duration_ms": 1e400}')
        add_event('H', 'coder', 'span', 'c', 'success', '2026-01-01T10:00:02+00:00', '[' * 100000 + ']' * 100000)
        add_event('H', 'coder', 'span', 'd', 'success', '2026-01-01T10:00:03+00:00',
                  json.dumps({'duration_ms': 5, 'detail': 'x' * 50000}))
        steps = axis_trace.trace('H')['steps']
        self.assertEqual([s['duration_ms'] for s in steps], [None, None, None, None])
        self.assertEqual(axis_trace.tasks()[0]['task_id'], 'H')


class SummaryTests(Isolated):
    def test_empty(self):
        self.assertEqual(axis_trace.summary(), {'tasks': 0, 'failed': 0, 'avg_duration_ms': 0, 'slowest': []})

    def test_numbers(self):
        for name, secs, outcome in (('a', 10, 'success'), ('b', 20, 'failure'), ('c', 30, 'success'), ('d', 0, 'success')):
            add_event(name, 'coder', 'span', 's1', outcome, '2026-01-01T10:00:00+00:00')
            if secs:
                add_event(name, 'coder', 'span', 's2', 'success', f'2026-01-01T10:00:{secs:02d}+00:00')
        s = axis_trace.summary()
        self.assertEqual(s['tasks'], 4)
        self.assertEqual(s['failed'], 1)
        self.assertEqual(s['avg_duration_ms'], 15000)
        self.assertEqual([x['task_id'] for x in s['slowest']], ['c', 'b', 'a'])
        self.assertEqual(s['slowest'][0]['duration_ms'], 30000)
        self.assertEqual(set(s['slowest'][0]), {'task_id', 'title', 'duration_ms'})


if __name__ == '__main__':
    unittest.main()
