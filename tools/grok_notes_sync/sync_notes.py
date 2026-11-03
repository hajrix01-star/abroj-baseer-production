#!/usr/bin/env python3
"""Read or explicitly synchronize Grok notes over Odoo XML-RPC."""
import argparse
from datetime import datetime, timezone
import json
import os
import sys
import xmlrpc.client

COLOR_KEYS = ['default', 'red', 'orange', 'yellow', 'green', 'teal', 'blue', 'darkblue', 'purple', 'pink', 'brown', 'gray']

FIELDS = ['grok_uid', 'title', 'body', 'is_list', 'color', 'pinned', 'active', 'label_ids', 'res_model', 'res_id', 'res_name', 'user_id', 'write_date', 'item_ids']


def normalize_color(value):
    if isinstance(value, bool):
        raise ValueError('Invalid color')
    if isinstance(value, str):
        if value in COLOR_KEYS:
            return value
        if value.isascii() and value.isdecimal():
            value = int(value)
    if isinstance(value, int) and 0 <= value < len(COLOR_KEYS):
        return COLOR_KEYS[value]
    raise ValueError('Invalid color')


def parse_time(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def build_js_line(notes):
    return 'const NOTES_ODOO: any = ' + json.dumps(notes, ensure_ascii=False) + ';'


def plan_push(notes, existing):
    by_uid = {note['grok_uid']: note for note in existing}
    plan = []
    for note in notes:
        uid = note.get('grok_uid')
        if not isinstance(uid, str) or not uid.strip():
            raise ValueError('Each note must have a nonempty grok_uid')
        current = by_uid.get(uid)
        action = 'would-create' if not current else ('would-update' if note.get('updated_at') and parse_time(note['updated_at']) > parse_time(current['write_date']) else 'would-skip')
        plan.append({'grok_uid': uid, 'action': action})
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=os.getenv('ODOO_URL', 'https://abroj.sa'))
    parser.add_argument('--db', default=os.getenv('ODOO_DB', 'baseer_prod'))
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument('--uid', type=int, default=None)
    identity.add_argument('--login', default=os.getenv('ODOO_LOGIN'))
    sub = parser.add_subparsers(dest='command')
    pull = sub.add_parser('pull')
    pull.add_argument('--out')
    push = sub.add_parser('push')
    push.add_argument('--file', required=True)
    push.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    key = os.getenv('ODOO_API_KEY')
    if not key:
        parser.error('ODOO_API_KEY environment variable is required')
    uid = args.uid or (int(os.getenv('ODOO_UID', '2')) if not args.login else None)
    if args.login:
        uid = xmlrpc.client.ServerProxy(args.url.rstrip('/') + '/xmlrpc/2/common').authenticate(args.db, args.login, key, {})
        if not uid:
            raise ValueError('Authentication failed')
    proxy = xmlrpc.client.ServerProxy(args.url.rstrip('/') + '/xmlrpc/2/object')
    def call(model, method, positional, **kwargs):
        return proxy.execute_kw(args.db, uid, key, model, method, positional, kwargs)
    if args.command == 'push':
        with open(args.file, encoding='utf-8') as source:
            notes = json.load(source)
        if isinstance(notes, dict):
            notes = notes.get('notes')
        if not isinstance(notes, list) or any(not isinstance(n, dict) or not isinstance(n.get('grok_uid'), str) or not n['grok_uid'].strip() for n in notes):
            raise ValueError('Input must be a list of notes with grok_uid')
        for note in notes:
            note['color'] = normalize_color(note.get('color', 'default'))
        if args.confirm:
            result = call('grok.note', 'grok_upsert', [notes])
        else:
            existing = call('grok.note', 'search_read', [[('grok_uid', 'in', [n['grok_uid'] for n in notes])]], fields=['grok_uid', 'write_date'], context={'active_test': False})
            result = plan_push(notes, existing)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        notes = call('grok.note', 'search_read', [[]], fields=FIELDS, context={'active_test': False})
        item_ids = list({i for n in notes for i in n['item_ids']})
        label_ids = list({i for n in notes for i in n['label_ids']})
        items = {r['id']: r for r in (call('grok.note.item', 'read', [item_ids], fields=['name', 'done', 'sequence']) if item_ids else [])}
        labels = {r['id']: r['name'] for r in (call('grok.note.label', 'read', [label_ids], fields=['name']) if label_ids else [])}
        result = []
        for n in notes:
            ordered = sorted((items[i] for i in n['item_ids'] if i in items), key=lambda i: (i['sequence'], i['id']))
            color = normalize_color(n['color'])
            result.append({**{k: n[k] for k in ('id', 'grok_uid', 'title', 'body', 'is_list', 'pinned', 'res_model', 'res_id', 'res_name')}, 'color': color, 'color_index': COLOR_KEYS.index(color), 'archived': not n['active'], 'labels': [labels[i] for i in n['label_ids'] if i in labels], 'items': [{k: i[k] for k in ('name', 'done', 'sequence')} for i in ordered], 'updated_at': n['write_date']})
        line = build_js_line(result)
        if getattr(args, 'out', None):
            with open(args.out, 'w', encoding='utf-8') as output:
                output.write(line + '\n')
        else:
            print(line)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, xmlrpc.client.Error) as exc:
        print('Sync failed: ' + str(exc).replace(os.getenv('ODOO_API_KEY', '') or '\0', '[redacted]'), file=sys.stderr)
        sys.exit(1)
