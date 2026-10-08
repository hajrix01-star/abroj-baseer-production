from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestHubScroll(HttpCase):
    def test_real_client_action_owns_vertical_scroll(self):
        """Exercise the installed action manager, not an isolated report mount."""
        action = self.env.ref('baseer_reports_menu.action_baseer_reports_hub')
        self.browser_js(
            '/odoo/action-%s' % action.id,
            """
            const hub = document.querySelector('.o_baseer_reports_hub.o_action');
            if (!hub) { throw new Error('The real report action was not mounted'); }
            const filler = document.createElement('div');
            filler.style.height = '2200px';
            filler.style.flex = '0 0 2200px';
            const marker = document.createElement('div');
            marker.textContent = 'Last report row';
            hub.append(filler, marker);
            if (hub.scrollHeight <= hub.clientHeight) {
                throw new Error('Fixture did not extend beyond the action viewport');
            }
            if (getComputedStyle(hub).overflowY !== 'auto') {
                throw new Error('The action does not own vertical scrolling');
            }
            hub.focus();
            hub.scrollTop = hub.scrollHeight;
            requestAnimationFrame(() => {
                const last = marker.getBoundingClientRect();
                const viewport = hub.getBoundingClientRect();
                if (hub.scrollTop <= 0 || last.top < viewport.top - 1 || last.bottom > viewport.bottom + 1) {
                    throw new Error('The last report row is unreachable');
                }
                if (document.scrollingElement.scrollTop !== 0) {
                    throw new Error('The body scrolled instead of the report action');
                }
                console.log('test successful');
            });
            """,
            ready="!!document.querySelector('.o_baseer_reports_hub.o_action')",
            login='admin',
        )


class TestHubScrollMobile(TestHubScroll):
    browser_size = '375x812'
    touch_enabled = True
