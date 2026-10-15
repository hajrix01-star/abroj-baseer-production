#!/usr/bin/env python3
"""Static Android contract checks for user-admin permissions and local revocation.

These complement compilation; they do not claim emulator, APK, or server E2E coverage.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java').read_text()
HISTORY = (ROOT / 'app/src/main/java/com/baseer/freshchat/sync/ConnectedHistoryCache.java').read_text()
OUTBOX = (ROOT / 'app/src/main/java/com/baseer/freshchat/sync/BChatV2Outbox.java').read_text()
MEDIA = (ROOT / 'app/src/main/java/com/baseer/freshchat/sync/BChatConnectedMediaStore.java').read_text()


def method(name, return_type='void'):
    start = SOURCE.index('private ' + return_type + ' ' + name + '(')
    opening = SOURCE.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (SOURCE[end] == '{') - (SOURCE[end] == '}')
        end += 1
    return SOURCE[start:end]


class PermissionContracts(unittest.TestCase):
    def test_additive_bootstrap_keeps_existing_capability_contract(self):
        verified = method('verifyV2')
        self.assertIn('JSONObject caps = result.getJSONObject("capabilities")', verified)
        self.assertIn('PermissionSet granted = permissionContract(result, account)', verified)
        self.assertIn('applyPermissionSet(account, granted);', verified)
        self.assertIn('if (chatAllowed()) loadRooms();', verified)
        contract = SOURCE[SOURCE.index('private static final class PermissionSet'):
                          SOURCE.index('private PermissionSet rememberedPermissions(')]
        self.assertIn('source.getInt("version") != 1', contract)
        self.assertIn('source.get("revision")', contract)
        self.assertIn('value instanceof Number', contract)
        self.assertIn('requiredFlag(source, "chat_view")', contract)
        self.assertIn('requiredFlag(source, "order_create")', contract)
        self.assertIn('requiredFlag(source, "order_receive")', contract)
        self.assertIn('Incomplete order permissions', contract)

    def test_independent_order_create_receive_and_view_guards(self):
        selectors = method('updateOrderSelectors')
        self.assertIn('setVisibility(orderCanCreate ? View.VISIBLE', selectors)
        self.assertIn('setVisibility(orderCanReceive ? View.VISIBLE', selectors)
        self.assertIn('if ("orders".equals(section) && !orderCanView) continue;',
                      method('renderBottomTabs'))
        self.assertIn('if (!mine && !orderCanCreate) return;', method('showOrderMode'))
        self.assertIn('if (!orderCanReceive) return;', method('showReceiptMode'))
        self.assertIn('if (!orderCanCreate || !verified', method('sendPendingOrder'))
        self.assertIn('|| !orderCanReceive', method('sendPendingReceipt'))
        self.assertIn('permissionSet.orderCreate', method('applyOrderRights'))
        self.assertIn('permissionSet.orderReceive', method('applyOrderRights'))

    def test_revocation_removes_only_disallowed_local_data(self):
        apply = method('applyPermissionSet')
        self.assertIn('historyCache.purgeAccount(scope)', apply)
        self.assertIn('outbox.purgeAccount(scope)', apply)
        self.assertIn('purgeRevokedMedia(scope)', apply)
        self.assertIn('taskCreatePreferences().edit().remove(scope.key)', apply)
        self.assertIn('if (!next.chatView)', apply)
        self.assertIn('if (!next.chatSend || !next.chatView)', apply)
        self.assertIn('if (!next.media || !next.chatView) purgeRevokedMedia(scope)', apply)
        self.assertIn('else if (!next.chatSend) cancelRevokedMediaSending(scope)', apply)
        self.assertIn('public void purgeAccount(AccountScope account)', HISTORY)
        self.assertIn('public void purgeAccount(AccountScope account)', OUTBOX)
        self.assertIn('public synchronized void purgeAccount(AccountScope account)', MEDIA)
        self.assertIn('"account_key=?"', HISTORY)
        self.assertIn('"account_key=?"', OUTBOX)
        order = method('setOrderRights')
        self.assertIn('orderCreatePreferences().edit().remove(scope.key)', order)
        self.assertIn('receiptConfirmPreferences().edit().remove(scope.key)', order)
        self.assertIn('orderSummaries.clear()', order)

    def test_offline_history_is_not_revoked_by_unrelated_option(self):
        offline = method('offerOfflineHistory', 'boolean')
        self.assertIn('rememberedPermissions(candidate)', offline)
        self.assertIn('(history == null || !saved.chatView)', offline)
        self.assertIn('(taskSnapshot == null || !saved.taskView)', offline)
        apply = method('applyPermissionSet')
        self.assertNotIn('purgeHistory();\n        if (!next.taskView)', apply)
        self.assertIn('if (!next.taskView)', apply)
        self.assertIn('if (!next.chatView)', apply)

    def test_offline_task_cache_is_bounded_scoped_and_labelled(self):
        task_cache = (ROOT / 'app/src/main/java/com/baseer/freshchat/sync/TaskOfflineCache.java').read_text()
        self.assertIn('MAX_PAGES_PER_ACCOUNT = 4', task_cache)
        self.assertIn('MAX_BYTES_PER_ACCOUNT = 2L * 1024 * 1024', task_cache)
        self.assertIn('account_key,room_id,state_filter,company_key', task_cache)
        self.assertIn('companyIds.contains(companyId)', task_cache)
        self.assertIn('purgeExceptCompanySet', task_cache)
        self.assertIn('offlineNotice(true)', method('showCachedTasks'))
        self.assertIn('offlineChatVerifiedAt = snapshot == null ? 0 : snapshot.verifiedAt', SOURCE)
        self.assertIn('offlineTaskVerifiedAt = taskSnapshot == null ? 0 : taskSnapshot.verifiedAt', SOURCE)

    def test_task_tabs_use_all_open_and_done_filters(self):
        self.assertIn('selectTaskState("open")', SOURCE)
        self.assertIn('selectTaskState("done")', SOURCE)
        self.assertIn('"open".equals(taskStateFilter)', method('updateTaskTabs'))

    def test_bridge_navigation_cannot_hang_before_bootstrap(self):
        self.assertIn('BRIDGE_NAVIGATION_TIMEOUT_MILLIS', SOURCE)
        watchdog = method('scheduleBridgeNavigationTimeout')
        self.assertIn('offerOfflineHistory()', watchdog)
        self.assertIn('fail(R.string.auth_network_error)', watchdog)
        opened = method('openWeb')
        self.assertIn('scheduleBridgeNavigationTimeout(web, currentWeb)', opened)
        self.assertIn('cancelBridgeNavigationTimeout()', method('releaseWeb'))

    def test_read_only_media_can_play_and_view_but_cannot_upload(self):
        contract = SOURCE[SOURCE.index('private static final class PermissionSet'):
                          SOURCE.index('private PermissionSet rememberedPermissions(')]
        self.assertIn('this.media = media && this.chatView;', contract)
        self.assertNotIn('this.media = media && this.chatSend;', contract)
        self.assertIn('return sendAllowed() && mediaAllowed();',
                      method('mediaUploadAllowed', 'boolean'))
        for name in ('toggleInlineAudio', 'openConnectedMedia', 'readConnectedMedia'):
            self.assertIn('mediaAllowed()', method(name))
            self.assertNotIn('mediaUploadAllowed()', method(name))
        for name in ('chooseConnectedMedia', 'toggleConnectedVoice',
                     'retryConnectedMedia', 'sendConnectedMedia'):
            self.assertIn('mediaUploadAllowed()', method(name))
        cancel = method('cancelRevokedMediaSending')
        self.assertIn('mediaStore.purgeAccount(scope)', cancel)
        self.assertNotIn('closeMediaRead()', cancel)
        self.assertNotIn('clearMediaReadCache()', cancel)
        self.assertIn('clearMediaReadCache()', method('purgeRevokedMedia'))

    def test_company_revoke_purges_only_removed_company_history(self):
        refresh = method('refreshPermissionSet')
        self.assertIn('stillVerified.retainAll(validCompanies)', refresh)
        self.assertIn('restrictCompanyScope(scoped, stillVerified)', refresh)
        revoke = method('restrictCompanyScope')
        self.assertIn('historyCache.purgeRoom(scope, room.id)', revoke)
        self.assertIn('if (allowed.contains(room.companyId)) retainedRooms.add(room.id)', revoke)
        self.assertIn('outbox.purgeExceptRooms(scope, retainedRooms)', revoke)
        self.assertIn('mediaStore.purgeCompaniesNotIn(scope, allowed)', revoke)
        self.assertIn('rooms.removeIf(room -> !allowed.contains(room.companyId))', revoke)
        self.assertIn('v1Companies.addAll(allowed)', revoke)
        self.assertNotIn('logout()', revoke)
        self.assertIn('public void purgeExceptRooms(AccountScope account', OUTBOX)
        self.assertIn('public synchronized void purgeCompaniesNotIn(AccountScope account', MEDIA)
        self.assertIn('v1Companies.contains(candidate.optLong("id"))',
                      method('refreshChatCompanySelector'))

    def test_company_swap_revokes_old_before_verifying_new(self):
        refresh = method('refreshPermissionSet')
        self.assertLess(refresh.index('stillVerified.retainAll(validCompanies)'),
                        refresh.index('restrictCompanyScope(scoped, stillVerified)'))
        self.assertLess(refresh.index('restrictCompanyScope(scoped, stillVerified)'),
                        refresh.index('revalidateCompanyIdentity(scoped)'))
        self.assertIn('boolean newCompanies = !v1Companies.containsAll(validCompanies)', refresh)
        recheck = method('revalidateCompanyIdentity')
        self.assertIn('verified = false;', recheck)
        self.assertIn('openWeb(BRIDGE);', recheck)
        self.assertNotIn('logout()', recheck)

    def test_permission_changes_opt_in_and_403_does_not_logout(self):
        self.assertIn('&limit=100&permissions_version=1', SOURCE)
        hint = method('applyLiveHint')
        self.assertIn('"permissions".equals(kind)', hint)
        self.assertIn('handler.post(this::refreshPermissionSet)', hint)
        resumed = SOURCE[SOURCE.index('@Override protected void onResume()'):
                         SOURCE.index('@Override public void onBackPressed()')]
        self.assertIn('handler.post(this::refreshPermissionSet)', resumed)
        for name in ('sendPendingOrder', 'sendPendingReceipt'):
            action = method(name)
            self.assertIn('if (status == 403)', action)
            self.assertIn('discoverOrders();', action)
            self.assertNotIn('if (status == 403) { denyOrdersForSession(); return; }', action)


if __name__ == '__main__':
    unittest.main(verbosity=2)
