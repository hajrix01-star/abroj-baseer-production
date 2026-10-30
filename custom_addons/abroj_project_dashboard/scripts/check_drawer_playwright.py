"""Exercise the drawer against an Odoo demo database and save mobile screenshots."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(os.environ.get('M5_SCREENSHOT_DIR', '/workspace/abroj-dashboard-impl'))
BASE = os.environ.get('M5_BASE_URL', 'http://127.0.0.1:53109')

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    try:
        for lang in ('ar', 'en'):
            context = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2,
                                          is_mobile=True, has_touch=True, reduced_motion='reduce')
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(BASE + '/abroj/app')
            page.locator('[name=login]').fill(os.environ.get('M5_USER', 'owner'))
            page.locator('[name=password]').fill(os.environ.get('M5_PASSWORD', 'owner'))
            page.locator('button[type=submit]').click()
            page.wait_for_url('**/abroj/app**', timeout=60000)
            page.wait_for_function('typeof data !== "undefined" && data && data.projects.length', timeout=60000)
            page.evaluate("lang => {localStorage.setItem('abroj.language', lang); location.hash='#/my-day'; location.reload()}", lang)
            page.wait_for_function('typeof data !== "undefined" && data && data.projects.length', timeout=60000)
            page.locator('.menu-button').click()
            page.wait_for_function('drawerAllProjects.length > 0')
            toggle = page.locator('.drawer-project-toggle')
            assert toggle.get_attribute('aria-expanded') == 'false'
            assert toggle.inner_text() == ('المشاريع' if lang == 'ar' else 'Projects')
            assert page.locator('#drawer-project-panel').get_attribute('inert') is not None
            page.screenshot(path=str(OUT / f'm5_{lang}_drawer_collapsed.png'))
            toggle.locator('.drawer-project-title').click()
            assert toggle.get_attribute('aria-expanded') == 'true'
            assert page.locator('.drawer-project-row').count() == page.evaluate('drawerAllProjects.length')
            assert page.locator('.drawer-project-row svg').count() == page.evaluate('drawerAllProjects.length')
            page.locator('.drawer-project-row').first.click()
            page.locator('.fab').wait_for()
            page.locator('.menu-button').click()
            page.wait_for_function('document.querySelectorAll(".drawer-project-row").length > 0')
            assert toggle.get_attribute('aria-expanded') == 'true'
            assert page.locator('.drawer-project-row.selected').count() == 1
            assert page.locator('.drawer-project-row.selected').get_attribute('aria-current') == 'page'
            assert page.locator('.drawer').evaluate('(el) => el.getBoundingClientRect().width') <= 390 * .85
            page.screenshot(path=str(OUT / f'm5_{lang}_drawer_expanded.png'))
            toggle.locator('.drawer-chevron').click()
            assert toggle.get_attribute('aria-expanded') == 'false'
            toggle.click()
            page.locator('.drawer-all-projects').click()
            page.locator('.projects-header').wait_for()
            page.locator('#bottom-nav [data-route=projects]').click()
            page.locator('.projects-header').wait_for()
            assert not errors, errors
            await_restore = "async () => {await rpc('/abroj/app/language',{lang:'ar'}); localStorage.setItem('abroj.language','ar')}"
            page.evaluate(await_restore)
            context.close()
            print(f'{lang}: drawer checks passed')
    finally:
        # Language changes made by initialization are persisted on the account.
        page.evaluate("async () => {await rpc('/abroj/app/language',{lang:'ar'}); localStorage.setItem('abroj.language','ar')}") if not page.is_closed() else None
        browser.close()
