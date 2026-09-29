import om_payroll_ops as ops
print(ops.sql(ops.QA,"SELECT id,name FROM res_company ORDER BY id;"))
print(ops.sql(ops.QA,"SELECT u.id,u.login,u.company_id,array_agg(r.cid ORDER BY r.cid) FROM res_users u LEFT JOIN res_company_users_rel r ON r.user_id=u.id GROUP BY u.id,u.login,u.company_id ORDER BY u.id;"))
