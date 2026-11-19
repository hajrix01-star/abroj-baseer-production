#!/usr/bin/env python3
"""Build Baseer's original dashboard snapshots using Odoo Community's spreadsheet schema."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / 'data' / 'files'
FILTER = 'baseer-period'


def sheet(name, rows=100):
    return {'id': name.lower(), 'name': name, 'colNumber': 8, 'rowNumber': rows,
            'rows': {}, 'cols': {str(i): {'size': 140} for i in range(8)}, 'merges': [],
            'cells': {}, 'styles': {}, 'formats': {}, 'borders': {}, 'conditionalFormats': [],
            'dataValidationRules': [], 'figures': [], 'tables': [], 'areGridLinesVisible': False,
            'isVisible': True, 'headerGroups': {'ROW': [], 'COL': []}, 'comments': {}}


def document():
    return {'version': '18.5.10', 'sheets': [sheet('Dashboard'), sheet('Data')],
            'styles': {'1': {'bold': True, 'fontSize': 16, 'textColor': '#01666b'},
                       '2': {'bold': True, 'fillColor': '#e6f2f3'}, '3': {'fontSize': 11}},
            'formats': {'1': '#,##0.00', '2': '0.0%'}, 'borders': {}, 'revisionId': 'baseer',
            'uniqueFigureIds': True, 'settings': {'locale': {'name': 'English (US)', 'code': 'en_US',
            'thousandsSeparator': ',', 'decimalSeparator': '.', 'dateFormat': 'mm/dd/yyyy',
            'timeFormat': 'hh:mm:ss', 'formulaArgSeparator': ',', 'weekStart': 7}},
            'pivots': {}, 'pivotNextId': 1, 'customTableStyles': {},
            'globalFilters': [{'id': FILTER, 'type': 'date', 'label': 'Period', 'defaultValue': 'this_year'}],
            'lists': {}, 'listNextId': 1, 'chartOdooMenusReferences': {}}


def pivot(d, model, name, measures, rows=(), columns=(), domain=(), date=None):
    ident = str(len(d['pivots']) + 1)
    matching = {FILTER: {'chain': date, 'type': 'datetime', 'offset': 0}} if date else {}
    d['pivots'][ident] = {'type': 'ODOO', 'id': ident, 'formulaId': ident, 'model': model,
        'name': name, 'domain': list(domain), 'context': {}, 'fieldMatching': matching,
        'measures': [{'id': m, 'fieldName': m} for m in measures],
        'rows': [dict(fieldName=field.split(':')[0], **({'granularity': field.split(':')[1]} if ':' in field else {})) for field in rows], 'columns': [dict(fieldName=field.split(':')[0], **({'granularity': field.split(':')[1]} if ':' in field else {})) for field in columns]}
    d['pivotNextId'] = len(d['pivots']) + 1
    return ident


def listing(d, model, name, columns, domain, date):
    ident = str(len(d['lists']) + 1)
    d['lists'][ident] = {'id': ident, 'model': model, 'name': name, 'columns': columns,
        'domain': domain, 'context': {}, 'orderBy': [{'name': date, 'asc': True}], 'fieldMatching': {}}
    d['listNextId'] = len(d['lists']) + 1
    return ident


def score(d, title, cell, index):
    ident = f'score-{index}'
    d['sheets'][0]['figures'].append({'id': ident, 'tag': 'chart', 'width': 185, 'height': 95,
        'col': 0, 'row': 0, 'offset': {'x': index * 190, 'y': 35},
        'data': {'type': 'scorecard', 'title': {'text': title, 'bold': True}, 'background': '#f1f8f8',
                 'keyValue': 'Data!' + cell, 'baselineMode': 'text', 'humanize': True, 'chartId': ident}})


def gauge(d, title, cell, index):
    ident = f'gauge-{index}'
    d['sheets'][0]['figures'].append({'id': ident, 'tag': 'chart', 'width': 200, 'height': 140,
        'col': 0, 'row': 0, 'offset': {'x': (index % 5) * 205, 'y': 1400 + (index // 5) * 145},
        'data': {'type': 'gauge', 'title': {'text': title}, 'background': '#ffffff', 'dataRange': 'Data!' + cell,
                 'sectionRule': {'colors': {'lowerColor': '#dc6965', 'middleColor': '#f6c46b', 'upperColor': '#00a04a'},
                   'rangeMin': '0', 'rangeMax': f'=MAX(100,Data!{cell}*1.25)', 'lowerInflectionPoint': {'type': 'percentage', 'value': '15', 'operator': '<='},
                   'upperInflectionPoint': {'type': 'percentage', 'value': '40', 'operator': '<='}}, 'chartId': ident}})


def graph(d, ident, title, model, group, measure, mode, x, y, date, domain=()):
    definition = {'title': {'text': title}, 'background': '#ffffff', 'legendPosition': 'top' if mode == 'pie' else 'none',
        'metaData': {'groupBy': [group], 'measure': measure, 'order': None, 'resModel': model, 'mode': mode, 'cumulatedStart': False},
        'searchParams': {'comparison': None, 'context': {}, 'domain': list(domain), 'groupBy': [group], 'orderBy': []},
        'type': 'odoo_' + mode, 'dataSets': [], 'chartId': ident,
        'fieldMatching': {FILTER: {'chain': date, 'type': 'datetime', 'offset': 0}}}
    if mode != 'pie': definition.update(verticalAxisPosition='left', stacked=False)
    d['sheets'][0]['figures'].append({'id': ident, 'tag': 'chart', 'width': 305, 'height': 230,
        'col': 0, 'row': 0, 'offset': {'x': x, 'y': y}, 'data': definition})


def line_chart(d):
    d['sheets'][0]['figures'].append({'id': 'income-expense-chart', 'tag': 'chart', 'width': 800, 'height': 300,
        'col': 0, 'row': 0, 'offset': {'x': 0, 'y': 1050}, 'data': {'type': 'line',
        'dataSetsHaveTitle': True, 'dataSets': [{'dataRange': 'Data!D30:D42', 'yAxisId': 'y'},
        {'dataRange': 'Data!E30:E42', 'yAxisId': 'y'}], 'legendPosition': 'top',
        'labelRange': 'Data!C31:C42', 'title': {'text': 'Income and expenses by month'},
        'labelsAsText': True, 'stacked': False, 'aggregated': False, 'cumulative': False, 'fillArea': False}})

def style_dashboard(d):
    page = d['sheets'][0]
    d['styles'].update({'4': {'bold': True, 'fontSize': 14, 'textColor': '#01666b'},
                        '5': {'bold': True, 'fontSize': 10, 'fillColor': '#e6f2f3', 'textColor': '#345'}})
    d['borders']['1'] = {'bottom': {'style': 'thin', 'color': '#9fc5c5'}}
    for key, value in list(page['cells'].items()):
        if isinstance(value, str) and value and not value.startswith('='):
            page['cells'][key] = '=_t(' + json.dumps(value, ensure_ascii=False) + ')'


def accounting_layout(d):
    page, data = d['sheets']; c = page['cells']; v = data['cells']
    page['cols'] = {str(i): {'size': size} for i, size in enumerate([220, 105, 105, 105, 220, 105, 105, 105])}
    page['rows'] = {str(i): {'size': 23} for i in range(100)}
    c.clear(); c['A1'] = 'Accounting overview'
    v['B20']='=IFERROR((-B2-B13)/-B2*100,0)'
    v['B21']='=IFERROR((-B2-B3-B13)/-B2*100,0)'
    for fig in page['figures']:
        kind=fig['data']['type']
        if kind == 'line': fig.update(width=1020,height=185); fig['offset']={'x':0,'y':135}
        elif kind == 'scorecard': fig.update(width=198,height=90); fig['offset']={'x':int(fig['id'].split('-')[-1])*204,'y':32}
        elif kind == 'gauge':
            idx=int(fig['id'].split('-')[-1])
            if idx > 6: continue
            fig.update(width=145,height=125); fig['offset']={'x':idx*150,'y':640}
    # A compact set of the seven requested ratios, retaining the data formulas for all calculations.
    selected=[0,1,2,4,3,8,9]
    gauges={int(f['id'].split('-')[-1]):f for f in page['figures'] if f['data']['type']=='gauge'}
    page['figures']=[f for f in page['figures'] if f['data']['type']!='gauge']
    for pos,index in enumerate(selected):
        f=gauges[index]; f['offset']={'x':pos*150,'y':680}; f.update(width=145,height=105)
        if index in (2, 3, 4):
            f['data']['sectionRule']['rangeMax'] = f'=MAX(3,Data!B{20 + index}*1.25)'
        page['figures'].append(f)
    blocks=[('A15','Cash', [('Cash received','=ODOO.DEBIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1)-ODOO.DEBIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-1)', '=ODOO.DEBIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-1)-ODOO.DEBIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-2)'), ('Cash spent','=ODOO.CREDIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1)-ODOO.CREDIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-1)', '=ODOO.CREDIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-1)-ODOO.CREDIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-2)'), ('Cash surplus','=B17-B18','=C17-C18'), ('Closing bank balance','=Data!B6','=Data!C6')]),
      ('E15','Profitability',[('Income','=-Data!B2','=-Data!C2'), ('Cost of revenue','=Data!B13','=Data!C13'), ('Gross profit','=F17-F18','=G17-G18'), ('Expenses','=Data!B3','=Data!C3'), ('Net profit','=F19-F20','=G19-G20')]),
      ('A23','Performance',[('Gross margin','=Data!B20/100','=IFERROR((-Data!C2-Data!C13)/-Data!C2,0)'), ('Net margin','=Data!B21/100','=IFERROR((-Data!C2-Data!C3-Data!C13)/-Data!C2,0)'), ('Return on assets','=Data!B27/100','=IFERROR((-Data!C2-Data!C3-Data!C13)/(Data!C6+Data!C7+Data!C8+Data!C9),0)'), ('Financial independence','=Data!B26/100','=IFERROR(-Data!C12/(Data!C6+Data!C7+Data!C8+Data!C9),0)')]),
      ('E23','Balance sheet',[('Assets','=Data!B6+Data!B7+Data!B8+Data!B9','=Data!C6+Data!C7+Data!C8+Data!C9'), ('Liabilities','=-Data!B10-Data!B11','=-Data!C10-Data!C11'), ('Equity','=-Data!B12','=-Data!C12')])]
    for start,title,rows in blocks:
        first=start[0]; row=int(start[1:]); cols='ABCD' if first=='A' else 'EFGH'
        c[start]=title; page['styles'][start]=4; page['borders'][start]=1
        for col,label in zip(cols,['', 'Current year', 'Previous year', 'Variation']):
            cell=f'{col}{row+1}'; page['styles'][cell]=5
            if label: c[cell]=label
        for n,(label,current,previous) in enumerate(rows,row+2):
            c[f'{cols[0]}{n}']=label; c[f'{cols[1]}{n}']=current; c[f'{cols[2]}{n}']=previous
            c[f'{cols[3]}{n}']=f'=IFERROR(({cols[1]}{n}-{cols[2]}{n})/ABS({cols[2]}{n}),0)'
            for col in cols[1:3]: page['formats'][f'{col}{n}']=2 if first=='A' and row==23 else 1
            page['formats'][f'{cols[3]}{n}']=2
    # Explicit numeric formats prevent the gauges from inheriting a currency format.
    d['formats']['3'] = '#,##0.0'
    for row in range(20, 32): data['formats'][f'B{row}'] = 3
    c['B25']='=IFERROR((F17-F18)/F17,0)'; c['B26']='=IFERROR(F21/F17,0)'
    v['B20']='=Dashboard!B25*100'; v['B21']='=Dashboard!B26*100'
    v['B22']='=IFERROR((Dashboard!F25-Data!B8-Data!B9)/ABS(Data!B10),0)'
    v['B23']='=IFERROR(Dashboard!F26/Dashboard!F27,0)'
    v['B24']='=IFERROR((Data!B6+Data!B4)/ABS(Data!B10),0)'
    v['B28']='=IFERROR(Data!H3/Dashboard!F17*365,0)'
    v['B29']='=IFERROR(Data!H4/(Dashboard!F18+Dashboard!F20)*365,0)'
    c['A29']='Ratios'; page['styles']['A29']=4; page['borders']['A29']=1
    for row, explanation in enumerate(['Gross margin shows the share left after direct costs.',
        'Net margin shows the share retained after expenses.', 'Current ratio compares current assets with short-term liabilities.',
        'Quick ratio compares cash and receivables with short-term liabilities.', 'Debt to equity compares liabilities with owners’ equity.',
        'Receivable days estimate collection time.', 'Payable days estimate payment time.'],35): c[f'A{row}']=explanation
    page['conditionalFormats']=[{'id':'positive-variation','ranges':['D17:D20','H17:H21','D25:D28','H25:H27'], 'rule':{'type':'CellIsRule','operator':'isGreaterThan','values':['0'],'style':{'textColor':'#188047'}}},
      {'id':'negative-variation','ranges':['D17:D20','H17:H21','D25:D28','H25:H27'], 'rule':{'type':'CellIsRule','operator':'isLessThan','values':['0'],'style':{'textColor':'#b42318'}}}]


def save(d, name):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{name}.json').write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n')


def accounting():
    d = document(); page, data = d['sheets']; c = page['cells']; v = data['cells']
    c['A1'] = 'Accounting overview | نظرة محاسبية'; page['styles']['A1'] = 1
    v['F1'] = '=ODOO.FILTER.VALUE("Period")'; v['B1'] = '=YEAR(F1)'
    groups = ['income', 'expense', 'asset_receivable', 'liability_payable', 'asset_cash',
              'asset_current', 'asset_non_current', 'asset_fixed', 'liability_current', 'liability_non_current', 'equity', 'expense_direct_cost']
    for i, group in enumerate(groups, 2):
        v[f'A{i}'] = group
        v[f'B{i}'] = f'=ODOO.BALANCE(ODOO.ACCOUNT.GROUP("{group}"),$B$1)'
        v[f'C{i}'] = f'=ODOO.BALANCE(ODOO.ACCOUNT.GROUP("{group}"),$B$1,-1)'
    for i, (title, formula) in enumerate([('Income', '=-B2'), ('Expenses', '=B3'), ('Receivables', '=B4'), ('Payables', '=-B5'), ('Bank & cash', '=B6')], 1):
        v[f'H{i}'] = formula
        score(d, title, f'H{i}', i - 1)
        v[f'H{i+10}'] = ('=-C2', '=C3', '=C4', '=-C5', '=C6')[i-1]
        d['sheets'][0]['figures'][-1]['data'].update(baseline=f'Data!H{i+10}', baselineMode='percentage', baselineDescr={'text': 'previous year'})
    v['G2']='=IF(AND(YEAR(F1)=YEAR(G1),MONTH(F1)=MONTH(G1)),MONTH(F1)&"/"&YEAR(F1),IF(AND(MOD(MONTH(F1)-1,3)=0,MONTH(G1)-MONTH(F1)=2),"Q"&ROUNDUP(MONTH(F1)/3,0)&"/"&YEAR(F1),YEAR(F1)))'
    v['H1']='=-ODOO.BALANCE(ODOO.ACCOUNT.GROUP("income"),G2)'
    v['H2']='=ODOO.BALANCE(ODOO.ACCOUNT.GROUP("expense"),G2)'
    v['H11']='=-ODOO.BALANCE(ODOO.ACCOUNT.GROUP("income"),G2,-1)'
    v['H12']='=ODOO.BALANCE(ODOO.ACCOUNT.GROUP("expense"),G2,-1)'
    v['H3']='=ODOO.RESIDUAL(ODOO.ACCOUNT.GROUP("asset_receivable"),B1)'
    v['H4']='=-ODOO.RESIDUAL(ODOO.ACCOUNT.GROUP("liability_payable"),B1)'
    v['H13']='=ODOO.RESIDUAL(ODOO.ACCOUNT.GROUP("asset_receivable"),B1,-1)'
    v['H14']='=-ODOO.RESIDUAL(ODOO.ACCOUNT.GROUP("liability_payable"),B1,-1)'
    c.update({'A9': 'Balance sheet | الميزانية العمومية', 'B10': 'Current year', 'C10': 'Previous year', 'D10': 'Variation %',
              'A11': 'Assets', 'B11': '=Data!B6+Data!B7+Data!B8+Data!B9', 'C11': '=Data!C6+Data!C7+Data!C8+Data!C9',
              'A12': 'Liabilities', 'B12': '=-(Data!B10+Data!B11)', 'C12': '=-(Data!C10+Data!C11)',
              'A13': 'Equity', 'B13': '=-Data!B12', 'C13': '=-Data!C12',
              'A16': 'Cash | النقد', 'A17': 'Closing bank balance', 'B17': '=Data!B6', 'C17': '=Data!C6',
              'A19': 'Profitability | الربحية', 'A20': 'Income', 'B20': '=-Data!B2', 'C20': '=-Data!C2',
              'A21': 'Cost of revenue', 'B21': '=Data!B13', 'C21': '=Data!C13',
              'A22': 'Gross profit', 'B22': '=B20-B21', 'C22': '=C20-C21',
              'A23': 'Expenses', 'B23': '=Data!B3', 'C23': '=Data!C3',
              'A24': 'Net profit', 'B24': '=B20-B21-B23', 'C24': '=C20-C21-C23',
              'A26': 'Ratios | النسب', 'A27': 'Gross margin: share of income after direct costs | هامش الربح الإجمالي',
              'A28': 'Net margin: share of income retained | هامش صافي الربح',
              'A29': 'Current ratio: current assets compared with current liabilities | نسبة التداول',
              'A30': 'Debt to equity: liabilities relative to equity | الدين إلى حقوق الملكية'})
    for row in [11,12,13,17,20,21,22,23,24]: c[f'D{row}'] = f'=IFERROR((B{row}-C{row})/ABS(C{row}),0)'
    v['B20']='=IFERROR(Dashboard!B22/Dashboard!B20*100,0)'; v['B21']='=IFERROR(Dashboard!B24/Dashboard!B20*100,0)'
    v['B22']='=IFERROR((B6+B7+B4)/-B10*100,0)'; v['B23']='=IFERROR(-(B10+B11)/-B12*100,0)'
    v['B24']='=IFERROR((B6+B4)/-B10*100,0)'
    v['B25']='=IFERROR((-B2-B3-B13)/-B2*100,0)'
    v['B26']='=IFERROR(-B12/(B6+B7+B8+B9)*100,0)'
    v['B27']='=IFERROR((-B2-B3-B13)/(B6+B7+B8+B9)*100,0)'
    v['B28']='=IFERROR(B4/-B2*365,0)'
    v['B29']='=IFERROR(-B5/(B3+B13)*365,0)'
    v['B30']='=IFERROR((B6-C6)/-B10*100,0)'
    v['B31']='=B6+B7+B4+B10'
    c.update({'A32':'Cash received | النقد المستلم', 'B32':'=ODOO.DEBIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1)-ODOO.DEBIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-1)',
              'C32':'=ODOO.DEBIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-1)-ODOO.DEBIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-2)',
              'A33':'Cash spent | النقد المدفوع', 'B33':'=ODOO.CREDIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1)-ODOO.CREDIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-1)',
              'C33':'=ODOO.CREDIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-1)-ODOO.CREDIT(ODOO.ACCOUNT.GROUP("asset_cash"),Data!B1,-2)',
              'A34':'Cash surplus | فائض النقد', 'B34':'=B32-B33', 'C34':'=C32-C33',
              'A36':'Quick ratio: cash and receivables versus current liabilities | النسبة السريعة',
              'A37':'Debtor and payable days indicate collection and payment timing | أيام التحصيل والسداد',
              'A38':'Cash movement to liabilities and working capital measure liquidity | السيولة ورأس المال العامل',
              'A40':'Performance | الأداء', 'A41':'Return on assets (investment proxy)', 'B41':'=Data!B27/100',
              'C41':'=IFERROR((-Data!C2-Data!C3-Data!C13)/(Data!C6+Data!C7+Data!C8+Data!C9),0)',
              'A42':'Financial independence', 'B42':'=Data!B26/100',
              'C42':'=IFERROR(-Data!C12/(Data!C6+Data!C7+Data!C8+Data!C9),0)'})
    for row in [41,42]: c[f'D{row}']=f'=IFERROR((B{row}-C{row})/ABS(C{row}),0)'
    for row in [32,33,34]: c[f'D{row}']=f'=IFERROR((B{row}-C{row})/ABS(C{row}),0)'
    ratio_titles=['Gross margin', 'Net margin', 'Current ratio', 'Debt / equity', 'Quick ratio', 'Operating margin', 'Financial independence', 'Return on assets', 'Receivable days', 'Payable days', 'Cash movement / liabilities', 'Working capital']
    for i, title in enumerate(ratio_titles): gauge(d, title, f'B{20+i}', i)
    v['C30']='=_t("Month")'; v['D30']='=_t("Income")'; v['E30']='=_t("Expense")'
    for month in range(1,13):
        row=30+month
        v[f'C{row}']=f'=DATE($B$1,{month},1)'
        v[f'D{row}']=f'=-ODOO.BALANCE(ODOO.ACCOUNT.GROUP("income"),"{month}/"&$B$1)'
        v[f'E{row}']=f'=ODOO.BALANCE(ODOO.ACCOUNT.GROUP("expense"),"{month}/"&$B$1)'
    line_chart(d)
    accounting_layout(d)
    style_dashboard(d)
    save(d, 'accounting')


def purchase():
    d=document(); page,data=d['sheets']; c=page['cells']; v=data['cells']; c['A1']='Purchase & vendor analysis'; page['styles']['A1']=1
    p=pivot(d,'purchase.report','Purchased value',['untaxed_total','qty_ordered','qty_received','qty_billed','delay','delay_pass'],domain=[['state','=','purchase']],date='date_order')
    vendor=pivot(d,'purchase.report','Top vendors',['untaxed_total'],rows=['partner_id'],domain=[['state','=','purchase']],date='date_order')
    d['pivots'][vendor]['measures'].append({'id':'order_id:count_distinct','fieldName':'order_id','aggregator':'count_distinct'})
    d['pivots'][vendor]['sortedColumn'] = {'measure': 'untaxed_total', 'order': 'desc', 'domain': []}
    category=pivot(d,'purchase.report','Categories',['untaxed_total'],rows=['category_id'],domain=[['state','=','purchase']],date='date_order')
    month=pivot(d,'purchase.report','Monthly purchases',['untaxed_total'],rows=['date_order:month'],domain=[['state','=','purchase']],date='date_order')
    ontime=pivot(d,'vendor.delay.report','On-time delivery',['on_time_rate'],date='date')
    vendor_ontime=pivot(d,'vendor.delay.report','Vendor on-time delivery',['on_time_rate'],rows=['partner_id'],date='date')
    data['colNumber']=12
    v['J1']=f'=PIVOT({vendor_ontime},100,FALSE,FALSE)'
    orders=pivot(d,'purchase.order','Orders',['__count'],domain=[['state','=','purchase']],date='date_order')
    for i,(title,formula) in enumerate([('Purchased value',f'=PIVOT.VALUE({p},"untaxed_total")'),('Orders',f'=PIVOT.VALUE({orders},"__count")'),('Average order', '=IFERROR(B1/B2,0)'),('Days to receive',f'=PIVOT.VALUE({p},"delay_pass")'),('Days to confirm',f'=PIVOT.VALUE({p},"delay")'),('On-time %',f'=PIVOT.VALUE({ontime},"on_time_rate")')],1): v[f'B{i}']=formula; score(d,title,f'B{i}',i-1)
    c['A20']='Top 10 vendors'; page['styles']['A20']=4; page['borders']['A20']=1
    for col, label in zip('ABCD', ['Vendor', 'Untaxed total', 'Orders', 'On-time %']):
        c[f'{col}21']=label; page['styles'][f'{col}21']=5
    for n in range(1,11):
        row=21+n
        c[f'A{row}']=f'=IFERROR(PIVOT.HEADER({vendor},"#partner_id",{n}),"")'
        c[f'B{row}']=f'=IFERROR(PIVOT.VALUE({vendor},"untaxed_total","#partner_id",{n}),"")'
        c[f'C{row}']=f'=IFERROR(PIVOT.VALUE({vendor},"order_id:count_distinct","#partner_id",{n}),"")'
        c[f'D{row}']=f'=IF(A{row}="","",IFERROR(VLOOKUP(A{row},Data!J1:K100,2,FALSE)/100,""))'
        page['formats'][f'B{row}']=1; page['formats'][f'D{row}']=2
    list_id=listing(d,'purchase.order','Pending purchase orders',['name','partner_id','date_planned','receipt_status'],[['state','=','purchase'],['receipt_status','in',['pending','partial']],['date_planned','<','today']],'date_planned')
    c['A35']='Late purchase orders'; page['styles']['A35']=4; page['borders']['A35']=1;
    for col,field in zip('ABCD',['name','partner_id','date_planned','receipt_status']):
        page['styles'][f'{col}36']=5
        c[f'{col}36']=f'=ODOO.LIST.HEADER({list_id}, "{field}")'
        for n in range(1,11): c[f'{col}{36+n}']=f'=ODOO.LIST({list_id},{n},"{field}")'
    graph(d,'purchase-month','Monthly purchases','purchase.report','date_order:month','untaxed_total','line',0,145,'date_order',[['state','=','purchase']])
    graph(d,'purchase-vendor','Top vendors','purchase.report','partner_id','untaxed_total','bar',310,145,'date_order',[['state','=','purchase']])
    graph(d,'purchase-category','Categories','purchase.report','category_id','untaxed_total','pie',620,145,'date_order',[['state','=','purchase']])
    style_dashboard(d)
    save(d,'purchase')


def warehouse():
    d=document(); page,data=d['sheets']; c=page['cells']; v=data['cells']; c['A1']='Warehouse daily operations'; page['styles']['A1']=1
    p=pivot(d,'stock.picking','Picking type and status',['__count'],rows=['picking_type_id'],columns=['state'],date='scheduled_date')
    for i,(name,code) in enumerate([('Late receipts','incoming'),('Late deliveries','outgoing'),('Late internal','internal')],1):
        ident=pivot(d,'stock.picking',name,['__count'],domain=[['picking_type_code','=',code],['state','not in',['done','cancel']],['scheduled_date','<','today']])
        v[f'B{i}']=f'=PIVOT.VALUE({ident},"__count")'; score(d,name,f'B{i}',i-1)
    c['A20']='Operations by type and status'; page['styles']['A20']=4; page['borders']['A20']=1
    for col, label in zip('ABCDE', ['Picking type', 'Ready', 'Waiting', 'Done', 'Cancelled']):
        c[f'{col}21']=label; page['styles'][f'{col}21']=5
    for n in range(1,11):
        row=21+n
        c[f'A{row}']=f'=IFERROR(PIVOT.HEADER({p},"#picking_type_id",{n}),"")'
        for col,state in zip('BCDE',['assigned','confirmed','done','cancel']):
            c[f'{col}{row}']=f'=IF(A{row}="","",IFERROR(PIVOT.VALUE({p},"__count","#picking_type_id",{n},"state","{state}"),0))'
        c[f'C{row}']=f'=IF(A{row}="","",IFERROR(PIVOT.VALUE({p},"__count","#picking_type_id",{n},"state","confirmed"),0)+IFERROR(PIVOT.VALUE({p},"__count","#picking_type_id",{n},"state","waiting"),0))'
    list_id=listing(d,'stock.picking','Late pickings',['name','partner_id','picking_type_id','scheduled_date','state'],[['state','not in',['done','cancel']],['scheduled_date','<','today']],'scheduled_date')
    c['A45']='Late pickings'; page['styles']['A45']=4; page['borders']['A45']=1
    for col,field in zip('ABCDE',['name','partner_id','picking_type_id','scheduled_date','state']):
        page['styles'][f'{col}46']=5
        c[f'{col}46']=f'=ODOO.LIST.HEADER({list_id}, "{field}")'
        for n in range(1,11): c[f'{col}{46+n}']=f'=ODOO.LIST({list_id},{n},"{field}")'
    graph(d,'warehouse-type','By operation type','stock.picking','picking_type_id','__count','bar',0,145,'scheduled_date')
    graph(d,'warehouse-state','By status','stock.picking','state','__count','bar',310,145,'scheduled_date')
    style_dashboard(d)
    save(d,'warehouse')


if __name__ == '__main__':
    accounting(); purchase(); warehouse()
