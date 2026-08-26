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
import json

import streamlit.components.v1 as components

# param name (as it appears in the URL) -> localStorage key. Add an entry
# here for every new client-side-persisted feature; the page that needs it
# just needs to call register() then redirect() itself (see following.py's
# and predictions.py's page-level callers for the pattern).
_KEYS = {}


def register(param: str, storage_key: str) -> None:
    _KEYS[param] = storage_key


def redirect(also_set: dict | None = None) -> None:
    """Hydrate every registered key from localStorage into the URL, then
    navigate ONCE if anything changed. No-ops if every registered key is
    already in the URL or has nothing saved — safe to call on every render.

    `also_set` is {localStorage key: exact string value} to write before
    deciding whether to navigate; a key whose stored value differs counts
    as a change, so this function's single navigation doubles as the page
    reload those keys need to take effect. It exists so callers that need
    to write localStorage AND reload don't add a SECOND navigator to the
    page — see the module docstring for why two racing navigations
    silently eat each other's data. (Concretely: a separate theme-sync
    script navigating in parallel with this one meant whichever won, the
    other's work was lost — landing on a URL with no ?prefs=, so the
    visitor's saved theme was unknown and the page came back in the wrong
    colours, then this redirect fired again and the two ping-ponged.)
    """
    if not _KEYS and not also_set:
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
            // Extra localStorage writes that need a reload to take effect
            // (Streamlit's own stActiveTheme-* keys). Verified by reading
            // back: if a write silently fails (quota, private mode) we must
            // NOT count it as a change, or every load would navigate again
            // forever trying to apply something that never sticks.
            const extra = {json.dumps(also_set or {})};
            Object.keys(extra).forEach(function(k) {{
                if (localStorage.getItem(k) !== extra[k]) {{
                    try {{ localStorage.setItem(k, extra[k]); }} catch (e) {{ return; }}
                    if (localStorage.getItem(k) === extra[k]) changed = true;
                }}
            }});
            if (!changed) {{ sessionStorage.removeItem('dm_nav_guard'); return; }}
            // Belt and braces against a reload loop: whatever the cause, never
            // navigate more than a few times in one session without reaching a
            // steady state. Cleared above the moment a render needs no
            // navigation at all, so normal use never accumulates.
            const tries = parseInt(sessionStorage.getItem('dm_nav_guard') || '0', 10);
            if (tries >= 3) return;
            sessionStorage.setItem('dm_nav_guard', String(tries + 1));
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
