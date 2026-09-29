"""Read-only comparison of original business rows in MAIN and PP1 clone."""
import os
import json
import hashlib
import psycopg2
from psycopg2 import sql
from pathlib import Path
args = dict(host='db',user=os.environ['USER'],password=os.environ['PASSWORD'])
source = psycopg2.connect(dbname='baseer_dev',**args)
target = psycopg2.connect(dbname='baseer_partner_priority_qa_20260909',**args)
results = {}
with source.cursor() as a, target.cursor() as b:
    a.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'account_%%' OR tablename LIKE 'baseer_%%' OR tablename LIKE 'hr_%%' OR tablename LIKE 'pos_%%' OR tablename LIKE 'product_%%' OR tablename IN ('res_partner','res_company')) ORDER BY tablename")
    for table, in a.fetchall():
        a.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",[table])
        cols = [r[0] for r in a.fetchall()]
        query = sql.SQL('SELECT {} FROM {}').format(sql.SQL(',').join(map(sql.Identifier,cols)),sql.Identifier(table))
        a.execute(query)
        old_rows = a.fetchall()
        if 'id' in cols:
            ids = [row[cols.index('id')] for row in old_rows]
            b.execute(query + sql.SQL(' WHERE id=ANY(%s)'),[ids])
        else:
            b.execute(query)
        clone_rows = b.fetchall()
        # Stable serialized multiset; excludes additional test records by original ids.
        encode = lambda rows: sorted(json.dumps(r,default=lambda v:bytes(v).hex() if isinstance(v,(bytes,memoryview)) else str(v),sort_keys=True) for r in rows)
        equal = encode(old_rows) == encode(clone_rows)
        results[table] = {'rows':len(old_rows),'original_columns_equal':equal}
        if not equal and 'id' in cols:
            position = cols.index('id')
            by_id = {row[position]:row for row in clone_rows}
            results[table]['differing_fields'] = sorted({col for row in old_rows if row[position] in by_id
                for i,col in enumerate(cols) if row[i] != by_id[row[position]][i]})
output = {'tables':len(results),'all_original_business_rows_equal':all(r['original_columns_equal'] for r in results.values()),
          'new_field':'res_partner.baseer_is_favorite','fixture_rows':'Isolated QA-only extra ids excluded; source rows fully compared',
          'results':results}
Path('/mnt/pp1-evidence/preservation.json').write_text(json.dumps(output,indent=2))
print('PP1 preservation',output['tables'],output['all_original_business_rows_equal'])
assert output['all_original_business_rows_equal']
