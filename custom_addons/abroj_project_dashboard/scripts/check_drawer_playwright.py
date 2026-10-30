"""Exercise the drawer against a disposable demo database and save mobile screenshots."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(os.environ.get('M5_SCREENSHOT_DIR', '/workspace/abroj-dashboard-impl'))
BASE = os.environ.get('M5_BASE_URL', 'http://127.0.0.1:53109')

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
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
        page.wait_for_function('data && data.projects.length > 6', timeout=60000)
        page.evaluate("lang => {localStorage.setItem('abroj.language', lang); location.reload()}", lang)
        page.wait_for_function('data && data.projects.length > 6', timeout=60000)
        page.evaluate("detail(data.projects.find(p => p.name === 'فيلا أم فالح').id)")
        page.locator('.fab').wait_for()
        name = page.evaluate('currentProject.name')
        page.locator('.menu-button').click()
        toggle = page.locator('.drawer-project-toggle')
        assert toggle.get_attribute('aria-expanded') == 'false'
        assert toggle.inner_text() == name
        assert page.locator('.drawer-project-link').inner_text() == ('المشاريع' if lang == 'ar' else 'Projects')
        assert page.locator('#drawer button').filter(has_text='+').count() == 0
        assert page.locator('#drawer-project-panel').get_attribute('inert') is not None
        page.screenshot(path=str(OUT / f'm5_{lang}_drawer_collapsed.png'))
        toggle.click()
        page.wait_for_function("document.querySelectorAll('#drawer-projects button').length > 6")
        assert toggle.get_attribute('aria-expanded') == 'true'
        assert page.locator('#drawer-project-search input').is_visible()
        archive = page.locator('.drawer-archive')
        assert archive.locator('summary').inner_text().startswith('أرشيف' if lang == 'ar' else 'Archive')
        assert archive.locator('button').count() > 0
        assert not archive.locator('button').first.is_visible()
        page.screenshot(path=str(OUT / f'm5_{lang}_drawer_expanded.png'))
        page.locator('#drawer-project-search input').fill(name)
        assert page.locator('#drawer-projects button').count() == page.evaluate('(q) => drawerAllProjects.filter(p => p.name.toLocaleLowerCase().includes(q.toLocaleLowerCase())).length', name)
        page.evaluate('closeDrawer()')
        page.locator('.menu-button').click()
        assert toggle.get_attribute('aria-expanded') == 'true'
        page.reload()
        page.wait_for_function('data && data.projects.length > 6', timeout=60000)
        page.locator('.menu-button').click()
        assert toggle.get_attribute('aria-expanded') == 'true'
        page.wait_for_function("document.querySelectorAll('#drawer-projects button').length > 6")
        page.locator('#drawer-projects button').first.click()
        page.locator('.fab').wait_for()
        page.locator('.menu-button').click()
        assert toggle.get_attribute('aria-expanded') == 'false'
        toggle.click()
        toggle.click()
        assert toggle.get_attribute('aria-expanded') == 'false'
        assert page.evaluate("getComputedStyle(document.querySelector('#drawer-project-panel')).transitionDuration") in ('0s', '1e-05s', '0.00001s')
        page.locator('.drawer-project-link').click()
        page.locator('.projects-header button').wait_for()
        page.wait_for_function("document.querySelectorAll('#project-list section').length === 2")
        assert page.locator('#project-list section').nth(1).locator('.project').count() > 0
        assert page.locator('.projects-header button').inner_text() == ('+ مشروع جديد' if lang == 'ar' else '+ New project')
        if not os.environ.get('M5_SCREENSHOTS_ONLY'):
            page.locator('.projects-header button').click()
            page.locator('#new-project-form input').fill('Playwright ' + lang)
            page.locator('#new-project-form button').click()
            page.locator('.fab').wait_for()
            assert page.locator('#app h2').inner_text() == 'Playwright ' + lang
        assert not errors, errors
        context.close()
        print(f'{lang}: drawer checks passed')
    browser.close()
