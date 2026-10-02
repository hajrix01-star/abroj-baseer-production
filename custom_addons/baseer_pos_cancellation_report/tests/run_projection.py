"""Projection regression tests on temporary PostgreSQL tables; always rolled back."""
import argparse
import importlib.util
import re
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--container', required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--user', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'baseer_[a-z_]+_test_[0-9]{8}', args.database):
        parser.error('An explicitly isolated Baseer test database is required.')
    module = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location('report_projection', module / 'models' / 'report_query.py')
    projection = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(projection)
    fixture = (module / 'tests' / 'projection_fixture.sql').read_text(encoding='utf-8')
    sql = fixture.replace('-- REPORT_VIEW_PLACEHOLDER', 'CREATE TEMP VIEW report_test AS ' + projection.REPORT_QUERY + ';')
    result = subprocess.run([
        'docker', 'exec', '-i', args.container, 'psql', '-X', '-U', args.user,
        '-d', args.database, '-v', 'ON_ERROR_STOP=1', '-q',
    ], input=sql, text=True, encoding='utf-8', capture_output=True)
    print(result.stdout)
    print(result.stderr)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
