"""Shared pure-note cases; run directly with ``python3 tests/note_cases.py``."""

CASES = [
    ('[{"text":"كاتشب ثوم","colorIndex":0}]', 'كاتشب ثوم'),
    ('[{"text":"أول"},{"text":" ثان "}]', 'أول، ثان'),
    ([{'text': ' أول '}, {'text': '  '}, None, {'text': 'ثان'}], 'أول، ثان'),
    (({'text': 'واحد'},), 'واحد'),
    ('{"text":"واحد","colorIndex":0}', 'واحد'),
    ('  legacy note  ', 'legacy note'),
    ('', ''), (None, ''), (False, ''), ('[]', ''), ('  ', ''),
    ('  [{invalid}  ', '  [{invalid}  '),
    ('  {"other":1}  ', '  {"other":1}  '),
]


if __name__ == '__main__':
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location('note', Path(__file__).resolve().parents[1] / 'models' / 'note.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for value, expected in CASES:
        actual = module.plain_note(value)
        assert actual == expected, (value, expected, actual)
    details = {'note': '[{"text":"أول"}]', 'customer_note': '[{"text":"ثان"}]', 'name': 'Food'}
    assert module.normalize_detail_notes(details) == {'note': 'أول', 'customer_note': 'ثان', 'name': 'Food'}
    assert details['note'].startswith('[')
    print(f'{len(CASES)} note cases and detail normalization passed')
