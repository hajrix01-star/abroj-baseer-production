#!/usr/bin/env python3
"""Narrow source regression tripwires, not Android runtime acceptance."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
main = (root / 'app/src/main/java/com/baseer/freshchat/MainActivity.java').read_text()
bubble = main.split('private View messageBubble(', 1)[1].split('private void scheduleDraftSave(', 1)[0]
checks = 0

def check(condition, description):
    global checks
    assert condition, description
    checks += 1

for label in ('sender', 'quote', 'removed', 'body'):
    check(f'bubble.addView({label}, p(-2, -2))' in bubble,
          f'{label} must contribute intrinsic width inside the wrap-content bubble')
    check(f'{label}.setMaxWidth(max - d(28))' in bubble,
          f'{label} width remains bounded by the current window')
check('LinearLayout.LayoutParams mt = p(-2, -2)' in bubble,
      'footer contributes intrinsic width for short and empty-body messages')
check('mt.gravity = Gravity.END' in bubble, 'footer stays at the logical end in RTL and LTR')
check('LinearLayout.LayoutParams bp = p(-2, -2)' in bubble, 'bubble remains content-sized')
check('bubble.addView(attachment)' in bubble, 'attachment keeps its existing explicit dimensions')
check('attachment.setOnLongClickListener' in bubble and 'showOriginalMessage(original)' in bubble,
      'attachment and quote actions remain available')
check('body.setOnLongClickListener' in bubble and 'showMessageActions(m)' in bubble, 'body opens explicit message actions')
check('selectMessageText(current)' in main and 'selection.setTextIsSelectable(true)' in main, 'explicit selectable-text action remains available without swallowing reply swipe')
check('reply.setMinHeight(d(48))' in bubble and 'R.string.foundation_reply' in bubble, 'visible Reply has a minimum 48dp touch target')
check('outer.setGravity(m.mine ? Gravity.START : Gravity.END)' in bubble,
      'mine/incoming alignment remains logical-direction aware')
print(f'PASS: {checks} bubble source contracts (native geometry tested separately)')
