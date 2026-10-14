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

    def test_opening_orders_rechecks_current_server_permission(self):
        switch = method('switchSection')
        self.assertNotIn('if (ordersDenied && "orders".equals(section)) return;', switch)
        self.assertIn('if ("orders".equals(section)) {', switch)
        self.assertIn('ordersDenied = false;', switch)
        self.assertIn('discoverOrders();', switch)

    def test_denial_still_clears_order_data_and_server_is_authoritative(self):
        denial = method('denyOrdersForSession')
        self.assertIn('ordersAvailable = false;', denial)
        self.assertIn('orderCart.clear();', denial)
        self.assertIn('showRooms();', denial)
        discovery = method('discoverOrders')
        self.assertIn('fetchV2("GET", V2_ORDERS + "/options"', discovery)
        self.assertIn('if (status == 403) { denyOrdersForSession(); return; }', discovery)


if __name__ == '__main__':
    unittest.main(verbosity=2)
