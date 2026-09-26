if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/employee-app/sw.js', { scope: '/employee-app/' }).catch(() => {});
}

document.querySelectorAll('[data-app-drawer]').forEach((drawer) => {
    const trigger = document.querySelector('[data-app-menu-toggle]');
    const backdrop = document.querySelector('.shift-drawer-backdrop');
    const closeButtons = document.querySelectorAll('[data-app-menu-close]');
    if (!trigger || !backdrop) return;
    const setOpen = (open, focusTrigger = false) => {
        drawer.classList.toggle('is-open', open);
        drawer.setAttribute('aria-hidden', String(!open));
        trigger.setAttribute('aria-expanded', String(open));
        backdrop.hidden = !open;
        requestAnimationFrame(() => backdrop.classList.toggle('is-open', open));
        document.body.classList.toggle('has-shift-menu-open', open);
        if (focusTrigger) trigger.focus();
    };
    trigger.addEventListener('click', () => setOpen(true));
    closeButtons.forEach((button) => button.addEventListener('click', () => setOpen(false, true)));
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && drawer.classList.contains('is-open')) setOpen(false, true);
    });
});

document.querySelectorAll('.check-item').forEach((form) => {
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const button = form.querySelector('button');
        if (button.disabled) return;
        button.disabled = true;
        try {
            const response = await fetch(form.action, {
                method: 'POST',
                body: new FormData(form),
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            if (!response.ok) throw new Error('Checklist update failed');
            const result = await response.json();
            form.classList.toggle('is-done', result.done);
            form.querySelector('.checkmark').textContent = result.done ? '✓' : '';
            document.querySelector('[data-opening-completion]').textContent = `${result.completion}٪`;
            document.querySelector('[data-opening-progress]').style.width = `${result.completion}%`;
        } catch (_) {
            window.alert('تعذر حفظ التحديث. أعد المحاولة.');
        } finally {
            button.disabled = false;
        }
    });
});

document.querySelectorAll('[data-task-item-form]').forEach((form) => {
    const items = form.querySelector('[data-task-items]');
    const addButton = form.querySelector('[data-add-task-item]');
    const rowTemplate = form.querySelector('template[data-task-item-template]');
    const itemCount = () => items.querySelectorAll('input[name="task_item"]').length;

    addButton.addEventListener('click', () => {
        if (itemCount() >= 10) return;
        items.append(rowTemplate.content.cloneNode(true));
    });
    items.addEventListener('click', (event) => {
        const removeButton = event.target.closest('[data-remove-task-item]');
        if (!removeButton || itemCount() <= 1) return;
        removeButton.closest('.task-item-input').remove();
    });
});

document.querySelectorAll('[data-photo-picker-open]').forEach((openButton) => {
    const dialog = document.getElementById(openButton.dataset.photoPickerOpen);
    if (!dialog) return;
    openButton.addEventListener('click', () => dialog.showModal());
    dialog.querySelector('[data-photo-picker-close]').addEventListener('click', () => dialog.close());
    dialog.querySelectorAll('input[type="file"]').forEach((input) => {
        input.addEventListener('change', () => {
            if (input.files.length) dialog.close();
        });
    });
});

document.querySelectorAll('[data-followup-tabs]').forEach((tabs) => {
    const panels = document.querySelectorAll('[data-followup-panel]');
    tabs.querySelectorAll('[data-followup-tab]').forEach((button) => {
        button.addEventListener('click', () => {
            const selected = button.dataset.followupTab;
            tabs.querySelectorAll('[data-followup-tab]').forEach((tab) => tab.classList.toggle('is-active', tab === button));
            panels.forEach((panel) => panel.classList.toggle('is-active', panel.dataset.followupPanel === selected));
        });
    });
});
