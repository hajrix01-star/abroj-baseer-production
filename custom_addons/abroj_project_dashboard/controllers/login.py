"""Abroj bilingual login page with a real "remember me" option."""

from odoo import http
from odoo.addons.web.controllers.home import Home
from odoo.http import request

LOGIN_LANGS = {'ar': 'ar_001', 'en': 'en_US'}
LANG_COOKIE = 'frontend_lang'

LABELS = {
    'ar': {
        'title': 'أهلاً بك في أبرج', 'welcome': 'مساحة واحدة لإدارة مشاريعك',
        'login': 'البريد الإلكتروني أو اسم المستخدم', 'password': 'كلمة المرور',
        'remember': 'تذكرني', 'forgot': 'نسيت كلمة المرور؟', 'submit': 'تسجيل الدخول',
        'footer': '© أبرج للمقاولات', 'show': 'إظهار كلمة المرور',
        'target_label': 'وجهة الدخول', 'target_app': 'أدخل المشاريع', 'target_odoo': 'أدخل أودو',
        'switch': 'English', 'tagline': 'من التخطيط إلى الإنجاز',
    },
    'en': {
        'title': 'Sign in', 'welcome': 'Welcome to Abroj',
        'login': 'Email or username', 'password': 'Password',
        'remember': 'Remember me', 'forgot': 'Forgot password?', 'submit': 'Sign in',
        'footer': '© Abroj Contracting', 'show': 'Show password',
        'target_label': 'Sign in to', 'target_app': 'Projects app', 'target_odoo': 'Odoo backend',
        'switch': 'عربي', 'tagline': 'From planning to delivery',
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


APP_PATHS = ('/abroj/app', '/app')
APP_LOGIN_PATHS = ('/abroj/app/login', '/app/login')


def _is_app_path(url):
    url = (url or '').split('?')[0].split('#')[0]
    return any(url == p or url.startswith(p + '/') for p in APP_PATHS) and url not in APP_LOGIN_PATHS


def _login_target(redirect, kw):
    """'app' (Abroj projects PWA) or 'odoo' (backend)."""
    target = kw.get('abroj_target')
    if target in ('app', 'odoo'):
        return target
    if request.httprequest.path in APP_LOGIN_PATHS or _is_app_path(redirect):
        return 'app'
    if redirect:
        return 'odoo'
    return 'app'


class AbrojLogin(Home):

    @http.route(['/web/login', '/app/login', '/abroj/app/login'], type='http', auth='none', readonly=False)
    def web_login(self, redirect=None, **kw):
        path = request.httprequest.path
        if path in APP_LOGIN_PATHS and not redirect:
            redirect = '/app' if path == '/app/login' else '/abroj/app'
        target = _login_target(redirect, kw)
        if request.httprequest.method == 'POST':
            # One shared form: the chosen destination decides where we land.
            if target == 'app' and not _is_app_path(redirect):
                redirect = '/abroj/app'
            elif target == 'odoo' and (not redirect or _is_app_path(redirect)):
                redirect = '/odoo'
        request.params['abroj_target'] = target
        request.params['redirect'] = redirect
        short = _login_lang()
        code = LOGIN_LANGS[short]
        installed = {c for c, _n in request.env['res.lang'].sudo().get_installed()}
        if code in installed:
            request.update_context(lang=code)
        request.params['abroj_lang'] = short
        request.params['abroj_labels'] = LABELS[short]
        response = super().web_login(redirect=redirect, **kw)
        if request.params.get('login_success'):
            # 'Projects' chosen by a user without projects access (or outside
            # the Abroj company): fall back to the Odoo backend gracefully.
            user = request.env['res.users'].browse(request.session.uid)
            if _is_app_path(redirect) and not user.with_user(user)._abroj_can_use_projects_app(user.company_id):
                response = request.redirect('/odoo')
            # Unchecked box -> browser-session cookie (see models/session_cookie.py).
            request.session['abroj_remember'] = bool(kw.get('remember'))
            # Remember the username only (never the password) after a successful login.
            if kw.get('remember') and kw.get('login'):
                response.set_cookie('abroj_last_login', kw['login'].strip()[:200], max_age=365 * 24 * 3600, samesite='Lax', cookie_type='optional')
            else:
                response.delete_cookie('abroj_last_login')
        if kw.get('lang') in LOGIN_LANGS or kw.get('lang') in LOGIN_LANGS.values():
            response.set_cookie(LANG_COOKIE, code, max_age=365 * 24 * 3600, cookie_type='optional')
        return response


class AbrojSwitch(http.Controller):

    @http.route(['/abroj/switch', '/app/switch'], type='http', auth='user', methods=['GET'], website=True)
    def abroj_switch(self, **kw):
        """Logged-in app chooser: Odoo backend or the projects PWA (no password form).

        website=True: with the website module installed, web.frontend_layout
        needs the request's website (otherwise KeyError 'website' -> 500).
        """
        if not request.env.user._abroj_can_use_projects_app():
            return request.redirect('/odoo')
        short = 'ar' if (request.env.user.lang or '').startswith('ar') else 'en'
        request.params['abroj_lang'] = short
        request.params['abroj_labels'] = dict(LABELS[short], switch='')
        return request.render('abroj_project_dashboard.abroj_switch', {
            'L': LABELS[short], 'switch_title': 'تبديل التطبيق' if short == 'ar' else 'Switch app',
            'user_name': request.env.user.name})
