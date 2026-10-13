# SPDX-License-Identifier: GPL-3.0-or-later
"""Fault-observer routing/persistence only; synthetic child != actual A/B E2E."""
import contextlib
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
import fault


class DiagnosticTests(unittest.TestCase):
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
            self.assertEqual((root / 'unknown-effect-audit.json').read_text(), '{broken\n')
            diagnostic = json.loads((root / 'unknown-effect-diagnostic.json').read_text())
            self.assertEqual(diagnostic, {'parentStderr': '', 'viewerStderr': ''})
            self.assertEqual(log.count(fault.MARKER), 2)
            self.assertNotIn('"status": "PASS"', log)

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
