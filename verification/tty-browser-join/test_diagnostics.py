# SPDX-License-Identifier: GPL-3.0-or-later
"""Fault-observer routing/persistence only; synthetic child != actual A/B E2E."""
import contextlib
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch
import fault
import observer
import evidence


class DiagnosticTests(unittest.TestCase):
    def driver(self, machine):
        # Load the actual functions/globals only. These lifecycle tests never
        # render an image; importing the VM-only PIL dependency is unnecessary.
        source = Path(__file__).with_name('test.py')
        tree = ast.parse(source.read_text())
        index = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Try))
        definitions = [node for node in tree.body[:index]
            if not isinstance(node, (ast.Import, ast.ImportFrom))]
        scope = {**globals(), 'machine': machine}
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), 'exec'), scope)
        return scope, tree.body[index], source

    def test_finish_saves_nonzero_result_before_the_original_assertion(self):
        # Execute the actual driver definitions, not a replacement finish().
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            class Machine:
                out_dir = str(root)
                def send_key(self, key):
                    self.last_key = key
                def execute(self, value, timeout=5):
                    return 0, '{"fixture":"synthetic-only"}'
            machine = Machine()
            scope, _, _ = self.driver(machine)
            snapshot = {'text': 'unchanged', 'field': 'editor', 'target': 'unit', 'browserPid': 1}
            scope.update(trial='cancel', current='cancel', profile_marker='fixture',
                wait=lambda value: None, snapshot=lambda: snapshot,
                command=lambda value: '-7' if value.endswith('.exit') else
                    'fixture' if 'c-fixture-marker' in value else 'same-termios')
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(AssertionError):
                scope['finish'](snapshot)
            saved = json.loads((root / 'trial-cancel-after-finish.json').read_text())
            self.assertEqual(saved['observation']['result']['exitCode'], -7)
            self.assertEqual(saved['observation']['result']['after'], snapshot)
            self.assertEqual(machine.last_key, 'ctrl-q')
            self.assertEqual(saved['admission'], 'NOT_PERFORMED')

    def test_ordinary_finish_quits_before_any_new_synchronous_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = []
            class Machine:
                out_dir = str(root)
                def send_key(self, key):
                    events.append(("key", key))
                def execute(self, value, timeout=5):
                    events.append(("diagnostic", value))
                    return 0, '{"trial":"cancel","files":{}}'
            scope, _, _ = self.driver(Machine())
            snap = {'text': 'unchanged', 'field': 'editor', 'target': 'unit', 'browserPid': 1}
            def command(value):
                events.append(("command", value))
                return '0' if value.endswith('.exit') else 'fixture' if 'c-fixture-marker' in value else 'same'
            scope.update(trial='cancel', profile_marker='fixture', command=command,
                wait=lambda value: events.append(("wait", value)), snapshot=lambda: snap)
            with contextlib.redirect_stdout(io.StringIO()):
                scope['finish'](snap)
            self.assertEqual(events[0], ('key', 'ctrl-q'))
            self.assertEqual([v for k, v in events if k == 'key'], ['ctrl-q'])
            self.assertFalse((root / 'trial-cancel-before-finish.json').exists())
            saved = json.loads((root / 'trial-cancel-after-finish.json').read_text())
            conditions = saved['observation']['conditions']
            self.assertEqual(conditions['mode'], 'ordinary-untraced')
            self.assertFalse(conditions['traceRequested'])
            self.assertEqual(conditions['extraBeforeInput'], [])
            self.assertEqual(conditions['extraBeforeQuit'], [])
            self.assertEqual(conditions['guestReadPhase'], 'after-finish')
            self.assertEqual(saved['observation']['result']['before'], snap)
            self.assertEqual(saved['admission'], 'NOT_PERFORMED')

    def test_cancel_trace_is_explicit_and_never_selected_by_normal_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            class Machine:
                out_dir = directory
                def send_chars(self, value): events.append(('input', value))
            scope, main, _ = self.driver(Machine())
            info = {'wrapperPid': 123, 'viewerPid': 456}
            def command(value):
                events.append(('command', value))
                if 'trace-cancel' in value:
                    return json.dumps({'traces': [{'pid': 123, 'tracerPid': 789}]})
                return json.dumps(info)
            scope.update(put=lambda *args: None, command=command,
                await_image=lambda *args: 'image', wait=lambda value, seconds=15: events.append(('wait', value)))
            scope['begin']('cancel', 'typed')
            self.assertFalse(scope['trace_requested'])
            self.assertFalse(any('trace-cancel' in str(v) or 'TracerPid' in str(v) for _, v in events))
            events.clear()
            scope['begin']('cancel', 'typed', diagnostic_trace=True)
            self.assertTrue(scope['trace_requested'])
            self.assertEqual(sum('trace-cancel' in str(v) for _, v in events), 1)
            self.assertEqual(sum('TracerPid' in str(v) for _, v in events), 1)
            # Inspect the real acceptance entry: none of its calls selects tracing.
            for node in ast.walk(main):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'begin':
                    self.assertFalse(any(k.arg == 'diagnostic_trace' for k in node.keywords))
            # The driver contains one finite case loop, not retry-until-success.
            loops = [node for node in ast.walk(main) if isinstance(node, ast.For)
                and isinstance(node.iter, ast.Tuple) and any(isinstance(v, ast.Constant) and v.value == 'cancel' for v in node.iter.elts)]
            self.assertEqual(len(loops), 1)
            self.assertEqual(sum(isinstance(v, ast.Constant) and v.value == 'cancel' for v in loops[0].iter.elts), 1)

    def test_tracing_cannot_leak_into_another_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            class Machine: out_dir = directory
            scope, _, _ = self.driver(Machine())
            with self.assertRaisesRegex(ValueError, 'explicit-cancel'):
                scope['begin']('ordinary', diagnostic_trace=True)
            with self.assertRaisesRegex(ValueError, 'explicit-cancel'):
                scope['begin']('cancel', expect_ready=False, diagnostic_trace=True)
            self.assertFalse(scope['trace_requested'])
            self.assertEqual(scope['trial'], '')

    def test_traced_finish_records_its_different_pre_quit_condition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = []
            class Machine:
                out_dir = directory
                def send_key(self, key): events.append('quit')
                def execute(self, value, timeout=5):
                    events.append('observation')
                    return 0, '{"trial":"cancel"}'
            scope, _, _ = self.driver(Machine())
            snap = {'text': 'unchanged', 'field': 'editor', 'target': 'unit', 'browserPid': 1}
            scope.update(trial='cancel', trace_requested=True, profile_marker='fixture',
                wait=lambda value: None, snapshot=lambda: snap,
                command=lambda value: '0' if value.endswith('.exit') else 'fixture' if 'c-fixture-marker' in value else 'same')
            with contextlib.redirect_stdout(io.StringIO()): scope['finish'](snap)
            self.assertEqual(events, ['observation', 'quit', 'observation'])
            saved = json.loads((root / 'trial-cancel-before-finish.json').read_text())
            self.assertEqual(saved['observation']['conditions']['mode'], 'traced-diagnostic')
            self.assertEqual(saved['observation']['conditions']['extraBeforeQuit'], ['diagnostic-file-and-DOM-read'])
            self.assertNotIn('status', saved)

    def test_trial_failure_roundtrip_preserves_abnormal_and_missing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = {'exitCode': 23, 'parentStderr': '', 'viewerStderr': None,
                'dom': {'state': 'ERROR', 'error': 'read-only-observer-failed'}}
            log = io.StringIO()
            with contextlib.redirect_stdout(log):
                name = fault.retain_trial(root, 'cancel', 'failure', None, raw)
            path = root / 'failed.log'; path.write_text(log.getvalue())
            report = fault.recover(path, root / 'recovered')
            saved = json.loads((root / 'recovered' / name).read_text())
            self.assertEqual(saved['observation'], raw)
            self.assertEqual(saved['admission'], 'NOT_PERFORMED')
            self.assertEqual(report['admission'], 'NOT_PERFORMED')
            self.assertNotIn('PASS', log.getvalue())

    def test_trial_record_never_overwrites_the_first_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                name = fault.retain_trial(root, 'cancel', 'failure', None, {'exitCode': 19})
                with self.assertRaises(FileExistsError):
                    fault.retain_trial(root, 'cancel', 'failure', None, {'exitCode': 0})
            self.assertEqual(json.loads((root / name).read_text())['observation']['exitCode'], 19)

    def test_trial_name_phase_and_recovery_binding_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, phase in (('../cancel', 'failure'), ('not-a-case', 'failure'), ('cancel', 'PASS')):
                with self.assertRaises(ValueError):
                    fault.retain_trial(root, name, phase, None, {})
            log = io.StringIO()
            with contextlib.redirect_stdout(log):
                fault.retain_trial(root, 'cancel', 'failure', None, {})
            record = json.loads(log.getvalue()[len(fault.MARKER):])
            record['path'] = 'trial-typed-failure.json'
            path = root / 'bad.log'; path.write_text(fault.MARKER + json.dumps(record) + '\n')
            with self.assertRaisesRegex(ValueError, 'trial-record-binding'):
                fault.recover(path, root / 'saved')

    def test_observed_bytes_distinguish_empty_missing_invalid_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(observer.read_observation(root / 'absent')['state'], 'MISSING')
            path = root / 'raw'; path.write_bytes(b'')
            value = observer.read_observation(path)
            self.assertEqual(value['state'], 'OBSERVED')
            self.assertEqual(value['dataBase64'], '')
            path.write_bytes(b'\xffraw-exit\n')
            value = observer.read_observation(path)
            import base64
            self.assertEqual(base64.b64decode(value['dataBase64']), path.read_bytes())
            path.write_bytes(b'x' * (observer.OBSERVATION_LIMIT + 1))
            self.assertEqual(observer.read_observation(path)['state'], 'TOO_LARGE')
            link = root / 'link'; link.symlink_to(path)
            self.assertEqual(observer.read_observation(link)['state'], 'NOT_REGULAR')
            fifo = root / 'fifo'; os.mkfifo(fifo)
            self.assertEqual(observer.read_observation(fifo)['state'], 'NOT_REGULAR')

    def test_failed_dom_read_does_not_erase_exit_or_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'cancel.exit').write_bytes(b'23')
            (root / 'cancel.errors').write_bytes(b'')
            with patch.object(observer, 'STATE', root), patch.object(observer, 'dom',
                    side_effect=ValueError('unavailable')):
                value = observer.diagnostic('cancel')
            self.assertEqual(value['files']['exit']['dataBase64'], 'MjM=')
            self.assertEqual(value['files']['errors']['dataBase64'], '')
            self.assertEqual(value['files']['viewer.errors']['state'], 'MISSING')
            self.assertEqual(value['dom']['state'], 'ERROR')

    def test_first_failure_survives_an_existing_partial_case_and_missing_later_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            class Machine:
                out_dir = str(root)
                def execute(self, value, timeout=5):
                    return 0, '{"exitCode":23}'
            scope, failure, source = self.driver(Machine())
            scope.update(trial='cancel', current='cancel', context=None,
                rows=[{'case': 'cancel'}])
            failure.body = ast.parse('raise RuntimeError("original-cancel-exit")').body
            report = {'cases': [{'case': 'cancel', 'status': 'NOT_PROVEN', 'reasons': ['incomplete']}],
                'errors': ['partial'], 'consistent': False}
            with patch('evidence.assess', return_value=report), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'original-cancel-exit'):
                    exec(compile(ast.fix_missing_locations(ast.Module(body=[failure],
                        type_ignores=[])), str(source), 'exec'), scope)
            saved = json.loads((root / 'trial-cancel-failure.json').read_text())
            self.assertEqual(saved['observation']['error']['message'], 'original-cancel-exit')
            self.assertEqual(json.loads((root / 'assessment.json').read_text()), report)

    def test_observer_attachment_is_not_an_input_wrapper_or_injector(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = {'wrapperPid': 123, 'viewerPid': 456, 'tty': '/dev/pts/0', 'size': [30, 90]}
            with patch.object(observer, 'STATE', root), patch.object(observer, 'session', return_value=info), \
                    patch.object(observer.os, 'umask'), \
                    patch.object(observer.subprocess, 'Popen') as spawn, \
                    patch.object(observer.subprocess, 'check_output', return_value='strace fixed-test\n'):
                spawn.return_value.pid = 789
                value = observer.trace_cancel()
            self.assertEqual(value['session'], info)
            self.assertEqual(spawn.call_count, 2)
            for call, pid in zip(spawn.call_args_list, (123, 456)):
                args = call.args[0]
                self.assertEqual(args[args.index('-p') + 1], str(pid))
                self.assertIn('--trace-fds=0,2', args)
                self.assertIn('--trace=read,write', args)
                self.assertNotIn('cdp-tty', args)
                self.assertFalse(any('inject' in word or 'kill-on-exit' in word for word in args))

    def test_forkpty_stderr_is_not_parent_stderr_and_exec_capture_preserves_status(self):
        message = 'cdp-tty: stage=input-dispatch completion=unknown; no input replay\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe = root / 'cdp-tty'
            probe.write_text('#!' + sys.executable + '\nimport os,sys\n'
                'assert os.isatty(0) and os.isatty(1)\n'
                'assert sys.argv[1]=="ws://127.0.0.1:9222/devtools/page/AUDIT"\n'
                'os.write(2,' + repr(message.encode()) + ')\nsys.exit(17)\n')
            probe.chmod(0o700)
            for capture in (False, True):
                with self.subTest(capture=capture):
                    child = root / ("child 'quoted' " + str(capture))
                    viewer = fault.viewer_command('ws://127.0.0.1:9222/devtools/page/AUDIT', str(child)) if capture else 'cdp-tty ws://127.0.0.1:9222/devtools/page/AUDIT'
                    command = ['/bin/sh', '-c', viewer]
                    code = 'import os,pty,sys\nsys.exit(os.waitstatus_to_exitcode(pty.spawn(' + repr(command) + ')))'
                    master, slave = os.openpty()
                    before = termios.tcgetattr(slave)
                    process = subprocess.Popen([sys.executable, '-c', code], stdin=slave,
                        stdout=slave, stderr=subprocess.PIPE, start_new_session=True,
                        env={**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH']})
                    output = bytearray()
                    try:
                        deadline = time.monotonic() + 3
                        while process.poll() is None and time.monotonic() < deadline:
                            if select.select([master], [], [], .02)[0]:
                                output.extend(os.read(master, 65536))
                        self.assertEqual(process.poll(), 17)
                        while select.select([master], [], [], 0)[0]:
                            output.extend(os.read(master, 65536))
                        self.assertEqual(process.communicate(timeout=1)[1], b'')
                        self.assertEqual(termios.tcgetattr(slave), before)
                        if capture:
                            self.assertEqual(child.read_text(), message)
                            self.assertNotIn(b'stage=input-dispatch', output)
                        else:
                            self.assertFalse(child.exists())
                            self.assertIn(b'stage=input-dispatch', output)
                    finally:
                        if process.poll() is None:
                            process.kill(); process.wait(timeout=1)
                        if process.stderr is not None:
                            process.stderr.close()
                        os.close(master); os.close(slave)

    def retained(self, root, audit='{"count":1}\n', parent='', viewer=''):
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            names = fault.retain(root, audit, parent, viewer)
        return names, log.getvalue()

    def test_bad_audit_and_empty_diagnostic_are_saved_not_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names, log = self.retained(root, audit='{broken\n')
            self.assertEqual(set(names), fault.FILES)
            self.assertEqual((root / names[0]).read_text(), '{broken\n')
            diagnostic = json.loads((root / names[1]).read_text())
            self.assertEqual(diagnostic, {'parentStderr': '', 'viewerStderr': ''})
            self.assertEqual(log.count(fault.MARKER), 2)
            self.assertNotIn('"status": "PASS"', log.getvalue())

    def test_failed_log_roundtrip_recovers_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names, log = self.retained(root, viewer='日本語\ncompletion=unknown\n')
            path = root / 'failed.log'; path.write_text(log + 'AssertionError: deliberately failed\n')
            result = fault.recover(path, root / 'saved')
            self.assertEqual(result['state'], 'RECOVERED')
            self.assertEqual(result['admission'], 'NOT_PERFORMED')
            for name in names:
                self.assertEqual((root / 'saved' / name).read_bytes(), (root / name).read_bytes())

    def test_no_observation_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = fault.recover(root / 'absent.log', root / 'saved')
            self.assertEqual(result['state'], 'NOT_OBSERVED')
            self.assertFalse((root / 'saved').exists())

    def test_reject_tampering_duplicate_partial_and_escaping_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, log = self.retained(root)
            lines = log.splitlines()
            first = json.loads(lines[0][len(fault.MARKER):])
            cases = [lines[:1], lines + lines[:1]]
            for key, value in [('sha256', '0'*64), ('path', '../escape'), ('text', 'changed')]:
                record = {**first, key: value}
                cases.append([fault.MARKER + json.dumps(record), lines[1]])
            cases.append([fault.MARKER + '{"path":"a","path":"b"}', lines[1]])
            for i, records in enumerate(cases):
                with self.subTest(case=i):
                    path = root / f'bad-{i}.log'; path.write_text('\n'.join(records) + '\n')
                    with self.assertRaises(ValueError):
                        fault.recover(path, root / f'out-{i}')


if __name__ == '__main__':
    unittest.main()
