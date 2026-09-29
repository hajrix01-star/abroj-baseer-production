"""Dense native purchases and expense scenarios; input-derived signed oracle."""
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from calendar import monthrange
from odoo import Command, fields
from unittest.mock import patch

def money(x): return Decimal(str(x)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)

def seed_purchases(env,ctx):
    assert env.cr.dbname=='baseer_sim90_20260910' and not env.su
    company=ctx['company']; assert company.id==2
    start=date(2026,1,1); end=date(2026,3,31)
    bank=ctx['bank_journal']; cash=ctx['cash_journal']
    events=[]; documents=[]; batches=[]; payments=[]; checks=[]; orders=[]
    methods={j.id:j.outbound_payment_method_line_ids.filtered(lambda x:x.code=='manual')[:1] for j in bank|cash}
    def account(kind): return env['account.account'].search([('company_ids','in',company.ids),('account_type','=',kind)],limit=1)
    tax=company.account_purchase_tax_id
    assert tax.amount==15 and tax.type_tax_use=='purchase'
    equity=account('equity')
    if not equity:
        equity=env['account.account'].create({'name':'SIM90 رأس مال تجريبي','code':'SIMCAP','account_type':'equity','company_ids':[Command.set(company.ids)]})
    funding=env['account.move'].create({'move_type':'entry','company_id':company.id,'journal_id':company.baseer_payroll_journal_id.id,'date':start,'ref':'SIM90 تمويل رأس مال التشغيل','line_ids':[Command.create({'name':'تمويل البنك','account_id':bank.default_account_id.id,'debit':1100000,'credit':0}),Command.create({'name':'تمويل الصندوق','account_id':cash.default_account_id.id,'debit':100000,'credit':0}),Command.create({'name':'رأس مال تجريبي','account_id':equity.id,'debit':0,'credit':1200000})]})
    funding.action_post()
    events.append({'key':'SIM90/CAPITAL','date':str(start),'kind':'capital_funding','model':'account.move','id':funding.id,'company_id':company.id,'move_ids':funding.ids,'expected_cash_in':'1200000.00','expected_operational_in':'1200000.00'})
    vendors=env['res.partner']
    for i in range(24):
        vendors|=env['res.partner'].create({'name':f'SIM90 مورد تجريبي {i+1:02d}','company_id':company.id,'supplier_rank':1,'property_account_payable_id':account('liability_payable').id,'property_account_receivable_id':account('asset_receivable').id})
    vendors[:5].write({'baseer_is_favorite':True})
    products=[]; maps=[]
    for i,title in enumerate(['المواد الغذائية','اللحوم والدواجن','الخضار والفواكه','المشروبات','التغليف','النظافة','الصيانة','الإيجار','المحروقات','الأدوات الصغيرة']):
        cat=env['product.category'].create({'name':'SIM90 '+title})
        prod=env['product.product'].create({'name':'SIM90 '+title,'type':'service','company_id':company.id,'categ_id':cat.id,'property_account_expense_id':account('expense').id,'property_account_income_id':account('income').id,'supplier_taxes_id':[Command.set(tax.ids)]})
        products.append(prod)
        maps.append(env['baseer.purchase.category.map'].create({'company_id':company.id,'category_id':cat.id,'product_id':prod.id}))
    def event(key,day,kind,model,rec,**vals):
        e={'key':key,'date':str(day),'kind':kind,'model':model,'id':rec.id,'company_id':company.id,**vals}
        events.append(e); return e
    def pay(bill,amount,day,journal,key):
        amount=money(amount)
        if not amount: return
        wiz=env['account.payment.register'].with_context(active_model='account.move',active_ids=bill.ids).create({'amount':float(amount),'payment_date':day,'journal_id':journal.id,'payment_method_line_id':methods[journal.id].id,'payment_difference_handling':'open','installments_mode':'full'})
        payment=wiz._create_payments()
        incoming=bill.move_type=='in_refund'
        event(key,day,'supplier_payment','account.payment',payment,move_ids=payment.move_id.ids,expected_cash_out=str(0 if incoming else -amount),expected_cash_in=str(amount if incoming else 0),expected_operational_in=str(amount if incoming else 0),bill_id=bill.id)
        payments.extend(payment.ids)
    def schedule(day,gross,mode):
        half=money(gross/2)
        monthend=date(day.year,day.month,monthrange(day.year,day.month)[1])
        nextmonth=date(2026,day.month+1,8) if day.month<12 else date(2027,1,8)
        if mode==0: result=[(day,gross)]
        elif mode==1:
            first_part=money(gross/4)
            result=[(day,first_part),(min(day+timedelta(days=2),monthend),half-first_part)]
        elif mode==2: result=[(day,half),(min(day+timedelta(days=5),monthend),gross-half)]
        elif mode==3: result=[(day,half),(nextmonth,gross-half)]
        elif mode==4: result=[]
        else: result=[(day+timedelta(days=14),gross)]
        return [(d,a) for d,a in result if d<=end]
    def register(bill,key,day,net,tax_amount,mode,product,prepaid=False,origin=None):
        gross=net+tax_amount; plan=schedule(day,gross,mode)
        paid=sum((a for d,a in plan),Decimal(0)); residual=gross-paid
        if not prepaid:
            for i,(d,a) in enumerate(plan): pay(bill,a,d,bank if (bill.id+i)%2 else cash,f'{key}/PAY/{i+1}')
        else:
            line=origin
            event(key+'/PAY/AUTO',day,'supplier_payment','account.payment',line.payment_id,move_ids=line.payment_id.move_id.ids,expected_cash_out=str(-gross),bill_id=bill.id)
            payments.extend(line.payment_id.ids)
        assert money(bill.amount_total)==gross,(key,bill.amount_total,gross)
        assert money(bill.amount_residual)==residual,(key,bill.amount_residual,residual)
        item={'key':key,'model':'account.move','id':bill.id,'date':str(day),'gross':str(gross),'net':str(net),'tax':str(tax_amount),'expected_residual':str(residual),'expected_settled':str(paid),'mode':mode,'move_ids':bill.ids,'expected':{'amount_total':str(gross),'amount_untaxed':str(net),'amount_tax':str(tax_amount),'amount_residual':str(residual)}}
        documents.append(item)
        item.update({'product_id':product.id,'category_id':product.categ_id.id,'category_allocations':[{'category_id':product.categ_id.id,'gross':str(gross),'net':str(net)}]})
        event(key,day,'supplier_invoice','account.move',bill,move_ids=bill.ids,gross=str(gross),tax=str(tax_amount),expected_residual=str(residual),expected_supplier_total=str(gross),product_id=product.id,category_id=product.categ_id.id)
        return item
    def create_bill(key,day,net,taxable,prod,vendor,mode):
        net=money(net); vat=money(net*Decimal('.15')) if taxable else Decimal(0)
        bill=env['account.move'].create({'move_type':'in_invoice','company_id':company.id,'partner_id':vendor.id,'invoice_date':day,'date':day,'invoice_date_due':day+timedelta(days=15),'ref':key,'invoice_line_ids':[Command.create({'product_id':prod.id,'name':key+' '+prod.name,'quantity':1,'price_unit':float(net+vat if taxable and tax.price_include else net),'tax_ids':[Command.set(tax.ids if taxable else [])]})]})
        bill.action_post(); register(bill,key,day,net,vat,mode,prod)
        return bill
    for n in range(ctx.get('daily_count',90)):
        day=start+timedelta(days=n)
        for k in range(4):
            net=Decimal(180+(n*37+k*113)%2200)+Decimal(k)/Decimal(10)
            create_bill(f'SIM90/DIRECT/{day}/{k+1}',day,net,(n+k)%7!=0,products[(n+k)%len(products)],vendors[(n+k)%len(vendors)],(n+k)%6)
        vals=[]; plans=[]
        for k in range(6):
            net=Decimal(80+(n*19+k*47)%900); taxable=(n+k)%5!=0
            vat=money(net*Decimal('.15')) if taxable else Decimal(0); gross=net+vat
            mapping=maps[(n+k)%len(maps)]
            key=f'SIM90/BATCH/{day}/{k+1}'
            vals.append(Command.create({'invoice_date':day,'partner_id':vendors[(n+k*3)%len(vendors)].id,'supplier_ref':key,'entry_type':'purchase' if k<4 else 'expense','category_map_id':mapping.id,'gross_amount':float(gross),'tax_id':tax.id if taxable else False,'is_credit':k!=0,'payment_method_line_id':methods[cash.id].id if k==0 else False}))
            plans.append((key,net,vat,k,mapping.product_id))
        batch=env['baseer.purchase.batch'].create({'company_id':company.id,'entry_date':day,'line_ids':vals})
        batch.action_approve()
        for line,(key,net,vat,mode,prod) in zip(batch.line_ids.sorted('id'),plans): register(line.move_id,key,day,net,vat,mode,prod,prepaid=mode==0,origin=line)
        batches.append({'model':batch._name,'id':batch.id,'date':str(day),'expected':{'amount_gross':str(sum((net+vat for key,net,vat,k,prod in plans),Decimal(0))),'bill_count':6},'move_ids':batch.move_ids.ids})
        if n%10==0: print('SIM90_PURCHASE_DAY',n+1,len(documents),flush=True)
    recurring=[('electricity','الكهرباء',4200,True),('water','المياه',680,True),('telecom','الاتصالات',1200,True),('internet','الإنترنت',750,True),('rent','الإيجار',16000,True),('maintenance','الصيانة',2400,True),('cleaning','النظافة',1800,True),('fuel','المحروقات',1500,True),('mudad_subscription','اشتراك مدد',460,True),('municipal_license','رسوم رخص',900,False)]
    for month in (1,2,3):
        for k,(key,title,base,taxable) in enumerate(recurring):
            cat=env.ref('baseer_service_seed.category_'+key,raise_if_not_found=False)
            mapping=env['baseer.purchase.category.map'].search([('company_id','=',company.id),('category_id','=',cat.id)],limit=1) if cat else False
            fallback={'rent':products[7],'maintenance':products[6],'cleaning':products[5],'fuel':products[8]}
            prod=mapping.product_id if mapping else fallback[key]
            bill=create_bill(f'SIM90/EXPENSE/{month}/{key}',date(2026,month,5+k),Decimal(base+month*17),taxable,prod,vendors[(k+8)%len(vendors)],(month+k)%6)
    # Native purchase orders and receipts provide a second purchasing entry path.
    stockprod=env['product.product'].create({'name':'SIM90 عبوات مخزنية','type':'consu','is_storable':True,'company_id':company.id,'purchase_method':'receive','property_account_expense_id':account('expense').id,'supplier_taxes_id':[Command.set(tax.ids)]})
    for n in range(18):
        day=start+timedelta(days=n*5); qty=10+n; unit=Decimal(12+n)
        po=env['purchase.order'].create({'company_id':company.id,'partner_id':vendors[n%24].id,'date_order':str(day)+' 08:00:00','partner_ref':f'SIM90/PO/{n+1}','order_line':[Command.create({'product_id':stockprod.id,'name':stockprod.name,'product_qty':qty,'product_uom_id':stockprod.uom_id.id,'price_unit':float(unit*Decimal('1.15') if tax.price_include else unit),'date_planned':str(day)+' 10:00:00','tax_ids':[Command.set(tax.ids)]})]})
        with patch.object(fields.Datetime,'now',return_value=datetime.combine(day,datetime.min.time()).replace(hour=8)):
            po.button_confirm()
        for picking in po.picking_ids:
            picking.action_assign()
            for move in picking.move_ids: move.quantity=move.product_uom_qty; move.picked=True
            with patch.object(fields.Datetime,'now',return_value=datetime.combine(day,datetime.min.time()).replace(hour=10)):
                result=picking.button_validate()
            assert picking.state=='done',(po.id,result)
        po.with_context(default_invoice_date=str(day)).action_create_invoice()
        bill=po.invoice_ids; bill.write({'invoice_date':day,'date':day}); bill.action_post()
        net=money(qty*unit); vat=money(net*Decimal('.15'))
        register(bill,f'SIM90/PO/{n+1}',day,net,vat,n%6,stockprod)
        orders.append({'id':po.id,'picking_ids':po.picking_ids.ids,'move_ids':bill.ids,'quantity':qty,'expected_gross':str(net+vat),'receipt_date':str(day)})
    # Supplier credits: reduce unpaid originals, preserving true residuals.
    refund_sources=[d for d in documents if d['mode']==4 and d.get('key','').startswith('SIM90/DIRECT/')][:6]
    for i,original in enumerate(refund_sources):
        bill=env['account.move'].browse(original['id']); original['has_refund']=True
        amount=money(Decimal(original['net'])/2); taxable=Decimal(original['tax'])!=0
        vat=money(amount*Decimal('.15')) if taxable else Decimal(0); gross=amount+vat
        day=date(2026,2 if i<3 else 3,15+i)
        refund=env['account.move'].create({'move_type':'in_refund','company_id':company.id,'partner_id':bill.partner_id.id,'invoice_date':day,'date':day,'ref':f'SIM90/SUPPLIER-CREDIT/{i+1}','reversed_entry_id':bill.id,'invoice_line_ids':[Command.create({'product_id':bill.invoice_line_ids[0].product_id.id,'name':'SIM90 مرتجع مورد جزئي','quantity':1,'price_unit':float(gross if taxable and tax.price_include else amount),'tax_ids':[Command.set(tax.ids if taxable else [])]})]})
        refund.action_post()
        (bill.line_ids|refund.line_ids).filtered(lambda l:l.account_id.account_type=='liability_payable').reconcile()
        original['expected_residual']=str(money(original['expected_residual'])-gross)
        original['expected']['amount_residual']=original['expected_residual']
        original['expected_settled']=str(money(original['expected_settled'])+gross)
        for e in events:
            if e['key']==original['key']: e['expected_residual']=original['expected_residual']
        event(f'SIM90/CREDIT/{i+1}',day,'supplier_credit','account.move',refund,move_ids=refund.ids,gross=str(-gross),expected_supplier_total=str(-gross),expected_residual='0',category_id=original['category_id'],product_id=original['product_id'])
        documents.append({'id':refund.id,'model':'account.move','date':str(day),'gross':str(-gross),'expected_residual':'0','expected':{'amount_total':str(gross),'amount_residual':'0'},'move_ids':refund.ids})
    # Unapproved cashier input stays visible to its creator; no financial posting.
    cashier=ctx.get('cashier_id')
    draft_ids=[]
    if cashier:
        for month in (1,2,3):
            batch=env['baseer.purchase.batch'].with_user(cashier).create({'company_id':company.id,'entry_date':date(2026,month,27),'line_ids':[Command.create({'invoice_date':date(2026,month,27),'partner_id':vendors[0].id,'supplier_ref':f'SIM90/CASHIER-DRAFT/{month}','entry_type':'purchase','category_map_id':maps[0].id,'gross_amount':115,'tax_id':tax.id,'is_credit':True})]})
            draft_ids.append(batch.id)
    return {'company_id':company.id,'user_id':env.uid,'events':events,'documents':documents,'manifest':documents+batches,'batches':batches,'purchase_orders':orders,'payments':payments,'draft_batch_ids':draft_ids,'vendor_ids':vendors.ids,'counts':{'vendor_documents':len(documents),'approved_batches':len(batches),'purchase_orders':len(orders),'recurring_expenses':30,'draft_batches':len(draft_ids)},'oracle':'Inputs and explicit payment schedule; supplier credits reduce payable, never cash until paid.'}
