"""Abroj bilingual login page with a real "remember me" option."""

from odoo import http
from odoo.addons.web.controllers.home import Home
from odoo.http import request

LOGIN_LANGS = {'ar': 'ar_001', 'en': 'en_US'}
LANG_COOKIE = 'frontend_lang'

LABELS = {
    'ar': {
        'title': 'تسجيل الدخول', 'welcome': 'مرحبًا بك في نظام أبرج',
        'login': 'البريد الإلكتروني أو اسم المستخدم', 'password': 'كلمة المرور',
        'remember': 'تذكرني', 'forgot': 'نسيت كلمة المرور؟', 'submit': 'دخول',
        'footer': '© أبرج للمقاولات', 'show': 'إظهار كلمة المرور',
    },
    'en': {
        'title': 'Sign in', 'welcome': 'Welcome to Abroj',
        'login': 'Email or username', 'password': 'Password',
        'remember': 'Remember me', 'forgot': 'Forgot password?', 'submit': 'Sign in',
        'footer': '© Abroj Contracting', 'show': 'Show password',
    },
}


def _login_lang():
    """?lang= param > frontend_lang cookie > browser Accept-Language."""
    candidates = [request.params.get('lang'), request.httprequest.cookies.get(LANG_COOKIE),
                  request.best_lang, request.httprequest.accept_languages.best]
    for cand in candidates:
        if cand:
            short = cand.replace('-', '_').split('_')[0].lower()
            if short in LOGIN_LANGS:
                return short
    return 'ar'


class AbrojLogin(Home):

    @http.route()
    def web_login(self, redirect=None, **kw):
        short = _login_lang()
        code = LOGIN_LANGS[short]
        installed = {c for c, _n in request.env['res.lang'].sudo().get_installed()}
        if code in installed:
            request.update_context(lang=code)
        request.params['abroj_lang'] = short
        request.params['abroj_labels'] = LABELS[short]
        response = super().web_login(redirect=redirect, **kw)
        if request.params.get('login_success'):
            # Unchecked box -> browser-session cookie (see models/session_cookie.py).
            request.session['abroj_remember'] = bool(kw.get('remember'))
        if kw.get('lang') in LOGIN_LANGS or kw.get('lang') in LOGIN_LANGS.values():
            response.set_cookie(LANG_COOKIE, code, max_age=365 * 24 * 3600, cookie_type='optional')
        return response
