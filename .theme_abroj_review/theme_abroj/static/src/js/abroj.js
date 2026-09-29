/** @odoo-module **/

document.addEventListener('DOMContentLoaded', () => {
  const site = document.querySelector('.abroj-site');
  if (!site) return;

  const targets = site.querySelectorAll(
    '.abroj-heading-grid, .abroj-service-card, .abroj-steps article, .abroj-work-card, .abroj-value__panel, .abroj-xray__copy'
  );

  targets.forEach((el) => el.classList.add('abroj-reveal'));

  if (!('IntersectionObserver' in window)) {
    targets.forEach((el) => el.classList.add('is-visible'));
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });

  targets.forEach((el) => observer.observe(el));
});
