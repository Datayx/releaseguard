"""Verify healthy and faulty third-party API behavior over real local HTTP."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

from workflow_checker import load, run

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'integrations/fastapi-heroes'


def verify(broken, port=None, baseline=None):
    if port is None:
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
    scratch = ROOT / 'integrations/fastapi-heroes/runtime'
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='verify-', dir=scratch) as directory:
        shutdown = Path(directory) / 'shutdown'
        command = [sys.executable, str(TARGET / 'serve.py'), '--port', str(port), '--data-dir', directory, '--shutdown-file', str(shutdown)]
        if broken:
            command.append('--broken')
        with tempfile.TemporaryFile(mode='w+b') as log:
            process = subprocess.Popen(command, stdout=log, stderr=log)
            try:
                base = f'http://127.0.0.1:{port}'
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read().decode(errors='replace'))
                    try:
                        with urlopen(base + '/openapi.json', timeout=1) as response:
                            if response.status == 200:
                                break
                    except (URLError, TimeoutError):
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError('Local API did not become ready')
                    time.sleep(0.1)
                workflow = load(ROOT / 'heroes.json')
                workflow['base_url'] = base
                workflow_path = Path(directory) / 'workflow.json'
                workflow_path.write_text(json.dumps(workflow), encoding='utf-8')
                command = [sys.executable, str(ROOT / 'workflow_checker.py'), str(workflow_path),
                           '--release', 'faulty-v2' if broken else 'healthy-v1', '--environment', 'local-integration']
                if baseline:
                    command += ['--baseline' if broken else '--set-baseline', str(baseline)]
                result = subprocess.run(command, capture_output=True, text=True, timeout=30)
                assert result.returncode == (1 if broken else 0), result.stderr + result.stdout
                report = json.loads(result.stdout)
                assert report['passed'] is (not broken), report
                assert all(step.get('passed') for step in report['cleanup']), report
                if broken:
                    assert report['steps'][-1]['name'] == 'Verify the update persisted', report
                    assert report['steps'][-1]['status'] == 200, report
                    assert report['steps'][-1]['error'] == 'json_assertion_mismatch', report
                db = sqlite3.connect(Path(directory) / 'database.db')
                try:
                    remaining = db.execute('SELECT COUNT(*) FROM hero').fetchone()[0]
                finally:
                    db.close()
                assert remaining == 0, f'{remaining} test records left behind'
                return {'mode': 'faulty' if broken else 'healthy', 'records_remaining': remaining, 'report': report}
            finally:
                shutdown.touch()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                    else:
                        process.kill()
                    process.wait(timeout=5)


if __name__ == '__main__':
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    baseline = TARGET / 'verified-baseline.json'
    results = [verify(False, port, baseline)]
    before = baseline.read_bytes()
    results.append(verify(True, port, baseline))
    assert baseline.read_bytes() == before, 'Failed run altered the baseline'
    assert results[-1]['report']['comparison']['status'] == 'regression'
    output = TARGET / 'verification.json'
    output.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    for result in results:
        print(f"{result['mode']}: expected outcome verified; records remaining = {result['records_remaining']}")
    print('Healthy and deliberately faulty deployments verified. Servers stopped.')
    print('CLI comparison detected regression; successful baseline was preserved.')
