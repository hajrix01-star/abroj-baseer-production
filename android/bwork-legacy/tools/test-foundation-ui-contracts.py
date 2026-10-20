#!/usr/bin/env python3
"""Fresh source tripwires. These do not replace Android lifecycle or geometry acceptance."""
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'app/src/main/java/com/baseer/bwork/legacy/MainActivity.java').read_text()
UI=(ROOT/'app/src/main/java/com/baseer/bwork/legacy/Ui.java').read_text()
EDITOR=(ROOT/'app/src/main/java/com/baseer/bwork/legacy/EditorState.java').read_text()
def method(name):
    methods=[]
    for match in re.finditer(r'private (?:static )?(?:<[^>]+> )?[\w<>?]+ '+name+r'\(',MAIN):
        opening=MAIN.index('{',match.start());depth=1;end=opening+1
        while depth: depth+=(MAIN[end]=='{')-(MAIN[end]=='}');end+=1
        methods.append(MAIN[match.start():end])
    assert methods,name
    return '\n'.join(methods)
class Foundations(unittest.TestCase):
    def test_navigation_waits_for_durability(self):
        for name in ('showList','showChat','showSettings','showModule','showPicker','exitDemo','applyLanguage'):
            self.assertIn('beforeNavigation(',method(name),name)
        self.assertIn('capturePreview()',method('showSharePreview'))
        gate=method('beforeNavigation')
        for text in ('captureEditors()','sendingEditor()','dirtyEditors()','flushEditors(','pendingNavigation','requiresReopen()'):self.assertIn(text,gate)
        self.assertIn('revealFailedEditor(failedState)',method('flushEditors'))
    def test_atomic_editor_and_independent_worker(self):
        writes=method('flushEditors')
        self.assertIn('STORE_IO.execute',writes)
        self.assertIn('targetStore.setDraft(snapshot.company, snapshot.conversation, snapshot.text, snapshot.files, snapshot.replyId)',writes)
        self.assertIn('targetStore.updatePendingSharePreview(snapshot.shareId, snapshot.text, snapshot.files)',writes)
        self.assertIn('state.committed(snapshot)',writes)
        self.assertIn('state.failed(snapshot, error)',writes)
        self.assertIn('QUERY_IO.execute(task)',method('queryOperation'))
        self.assertIn('new ArrayBlockingQueue<>(4)',MAIN)
        self.assertIn('canceled.get() || !activityAlive()',method('queryOperation'))
    def test_complete_bounded_editor_recovery(self):
        self.assertIn('MAX_RECOVERY_EDITORS = 4',MAIN)
        self.assertIn('state.dirty() || state.sending()',method('dirtyEditorCount'))
        self.assertIn('processOrphanEditors.size()',method('dirtyEditorCount'))
        self.assertIn('drafts.size() + orphans.size() > MAX_RECOVERY_EDITORS',method('restoreEditors'))
        self.assertIn('editorProcessEpoch.equals(saved.getString("editorProcess"))',method('restoreEditors'))
        self.assertIn('saved.isPendingShareResolved(value.shareId)',method('admitRecoveredEditor'))
        self.assertIn('value.sendToken, value.shareId)',method('admitRecoveredEditor'))
        self.assertIn('retainOrphan(value)',method('admitRecoveredEditor'))
    def test_preview_and_normal_mutations_share_capacity_guard(self):
        for name,guard in [('captureDraft','canEditCurrentDraft()'),('capturePreview','canEditPreview()'),('sendDraft','canEditCurrentDraft()'),('sendShare','canEditPreview()')]:
            self.assertIn(guard,method(name),name)
        files=method('renderDraftFiles')
        self.assertIn('if (!canEditCurrentDraft() || draftEditor.sending())',files)
        self.assertIn('remove.setEnabled(canEditCurrentDraft() && !draftEditor.sending())',files)
        preview=method('showSharePreview')
        self.assertIn('if (!canEditPreview() || previewEditor.sending())',preview)
        self.assertIn('remove.setEnabled(canEditPreview() && !previewEditor.sending())',preview)
        self.assertIn('send.setEnabled(canEditPreview() && !previewEditor.sending())',preview)
        self.assertIn('previewMigrationBlocked = true; previewText = legacyText; previewFiles = kept',method('loadPreview'))
    def test_send_tokens_and_uncertain_publication_are_retained(self):
        for name in ('sendDraft','sendShare'):
            body=method(name)
            self.assertIn('editor.beginSend(',body)
            self.assertIn('targetStore.requiresReopen()',body)
            self.assertIn('editor.commitUncertain(value, problem)',body)
            self.assertIn('activeActivity.get()',body)
        self.assertIn('restoreEditors(recovery, reopened)',method('reopenCurrentHistory'))
        self.assertIn('sendToken!=null',EDITOR)
        self.assertIn('Objects.equals(editorId,value.editorId)',EDITOR)
    def test_bounded_views_search_and_reading_checkpoint(self):
        self.assertIn('HISTORY_WINDOW = 30, SEARCH_WINDOW = 40',MAIN)
        self.assertIn('history.removeAllViews()',MAIN)
        self.assertIn('messageViews.clear()',MAIN)
        self.assertIn('targetStore.searchMessagePage',MAIN)
        self.assertIn('targetStore.pageAfter',MAIN)
        self.assertIn('bwork-history-newer',MAIN)
        self.assertIn('new SimpleDateFormat("d MMMM yyyy"',MAIN)
        self.assertIn('out.putSerializable("readingState"',MAIN)
        self.assertIn('composerSelectionStart',MAIN)
        self.assertIn('composer.setSelection(Math.min(start, composer.length()), Math.min(end, composer.length()))',MAIN)
    def test_transcript_is_bounded_and_streamed(self):
        self.assertIn('new BoundedTextWriter(128*1024)',method('conversationTranscript'))
        self.assertIn('targetStore.writeConversationTranscript(co,cv,writer,labels)',method('saveTranscript'))
        self.assertNotIn('getBytes',method('saveTranscript'))
        self.assertIn('CodingErrorAction.REPORT',method('utf8Writer'))
    def test_preservation_and_explicit_recovery(self):
        self.assertNotIn('.delete(',method('cleanupAttachments'))
        self.assertIn('ChatStore.restoreLastGood(file, recovery)',method('showStoreFailure'))
        self.assertIn('record.id, true).commit()',method('confirmRecoveredEditorRemoval'))
        self.assertNotIn('sendDraft',method('showRecoveredEditor'))
        self.assertNotIn('setDraft',method('showRecoveredEditor'))
        self.assertIn('PdfPreviewView(this,file)',MAIN.replace(' ',''))
if __name__=='__main__':unittest.main(verbosity=2)
