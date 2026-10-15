#!/usr/bin/env python3
"""Test-harness setup/preservation checks only; no native execution."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
def source(folder,name):return (ROOT/'tests'/folder/'com/baseer/freshchat/test'/name).read_text()
class HarnessReadiness(unittest.TestCase):
    def test_shared_guard_preserves_private_bytes_and_preferences(self):
        guard=source('android-ui-support','UiFixtureGuard.java')
        for token in ('hashFiles(context.getFilesDir())','verifyHashes(context.getFilesDir(),originals)','restorePrefs','processEditors','processOrphanEditors','STORE_IO','original root'):
            if token=='original root':self.assertIn('Ordinary root created',guard)
            else:self.assertIn(token,guard)
    def test_bubble_installs_before_launch_and_waits_for_store(self):
        text=source('android-bubbles','BubbleGeometryInstrumentation.java')
        self.assertLess(text.index('fixtureGuard.install(store)'),text.index('ActivityMonitor monitor'))
        self.assertIn('getDeclaredField("initializing")',text)
        self.assertIn('saved.get(activity)==store',text)
        self.assertIn('fixtureGuard.verifyOriginals()',text)
    def test_entry_variants_wait_and_preserve(self):
        for name in ('EntryLayoutInstrumentation.java','EntryBoundaryInstrumentation.java','EntryLifecycleInstrumentation.java'):
            text=source('android-entry-layout',name)
            self.assertIn('fixtureGuard.install(store)',text,name)
            self.assertIn('"initializing"',text,name)
            self.assertNotIn('attachmentPaths().isEmpty()',text,name)
            self.assertNotIn('Disposable attachment directory is empty',text,name)
            self.assertNotIn('field(activity, "opened")',text,name)
    def test_cross_process_checkpoint_keeps_original_hashes(self):
        text=source('android-entry-layout','EntryLifecycleInstrumentation.java')
        for token in ('entry lifecycle v2','c.originalFiles = UiFixtureGuard.hashFiles','checkpoint.originalFiles','checkpoint.recovery'):
            self.assertIn(token,text)
    def test_unsigned_builds_cannot_create_new_signing_keys(self):
        for name in ('build-editor-tests.sh','build-bubble-tests.sh','build-entry-layout-tests.sh'):
            text=(ROOT/'tools'/name).read_text()
            self.assertIn('BCHAT_UNSIGNED_ONLY',text)
            self.assertNotIn('keytool',text)
            self.assertNotIn('-genkey',text)
if __name__=='__main__':unittest.main(verbosity=2)
