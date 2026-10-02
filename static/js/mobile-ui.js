document.addEventListener('DOMContentLoaded', () => {
  // Keep input state for existing scheduling code; expose explicit toggle buttons.
  document.querySelectorAll('#page-scheduler .sch-plat-card label').forEach(label => {
    const input = label.querySelector('input[type="checkbox"]');
    if (!input) return;
    const platform = input.id.replace('sch-cb-', '');
    const pillBar = document.getElementById('sch-platform-pills');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'sch-platform-toggle';
    button.dataset.platform = platform;
    button.setAttribute('aria-pressed', String(input.checked));
    input.hidden = true;
    label.before(input);
    while (label.firstChild) button.appendChild(label.firstChild);
    button.addEventListener('click', () => {
      input.checked = !input.checked;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    if (pillBar) {
      label.remove();
      pillBar.appendChild(button);
    } else {
      label.replaceWith(button);
    }
  });
  const rotation = document.getElementById('sch-round-robin');
  if (rotation) {
    const label = rotation.closest('label');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'sch-rotation-toggle';
    button.textContent = 'Xoay vòng tài khoản';
    button.setAttribute('aria-pressed', String(rotation.checked));
    rotation.hidden = true;
    label.before(rotation);
    button.addEventListener('click', () => {
      rotation.checked = !rotation.checked;
      button.setAttribute('aria-pressed', String(rotation.checked));
    });
    label.replaceWith(button);
  }
  const arrow = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';
  const groups = [
    '#page-config .config-pane',
    '#page-publish .publish-pane',
    '#page-scheduler #sch-panel-schedule',
  ];
  for (const groupSelector of groups) {
    document.querySelectorAll(groupSelector).forEach(group => {
      const cardSelector = groupSelector.includes('scheduler') ? '.sch-section-card' : groupSelector.includes('config') ? '.cfg-card' : '.premium-card';
      const cards = group.querySelectorAll(cardSelector);
      cards.forEach((card, index) => {
        const header = groupSelector.includes('scheduler') ? card.firstElementChild : card.querySelector('.cfg-card-header, .card-header');
        if (!header) return;
        card.classList.add('mobile-accordion');
        if (header.parentElement !== card) card.classList.add('mobile-accordion-nested');
        const isScheduler = groupSelector.includes('scheduler');
        const closedInitially = isScheduler ? index === 2 || index === 4 : index > 0;
        if (closedInitially) card.classList.add('mobile-accordion-closed');
        if (isScheduler) card.style.order = String([0, 1, 3, 2, 4][index] ?? index);
        const label = (header.querySelector('.cfg-card-title, .card-title, .sch-sec-title') || header)?.textContent?.trim() || 'mục này';
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'mobile-accordion-toggle';
        button.setAttribute('aria-label', `Ẩn hoặc hiện ${label}`);
        button.setAttribute('aria-expanded', String(!closedInitially));
        button.innerHTML = arrow;
        button.addEventListener('click', () => {
          const closed = card.classList.toggle('mobile-accordion-closed');
          button.setAttribute('aria-expanded', String(!closed));
        });
        header.appendChild(button);
      });
    });
  }
});
