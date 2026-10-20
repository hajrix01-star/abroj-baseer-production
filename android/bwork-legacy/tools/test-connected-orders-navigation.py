#!/usr/bin/env python3
"""Connected orders stay discoverable after a server-side permission change."""
from pathlib import Path
import unittest


SOURCE = (Path(__file__).resolve().parents[1] /
          'app/src/main/java/com/baseer/bwork/legacy/BWorkIdentityActivity.java').read_text()


def method(name):
    start = SOURCE.index('private void ' + name + '(')
    opening = SOURCE.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (SOURCE[end] == '{') - (SOURCE[end] == '}')
        end += 1
    return SOURCE[start:end]


class ConnectedOrdersNavigation(unittest.TestCase):
    def test_representative_denied_hides_orders_tab(self):
        navigation = method('renderBottomTabs')
        self.assertIn('String[] sections = {"chats", "orders", "tasks"}', navigation)
        self.assertIn('if ("orders".equals(section) && !orderCanView) continue;', navigation)
        denial = method('denyOrdersForSession')
        self.assertIn('orderAccess = "";', denial)
        self.assertIn('orderCanView = orderCanCreate = orderCanReceive = false;', denial)
        self.assertIn('showRooms();', denial)

    def test_viewer_and_operator_discovered_without_opening_hidden_tab(self):
        switch = method('switchSection')
        self.assertIn('if ("orders".equals(section) && !orderCanView) return;', switch)
        self.assertIn('if (!"orders".equals(section)) handler.post(this::maybeProbeOrderCapability);', switch)
        self.assertIn('if ("orders".equals(section)) {', switch)
        self.assertIn('boolean needsDiscovery = !ordersAvailable || ordersDenied', switch)
        self.assertIn('ordersDenied = false;', switch)
        self.assertIn('if (needsDiscovery) discoverOrders();', switch)
        self.assertIn('!orderCompanyOptionsLoaded', switch)
        self.assertIn('loadOrderCompanyOptions();', switch)
        probe = method('maybeProbeOrderCapability')
        self.assertIn('V2_ORDERS + "/options"', probe)
        self.assertIn('if (status == 403)', probe)
        self.assertIn('applyOrderRights(body, scopedAccount);', probe)
        self.assertIn('"viewer".equals(access)', probe)
        self.assertIn('"operator".equals(access)', probe)
        self.assertIn('renderBottomTabs();', probe)
        rooms = method('loadRooms')
        self.assertLess(rooms.index('maybeProbeOrderCapability();'),
                        rooms.index('maybeRegisterPush();'))

    def test_denial_still_clears_order_data_and_server_is_authoritative(self):
        denial = method('denyOrdersForSession')
        self.assertIn('ordersAvailable = false;', denial)
        self.assertIn('orderCart.clear();', denial)
        self.assertIn('showRooms();', denial)
        discovery = method('discoverOrders')
        self.assertIn('fetchV2("GET", V2_ORDERS + "/options"', discovery)
        self.assertIn('if (status == 403) { denyOrdersForSession(); return; }', discovery)

    def test_company_is_restored_only_inside_verified_account(self):
        bootstrap = method('acceptResponse')
        self.assertIn('prepareOrderCompanyAccount(nextAccount);', bootstrap)
        verified = method('verifyV2')
        self.assertIn('savedOrderCompany(account)', verified)
        saved = SOURCE[SOURCE.index('private long savedOrderCompany('):
                       SOURCE.index('private void saveOrderCompany(')]
        self.assertIn('v1Companies.contains(id)', saved)
        self.assertIn('orderCompanyPreferences().edit().remove(ORDER_COMPANY_SELECTED)', method('discoverOrders'))
        self.assertNotIn('orderCompanyPreferences()', method('logout'))
        self.assertNotIn('orderCompanyPreferences()', SOURCE[SOURCE.index('localExit.setOnClickListener('):
                                                                SOURCE.index('layout.addView(localExit,')])
        self.assertIn('stored.edit().clear().putString(ORDER_COMPANY_OWNER, scope.key)',
                      method('prepareOrderCompanyAccount'))

    def test_company_content_403_recovers_once_without_revealing_old_data(self):
        recovery = method('recoverOrderCompanyAccess')
        self.assertIn('deniedOrderCompanyIds.add(deniedCompanyId)', recovery)
        self.assertIn('orderItems.removeAllViews();', recovery)
        self.assertIn('orderCompanies.clear();', recovery)
        self.assertIn('orderCart.clear();', recovery)
        self.assertIn('if (firstFailure) discoverOrders();', recovery)
        self.assertIn('deniedOrderCompanyIds.clear();', recovery)
        discovery = method('discoverOrders')
        self.assertIn('!deniedOrderCompanyIds.contains(choice.id)', discovery)
        self.assertIn('if (status == 403) { denyOrdersForSession(); return; }', discovery)
        for loader in ('loadOrderCompanyOptions', 'loadReceipts', 'loadReceiptDetail'):
            self.assertIn('recoverOrderCompanyAccess(companyId)', method(loader))
        for loader in ('loadOrderSummaries', 'loadPreviousOrder'):
            self.assertIn('recoverAllOrdersAccess()', method(loader))
        global_recovery = method('recoverAllOrdersAccess')
        self.assertIn('orderSummaries.clear();', global_recovery)
        self.assertIn('orderListBeforeId = 0;', global_recovery)
        self.assertIn('renderOrderSummaries();', global_recovery)
        self.assertIn('allOrdersRecoveryAttempted = true;', global_recovery)
        self.assertNotIn('orderCompanyId =', global_recovery)

    def test_company_lists_use_same_ascending_id_order(self):
        profile = SOURCE[SOURCE.index('private JSONObject verifiedProfile('):
                         SOURCE.index('private static final class SessionRedirect')]
        self.assertIn('sortedCompanies.sort((first, second) -> Long.compare(', profile)
        self.assertIn('companies.sort((first, second) -> Long.compare(first.id, second.id));',
                      method('discoverOrders'))

    def test_all_orders_are_global_and_details_are_owned_by_server_identity(self):
        listing = method('loadOrderSummaries')
        self.assertIn('V2_ORDERS + "?scope=all"', listing)
        self.assertNotIn('orderCompanyId', listing)
        self.assertIn('new OrderSummary(array.getJSONObject(i), true)', listing)
        self.assertIn('v1Companies.contains(order.companyId)', listing)
        self.assertIn('recoverAllOrdersAccess()', listing)
        self.assertIn('if (status == 403 || status == 404) { recoverAllOrdersAccess(); return; }', listing)
        self.assertIn('array.length() > 30', listing)
        detail = method('loadPreviousOrder')
        self.assertIn('final long companyId = selected.companyId;', detail)
        self.assertIn('"&scope=all"', detail)
        self.assertIn('detail.requesterId != selected.requesterId', detail)
        self.assertIn('if (status == 404)', detail)
        self.assertIn('recoverAllOrdersAccess();', detail)
        self.assertNotIn('companyId != orderCompanyId', detail)
        dialog = method('showPreviousOrder')
        self.assertIn('detail.requesterId == scopedAccount.userId', dialog)
        self.assertIn('if (ownOrder) builder.setPositiveButton(', dialog)
        guard = SOURCE[SOURCE.index('private boolean validPreviousOrderContext('):
                       SOURCE.index('private String previousOrderShareText(')]
        self.assertIn('requesterId == scopedAccount.userId', guard)
        self.assertIn('v1Companies.contains(companyId)', guard)
        self.assertNotIn('orderCompanyId == companyId', guard)

    def test_viewer_has_only_global_read_only_orders(self):
        discovery = method('discoverOrders')
        self.assertIn('body.getString("access")', discovery)
        self.assertIn('"viewer".equals(access)', discovery)
        self.assertIn('orderMine = true;', discovery)
        self.assertIn('if (orderMine) loadOrderSummaries(0);', discovery)
        selectors = method('updateOrderSelectors')
        self.assertIn('orderCatalogButton.getParent()).setVisibility(orderCanCreate ? View.VISIBLE : View.GONE)', selectors)
        self.assertIn('orderReceiptButton.getParent()).setVisibility(orderCanReceive ? View.VISIBLE : View.GONE)', selectors)
        self.assertIn('orderHeaderCompanyButton.setVisibility((orderCanCreate || orderCanReceive)', selectors)
        self.assertIn('if (!mine && !orderCanCreate) return;',
                      method('showOrderMode'))
        self.assertIn('if (!orderCanReceive) return;',
                      method('showReceiptMode'))
        self.assertIn('&& orderCanCreate',
                      SOURCE[SOURCE.index('private boolean validPreviousOrderContext('):
                             SOURCE.index('private String previousOrderShareText(')])

    def test_receipt_sharing_never_reconfirms_or_formats_local_message(self):
        confirm = method('sendPendingReceipt')
        self.assertIn('shareConfirmedReceipt(pending.orderId,', confirm)
        share = method('shareConfirmedReceipt')
        self.assertIn('V2_ORDERS + "/receipts/" + orderId + "/share"', share)
        self.assertIn('payload.put("company_id", companyId)', share)
        self.assertNotIn('payload.put("room_id"', share)
        self.assertNotIn('payload.put("text"', share)
        self.assertNotIn('"/confirm"', share)
        retry = method('showReceiptShareRetry')
        self.assertIn('shareConfirmedReceipt(orderId,', retry)
        self.assertNotIn('sendPendingReceipt(', retry)

    def test_receipt_share_retry_survives_restart_and_is_account_scoped(self):
        self.assertIn('RECEIPT_SHARE_PREFS = com.baseer.bwork.legacy.compat.LegacyIdentity.RECEIPT_SHARE', SOURCE)
        key = SOURCE[SOURCE.index('private String receiptShareKey('):
                     SOURCE.index('private long pendingReceiptShareCompany(')]
        self.assertIn('scope.key + ":" + orderId', key)
        confirm = method('sendPendingReceipt')
        self.assertLess(confirm.index('receiptSharePreferences().edit()'),
                        confirm.index('receiptConfirmPreferences().edit().remove(pending.scope)'))
        self.assertIn('putLong(receiptShareKey(scopedAccount, pending.orderId)', confirm)
        pending = SOURCE[SOURCE.index('private boolean hasPendingReceiptShare('):
                         SOURCE.index('private void sendPendingReceipt(')]
        self.assertIn('account.key + ":"', pending)
        self.assertIn('receiptSharePreferences().getAll()', pending)
        self.assertIn('if (account != scopedAccount) return;', pending)
        selectors = method('updateOrderSelectors')
        self.assertIn('orderCanReceive && hasPendingReceiptShare()', selectors)
        share = method('shareConfirmedReceipt')
        self.assertIn('if (account != scopedAccount) return;', share)
        self.assertIn('if (status == 0) handleV2TransportFailure(status, true);', share)
        self.assertIn('receiptSharePreferences().edit()', share)
        self.assertIn('.remove(receiptShareKey(scopedAccount, orderId)).commit()', share)
        self.assertLess(share.index('status != 200'), share.index('.remove(receiptShareKey('))

    def test_all_orders_do_not_depend_on_header_company_options(self):
        navigation = method('switchSection')
        self.assertIn('else if (orderMine) loadOrderSummaries(0);', navigation)
        discovery = method('discoverOrders')
        self.assertIn('if (orderMine) loadOrderSummaries(0);', discovery)
        select = method('selectOrderCompany')
        self.assertIn('if (orderMine)', select)
        self.assertNotIn('orderSummaries.clear();', select[select.index('if (orderMine)'):
                                                       select.index('return;', select.index('if (orderMine)'))])

    def test_orders_capability_probe_reuses_validated_account_scoped_options(self):
        probe = method('maybeProbeOrderCapability')
        self.assertIn('v1Companies.contains(choice.id)', probe)
        self.assertIn('orderCapabilityAccount = scopedAccount;', probe)
        self.assertIn('orderCapabilityOptions = body;', probe)
        self.assertIn('orderCapabilityProbeFailures >= 3', probe)
        self.assertIn('int backoff = 500 << orderCapabilityProbeFailures++', probe)
        discovery = method('discoverOrders')
        self.assertIn('orderCapabilityAccount == scopedAccount', discovery)
        self.assertIn('orderCapabilityOptionsAt < 30000', discovery)
        self.assertIn('if (cached != null) discovery.complete(200, cached);', discovery)
        self.assertIn('else fetchV2("GET", V2_ORDERS + "/options", null, discovery);', discovery)
        clear = method('clearChatView')
        self.assertIn('orderCapabilityOptions = null;', clear)
        self.assertIn('orderCapabilityAccount = null;', clear)

    def test_receipt_list_is_not_blocked_by_catalog_options_or_busy_polling(self):
        switch = method('switchSection')
        self.assertIn('!orderReceiving && !orderMine && orderCompanyId > 0', switch)
        self.assertIn('if (orderReceiving) loadReceipts(0);', switch)
        self.assertIn('if (orderReceiving) loadReceipts(0);', method('discoverOrders'))
        self.assertIn('if (orderReceiving) loadReceipts(0);', method('selectOrderCompany'))
        self.assertNotIn('loadOrderCompanyOptions();', method('showReceiptMode'))
        receipt = method('loadReceipts')
        self.assertIn('queueOrderLoadWhenIdle(', receipt)
        self.assertNotIn('}, 500);', receipt)
        self.assertIn('scopedAccount == account', receipt)
        self.assertIn('companyId == orderCompanyId', receipt)
        self.assertIn('serial == orderViewSerial', receipt)
        self.assertIn('runQueuedOrderLoad', SOURCE[SOURCE.index('private void fetchV2Internal('):
                                                   SOURCE.index('private static final class LiveRequest')])

    def test_receipt_conflict_preserves_pending_uuid_and_allows_validated_edit(self):
        send = method('sendPendingReceipt')
        self.assertIn('receiptErrorCode(status, body)', send)
        self.assertIn('receiptFailureMessage(status, code)', send)
        self.assertIn('editRejectedPendingReceipt(pending, scopedAccount)', send)
        self.assertNotIn('receiptConfirmPreferences().edit().remove(pending.scope)',
                         send[send.index('} catch (Exception invalid) {'):])
        edit = method('editRejectedPendingReceipt')
        self.assertIn('pending.stored.equals(receiptConfirmPreferences()', edit)
        self.assertIn('new ReceiptSummary(body.getJSONObject("order"))', edit)
        self.assertIn('showReceiptForm(detail, lines, scopedAccount, pending.companyId, serial, pending)', edit)
        review = method('confirmReceiptReview')
        self.assertIn('replacing == null', review)
        self.assertIn('UUID.randomUUID().toString() : replacing.uuid', review)
        self.assertIn('.putString(scopedAccount.key, pending.stored).commit()', review)


if __name__ == '__main__':
    unittest.main(verbosity=2)
