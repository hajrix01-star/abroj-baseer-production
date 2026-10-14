#!/usr/bin/env python3
"""Orders UI source tripwires; device geometry still needs visual acceptance."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java').read_text(encoding='utf-8')
UI = (ROOT / 'app/src/main/java/com/baseer/freshchat/Ui.java').read_text(encoding='utf-8')


def method(name):
    start = SOURCE.index('private void ' + name + '(')
    opening = SOURCE.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (SOURCE[end] == '{') - (SOURCE[end] == '}')
        end += 1
    return SOURCE[start:end]


class OrdersUiContracts(unittest.TestCase):
    def test_purchase_route_is_server_advertised_and_survives_pending_retry(self):
        options = method('loadOrderCompanyOptions')
        self.assertIn('body.optJSONArray("purchase_routes")', options)
        self.assertIn('routes.add("representative")', options)
        self.assertIn('orderPurchaseRoutes.contains(orderPurchaseRoute)', options)
        self.assertIn('orderPurchaseRoute = "representative";', method('selectOrderCompany'))
        submit = method('submitOrder')
        self.assertIn('orderPurchaseRoutes.contains(orderPurchaseRoute)', submit)
        self.assertIn('payload.put("purchase_route", orderPurchaseRoute)', submit)
        self.assertIn('!"representative".equals(orderPurchaseRoute)', submit)
        pending = SOURCE[SOURCE.index('private static final class PendingOrder'):
                         SOURCE.index('private static final class PendingReceipt')]
        self.assertIn('this.raw = raw;', pending)
        self.assertIn('payload.has("purchase_route")', pending)
        self.assertIn('"representative"', pending)
        self.assertIn('pending.purchaseRoute.equals(created.purchaseRoute)', method('sendPendingOrder'))

    def test_tabs_are_outside_notice_overlay_and_have_fixed_underline(self):
        self.assertIn('orderContent.addView(orderNotice, orderNoticeSize);', SOURCE)
        self.assertIn('modulePane.addView(orderTabs);', SOURCE)
        self.assertNotIn('modulePane.addView(orderNotice);', SOURCE)
        self.assertIn('orderCatalogLine = addOrderTab(orderSegments, orderCatalogButton);', SOURCE)
        self.assertIn('lineSize = new LinearLayout.LayoutParams(-1, dp(3))', SOURCE)
        self.assertIn('button.setTextSize(15);', UI[UI.index('static void styleSegment'):])

    def test_same_context_can_remain_visible_but_other_context_cannot(self):
        prepare = method('prepareOrderContent')
        self.assertIn('if (key.equals(orderRenderedKey)) return;', prepare)
        self.assertIn('orderItems.removeAllViews();', prepare)
        key = SOURCE[SOURCE.index('private String orderContentKey'):SOURCE.index('private void prepareOrderContent')]
        for field in ('mode', 'companyId', 'categoryId', 'search', 'cursor'):
            self.assertIn(field, key)
        for loader in ('loadOrderSummaries', 'loadReceipts'):
            self.assertIn('prepareOrderContent(contentKey);', method(loader))
        self.assertIn('prepareOrderContent(contentKey);',
                      SOURCE[SOURCE.index('private void loadOrderCatalog(long afterId, int navigation)'):])

    def test_loading_is_delayed_and_cart_total_stays_server_owned(self):
        self.assertIn('handler.postDelayed(orderLoadingTask, 220);', method('beginOrderLoading'))
        self.assertIn('if (keepVisible) return;', method('beginOrderLoading'))
        self.assertIn('beginOrderLoading(serial, R.string.order_loading);', method('discoverOrders'))
        self.assertIn('beginOrderLoading(serial, R.string.order_loading);', method('loadOrderCompanyOptions'))
        self.assertNotIn('orderNotice.setText(R.string.order_loading);', method('discoverOrders'))
        self.assertNotIn('orderNotice.setText(R.string.order_loading);', method('loadOrderCompanyOptions'))
        self.assertIn('finishOrderLoading();', method('loadOrderSummaries'))
        self.assertIn('finishOrderLoading();', method('loadReceipts'))
        self.assertIn('orderCartSummary.setText(', method('refreshOrderQuoteLabels'))
        self.assertIn('orderQuoteTotal', method('refreshOrderQuoteLabels'))
        self.assertIn('orderCartButton.setText(R.string.order_view_cart);', SOURCE)

    def test_load_failures_offer_in_context_retry(self):
        retry = method('showOrderLoadError')
        self.assertIn('orderNotice.setOnClickListener(', retry)
        self.assertIn('R.string.order_tap_retry', retry)
        self.assertIn('this::discoverOrders', method('discoverOrders'))
        self.assertIn('this::loadOrderCompanyOptions', method('loadOrderCompanyOptions'))
        self.assertIn('() -> loadOrderCatalog(afterId, navigation)',
                      SOURCE[SOURCE.index('private void loadOrderCatalog(long afterId, int navigation)'):])
        self.assertIn('() -> loadOrderSummaries(beforeId)', method('loadOrderSummaries'))
        self.assertIn('() -> loadReceipts(beforeId)', method('loadReceipts'))

    def test_catalog_has_one_compact_accessible_quantity_stepper(self):
        catalog = method('renderOrderCatalog')
        self.assertIn('orderQuantityStepper(selected)', catalog)
        self.assertNotIn('Button decrement = orderQuantityAction(', catalog)
        self.assertNotIn('Button remove = orderQuantityAction(', catalog)
        self.assertIn('orderScroll.getWidth()', catalog)
        self.assertIn('boolean compactStepper = selected != null && availableNameDp < 168;', catalog)
        stepper = SOURCE[SOURCE.index('private LinearLayout orderQuantityStepper('):
                         SOURCE.index('private TextView orderStepperAction(')]
        self.assertIn('selected.quantity', stepper)
        self.assertIn('editOrderQuantity(selected.option)', stepper)
        self.assertIn('stepOrderQuantity(selected.option, -1)', stepper)
        self.assertIn('stepOrderQuantity(selected.option, 1)', stepper)
        self.assertIn('new LinearLayout.LayoutParams(dp(48), dp(48))', stepper)
        self.assertIn('new LinearLayout.LayoutParams(dp(56), dp(48))', stepper)
        self.assertIn('dividerSize.gravity = Gravity.CENTER_VERTICAL;', stepper)
        self.assertIn('secondDividerSize.gravity = Gravity.CENTER_VERTICAL;', stepper)
        action = SOURCE[SOURCE.index('private TextView orderStepperAction('):
                        SOURCE.index('private OrderCartLine orderLineForProduct(')]
        self.assertIn('setMinWidth(dp(48))', action)
        self.assertIn('setMinHeight(dp(48))', action)


if __name__ == '__main__':
    unittest.main(verbosity=2)
