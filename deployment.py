"""Local deployment comparisons. Baselines change only by explicit promotion."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile


def fingerprint(spec):
    canonical = json.dumps(spec, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def tag(report, spec, environment, release):
    if not environment.strip() or not release.strip():
        raise ValueError('Environment and release must be nonempty')
    return report | {
        'schema_version': 1,
        'workflow_fingerprint': fingerprint(spec),
        'environment': environment,
        'release': release,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
    }


def read_baseline(path):
    baseline = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(baseline, dict) or baseline.get('schema_version') != 1 or baseline.get('passed') is not True:
        raise ValueError('Invalid baseline: requires a successful version-1 report')
    for key in ('workflow_fingerprint', 'environment', 'release'):
        if not isinstance(baseline.get(key), str) or not baseline[key]:
            raise ValueError('Invalid baseline metadata')
    if not isinstance(baseline.get('steps'), list) or not baseline['steps'] or any(s.get('passed') is not True for s in baseline['steps']):
        raise ValueError('Invalid baseline steps')
    return baseline


def compare(current, baseline):
    differences = [key for key in ('workflow_fingerprint', 'environment') if current[key] != baseline[key]]
    if differences:
        return {'status': 'not_comparable', 'reasons': differences, 'baseline_release': baseline['release']}
    failure = next((s for s in current['steps'] + current['cleanup'] if s.get('passed') is False), None)
    return {
        'status': 'passed' if current['passed'] else 'regression',
        'baseline_release': baseline['release'],
        'first_failing_step': failure['name'] if failure else None,
        'note': 'Behavior change observed; deployment causation is not established.',
    }


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def promote(path, report):
    if report.get('passed') is not True:
        raise ValueError('Failed runs cannot become baselines')
    if any(step.get('skipped') for step in report['cleanup']):
        raise ValueError('Skipped cleanup prevents baseline promotion')
    # Do not store nested comparisons as part of a baseline.
    atomic_write(path, {key: value for key, value in report.items() if key != 'comparison'})
