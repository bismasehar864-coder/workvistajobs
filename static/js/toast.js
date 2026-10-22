// Toasts fade themselves out after a few seconds so a confirmation
// doesn't sit on the page forever. Dismissing by hand still works, and
// if this script never runs the toast simply stays put and readable -
// it is plain markup, not something JS builds.
(function () {
    var VISIBLE_MS = 4000;

    document.querySelectorAll('.toast').forEach(function (toast, index) {

        // Errors stay until dismissed: they usually say something the
        // reader has to act on.
        if (toast.classList.contains('toast--error')) return;

        window.setTimeout(function () {
            toast.classList.add('toast--leaving');

            toast.addEventListener('transitionend', function () {
                toast.remove();
            }, { once: true });

        }, VISIBLE_MS + index * 400);
    });
})();
