"""Terminal summaries with escaped labels and redacted response diagnostics."""
import json


def safe(value):
    return json.dumps(str(value), ensure_ascii=True)[1:-1]


def failure_reason(step):
    error = step.get('error', 'unknown_failure')
    details = step.get('details', {})
    field = safe(details.get('field', ''))
    if error == 'status_mismatch':
        return f"Expected HTTP {details.get('expected_status', '?')}; received {step.get('status', '?')}."
    if error == 'json_assertion_mismatch':
        return f"Field '{field}': expected {safe(details.get('expected', '[redacted]'))}; received {safe(details.get('actual', '[redacted]'))}."
    if error == 'json_range_mismatch':
        return f"Field '{field}': expected range [{safe(details.get('minimum'))}, {safe(details.get('maximum'))}]; received {safe(details.get('actual'))}."
    messages = {
        'missing_json_field': f"Response is missing JSON field '{field}' or its structure is incompatible.",
        'invalid_json_response': 'Expected JSON but the response could not be decoded.',
        'capture_failed': 'Could not capture a required value from the response.',
        'response_too_large': 'Response exceeded the 1 MiB limit.',
        'TimeoutError': 'Request timed out.',
        'URLError': 'Connection failed; check the target server, network, and TLS configuration.',
        'KeyError': 'A required workflow variable is unavailable.',
    }
    return messages.get(error, f"Step could not complete ({safe(error)}).")


def format_report(report):
    lines = ['ReleaseGuard | ' + ('PASS' if report['passed'] else 'FAIL')]
    if 'release' in report:
        lines.append(f"Release: {safe(report['release'])} | Environment: {safe(report['environment'])}")
    for label, steps in [('Workflow', report['steps']), ('Cleanup', report['cleanup'])]:
        if not steps:
            continue
        lines.append(f'\n{label}')
        for step in steps:
            state = 'SKIP' if step.get('skipped') else 'PASS' if step.get('passed') else 'FAIL'
            suffix = f" | HTTP {step['status']}" if 'status' in step else ''
            if 'duration_ms' in step:
                suffix += f" | {step['duration_ms']:.2f} ms"
            lines.append(f"  {state}  {safe(step['name'])}{suffix}")
            if step.get('skipped'):
                lines.append('        Required captured values are unavailable; cleanup was not attempted.')
            elif not step.get('passed'):
                lines.append('        ' + failure_reason(step))
    if report.get('steps_not_run'):
        lines.append(f"\n{report['steps_not_run']} workflow step(s) not run after failure.")
    comparison = report.get('comparison')
    if comparison:
        lines.append(f"\nComparison: {safe(comparison['status'])} | Baseline: {safe(comparison['baseline_release'])}")
        if comparison.get('first_failing_step'):
            lines.append('Previously passed; now fails at: ' + safe(comparison['first_failing_step']))
        if comparison.get('reasons'):
            lines.append('Changed: ' + ', '.join(safe(reason) for reason in comparison['reasons']))
        if comparison.get('note'):
            lines.append(safe(comparison['note']))
    if report.get('baseline_update'):
        lines.append('\nBaseline preserved: failed runs cannot replace it.')
    lines.append('\nResponse values are hidden unless explicitly allowed numeric/boolean diagnostics.')
    return '\n'.join(lines)
