// Clicking anywhere on a .job-card opens its full detail page on
// WorkVista. Clicking the "View job" / "Apply now" link inside a card
// still goes straight to the external source - see TRENDING.md for
// why the distinction matters (detail page = browse on WorkVista,
// that link = where the user actually applies).
document.addEventListener('click', function (event) {
    var card = event.target.closest('.job-card[data-href]');

    if (!card) return;
    if (event.target.closest('a, button, form')) return;

    window.location.href = card.dataset.href;
});

document.addEventListener('keydown', function (event) {
    if (event.key !== 'Enter' && event.key !== ' ') return;

    var card = event.target.closest('.job-card[data-href]');

    if (!card || event.target !== card) return;

    event.preventDefault();
    window.location.href = card.dataset.href;
});
