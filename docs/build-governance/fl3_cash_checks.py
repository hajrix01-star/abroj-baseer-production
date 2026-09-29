from pathlib import Path
exec(compile(Path('/mnt/qa-evidence/fl3_regression.py').read_text(encoding='utf8'),
             'fl3_regression.py', 'exec'), {'env': env, 'FL3_SUITE': 'cash'})
