"""Abroj "remember me": checked -> 90-day persistent cookie, unchecked -> browser-session cookie.

Odoo always emits ``session_id`` with Max-Age = sessions.max_inactivity_seconds
(7 days). When the user signs in from the Abroj login page with the box
unchecked we store ``abroj_remember = False`` in the session; every later
re-emission of the cookie is rewritten without Expires/Max-Age so the browser
drops it when it is closed. The server-side session still expires normally.
"""
import werkzeug

from odoo import http

REMEMBER_SECONDS = 90 * 24 * 3600  # keep in sync with data/login_session.xml

_orig_save_session = http.Request._save_session


def _abroj_save_session(self, env=None):
    _orig_save_session(self, env)
    sess = self.session
    remember = sess.get('abroj_remember')
    if not sess.uid or remember is None:
        return
    headers = self.future_response.headers
    cookies = headers.getlist('Set-Cookie')
    if not any(c.startswith('session_id=') for c in cookies):
        return
    headers.remove('Set-Cookie')
    for c in cookies:
        if not c.startswith('session_id='):
            headers.add('Set-Cookie', c)
    werkzeug.Response.set_cookie(self.future_response, 'session_id', sess.sid,
                                 max_age=REMEMBER_SECONDS if remember else None,
                                 expires=None, httponly=True)


if not getattr(http.Request._save_session, '_abroj_patched', False):
    _abroj_save_session._abroj_patched = True
    http.Request._save_session = _abroj_save_session
