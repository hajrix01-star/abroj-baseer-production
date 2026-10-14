#!/usr/bin/env python3
"""Connected orders stay discoverable after a server-side permission change."""
from pathlib import Path
import unittest


SOURCE = (Path(__file__).resolve().parents[1] /
          'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java').read_text()


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
    def test_orders_tab_remains_visible_after_permission_denial(self):
        navigation = method('renderBottomTabs')
        self.assertIn('String[] sections = {"chats", "orders", "tasks"}', navigation)
        self.assertNotIn('if (ordersDenied && "orders".equals(section)) continue;', navigation)

    def test_opening_orders_rechecks_denied_role_without_repeating_valid_options(self):
        switch = method('switchSection')
        self.assertNotIn('if (ordersDenied && "orders".equals(section)) return;', switch)
        self.assertIn('if ("orders".equals(section)) {', switch)
        self.assertIn('boolean needsDiscovery = !ordersAvailable || ordersDenied || orderCompanies.isEmpty();', switch)
        self.assertIn('ordersDenied = false;', switch)
        self.assertIn('if (needsDiscovery) discoverOrders();', switch)
        self.assertIn('!orderCompanyOptionsLoaded', switch)
        self.assertIn('loadOrderCompanyOptions();', switch)
        navigation = method('renderBottomTabs')
        self.assertNotIn('else if ("orders".equals(section) && "orders".equals(visibleSection))', navigation)

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
        for loader in ('loadOrderCompanyOptions', 'loadOrderSummaries', 'loadReceipts',
                       'loadReceiptDetail', 'loadPreviousOrder'):
            self.assertIn('recoverOrderCompanyAccess(companyId)', method(loader))

    def test_company_lists_use_same_ascending_id_order(self):
        profile = SOURCE[SOURCE.index('private JSONObject verifiedProfile('):
                         SOURCE.index('private static final class SessionRedirect')]
        self.assertIn('sortedCompanies.sort((first, second) -> Long.compare(', profile)
        self.assertIn('companies.sort((first, second) -> Long.compare(first.id, second.id));',
                      method('discoverOrders'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
