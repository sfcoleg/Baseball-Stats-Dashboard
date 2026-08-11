"""Single combined localStorage -> query-param redirect for every feature
that persists client-side (see following.py, predictions.py). Each such
module used to fire its OWN redirect script independently on a fresh
session; with two (or more) of those on the same page, whichever navigated
first could tear down the others' iframes mid-script before they ran,
silently dropping their data. Doing the check-and-redirect ONCE here, for
every registered storage key at once, avoids that race entirely — there's
only ever one navigation.

IMPORTANT: redirect() must be called from WITHIN a routed page's own script
(e.g. pages/13_Following.py, pages/8_Todays_Games.py) — NOT from main.py.
Empirically, any st.components.v1.html() call made from main.py (whether
before or after st.navigation()'s pg.run()) never actually executes its
script in the browser; only components.html calls made from inside the
page that pg.run() routes to reliably do. register() itself is plain
Python (no rendering), so it's fine to call from main.py.
"""
import streamlit.components.v1 as components

# param name (as it appears in the URL) -> localStorage key. Add an entry
# here for every new client-side-persisted feature; the page that needs it
# just needs to call register() then redirect() itself (see following.py's
# and predictions.py's page-level callers for the pattern).
_KEYS = {}


def register(param: str, storage_key: str) -> None:
    _KEYS[param] = storage_key


def redirect() -> None:
    """Call from within a page's own script (see module docstring for why),
    after that page's own register() call. No-ops if every registered key
    is either already in the URL or has nothing saved yet — safe to call
    on every render."""
    if not _KEYS:
        return
    # Each check needs its own variable name — with 2+ registered keys,
    # `const saved` declared once per check in this shared function scope
    # would be a fatal "already declared" SyntaxError, which silently kills
    # the ENTIRE script (including the checks that would've worked fine on
    # their own) with no visible console error inside a sandboxed iframe.
    checks = "\n".join(
        f"""
        if (!url.searchParams.has('{param}')) {{
            const saved_{i} = localStorage.getItem('{storage_key}');
            if (saved_{i}) {{ url.searchParams.set('{param}', saved_{i}); changed = true; }}
        }}
        """
        for i, (param, storage_key) in enumerate(_KEYS.items())
    )
    components.html(
        f"""
        <script>
        (function() {{
            const url = new URL(window.parent.location.href);
            let changed = false;
            {checks}
            if (!changed) return;
            // components.html() renders in a sandboxed iframe without
            // allow-top-navigation, so window.parent.location.href = ...
            // is silently blocked by the browser. Workaround: build the
            // link IN the parent document (allowed via allow-same-origin)
            // and click it there, so the navigation is parent-initiated
            // rather than a cross-frame navigation from the sandboxed iframe.
            const a = window.parent.document.createElement('a');
            a.href = url.toString();
            window.parent.document.body.appendChild(a);
            a.click();
        }})();
        </script>
        """,
        height=0,
    )
