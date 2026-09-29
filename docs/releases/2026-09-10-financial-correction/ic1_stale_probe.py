assert env.cr.dbname == 'baseer_ic1_20260910'
import json
wizard = env['baseer.financial.correction'].search([('move_id','=',4)],order='id desc',limit=1)
before = json.loads(wizard.baseline_json)
after = json.loads(wizard._snapshot(wizard.move_id,wizard.payment_id,wizard.batch_line_id))
def compare(a,b,path=''):
    if isinstance(a,dict) and isinstance(b,dict):
        for key in a.keys()|b.keys():
            compare(a.get(key),b.get(key),path+'/'+key)
    elif isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
        for idx,(first,second) in enumerate(zip(a,b)):
            compare(first,second,path+'/'+str(idx))
    elif a!=b:
        print(path,repr(a),repr(b))
compare(before,after)
env.cr.rollback()
