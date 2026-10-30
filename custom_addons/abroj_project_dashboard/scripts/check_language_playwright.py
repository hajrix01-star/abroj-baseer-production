"""Check local Arabic switching when the language RPC cannot sync the account."""
import os

from playwright.sync_api import sync_playwright

base = os.environ['M5_BASE_URL']
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    page = browser.new_page()
    page.goto(base + '/abroj/app')
    page.locator('[name=login]').fill(os.environ.get('M5_USER', 'admin'))
    page.locator('[name=password]').fill(os.environ.get('M5_PASSWORD', 'admin'))
    page.locator('button[type=submit]').click()
    page.wait_for_function('data')
    page.evaluate("localStorage.setItem('abroj.language', 'en'); location.reload()")
    page.wait_for_function('data && document.documentElement.lang === "en"')
    page.route('**/abroj/app/language', lambda route: route.fulfill(
        json={'jsonrpc': '2.0', 'id': 1, 'result': {'ok': True, 'server_synced': False, 'ui_lang': 'ar'}}))
    page.locator('#language').click()
    page.wait_for_function('data && document.documentElement.dir === "rtl"')
    assert page.evaluate("localStorage.getItem('abroj.language')") == 'ar'
    assert 'تعذرت مزامنتها' in page.locator('#toast').inner_text()
    browser.close()
    print('Arabic local fallback: passed')
