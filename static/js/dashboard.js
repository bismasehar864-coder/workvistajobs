// The dashboard's sidebar used to switch tabs in the browser, keeping
// the open section in a URL fragment and localStorage. Nothing here does
// that any more: each section is its own address (/dashboard/user/
// <section>/), the sidebar is plain links, and the server renders
// exactly one section with .active. So a reload, the back button, a
// shared link and the redirect after saving a form all land on the same
// place, which the old fragment-and-memory approach could not manage -
// a GET form submission drops the fragment, and a redirect has none.
//
// What is left is one small courtesy: clear the remembered tab from the
// previous design so an old value can't linger in anybody's browser.

(function () {
    try {
        localStorage.removeItem("activeSection");
    } catch (e) {
        // Private browsing, or storage disabled. Nothing depends on it.
    }
})();
