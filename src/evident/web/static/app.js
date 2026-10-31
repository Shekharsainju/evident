(() => {
  const popover = document.querySelector('#receipt-popover');
  if (!(popover instanceof HTMLDialogElement)) return;
  const content = popover.querySelector('.popover-content');
  if (!content) return;

  const close = () => popover.close();
  popover.addEventListener('click', (event) => { if (event.target === popover) close(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && popover.open) close(); });

  document.addEventListener('click', async (event) => {
    const claim = event.target.closest('[data-claim-id]');
    if (!claim || !claim.closest('.profile')) return;
    const link = claim.closest('a[href]');
    if (!link) return;
    event.preventDefault();
    content.textContent = 'Loading evidence receipt…';
    popover.showModal();
    try {
      const url = new URL(link.href, window.location.origin);
      url.searchParams.set('partial', '1');
      const response = await fetch(url, { headers: { Accept: 'text/html' } });
      if (!response.ok) throw new Error('Receipt unavailable');
      content.innerHTML = await response.text();
      const button = content.querySelector('[data-close-receipt]');
      if (button) button.addEventListener('click', close);
    } catch (_) {
      content.textContent = 'The evidence receipt could not be loaded.';
    }
  });
})();
