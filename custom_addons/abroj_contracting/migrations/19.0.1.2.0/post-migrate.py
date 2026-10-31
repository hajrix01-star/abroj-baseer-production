def migrate(cr, version):
    cr.execute("""
        UPDATE account_payment AS payment
           SET abroj_voucher_id = voucher.id
          FROM abroj_contracting_voucher AS voucher
         WHERE voucher.payment_id = payment.id
           AND payment.abroj_voucher_id IS DISTINCT FROM voucher.id
    """)
    cr.execute("""
        UPDATE account_move AS move
           SET abroj_voucher_id = voucher.id, ref = voucher.name
          FROM abroj_contracting_voucher AS voucher
          JOIN account_payment AS payment ON payment.id = voucher.payment_id
         WHERE move.id = payment.move_id
           AND (move.abroj_voucher_id IS DISTINCT FROM voucher.id
                OR move.ref IS DISTINCT FROM voucher.name)
    """)
    cr.execute("""
        UPDATE account_move_line AS line
           SET ref = move.ref
          FROM account_move AS move
         WHERE line.move_id = move.id AND move.abroj_voucher_id IS NOT NULL
           AND line.ref IS DISTINCT FROM move.ref
    """)
