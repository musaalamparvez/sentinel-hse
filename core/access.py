"""Access-code gating shared by the supervisor dashboard (#11) and the
assignee report detail page (#8), per #10.

Neither of those pages is open to the public internet, but this project
has no user accounts. Instead, both are gated behind a single shared
access code (or set of codes) configured via the DJANGO_ACCESS_CODES env
var (see settings.ACCESS_CODES) — never hardcoded, never in the DB.

Usage: decorate any view that should require the code.

    from core.access import require_access_code

    @require_access_code
    def dashboard(request):
        ...

The code can arrive as a URL query param (``?code=...``), a POST form
field, or — once entered successfully — an existing session cookie, so
the user isn't re-prompted on every page view within that session.
"""

from functools import wraps

from django.conf import settings
from django.shortcuts import redirect, render

SESSION_KEY = "has_valid_access_code"

# Rendered whenever the gate blocks a request; the caller's own template
# is never reached, so this must not leak anything about the page behind
# the gate.
PROMPT_TEMPLATE = "core/access_code_prompt.html"


def _valid_codes():
    return set(settings.ACCESS_CODES)


def _submitted_code(request):
    """The code the caller supplied this request, from the form field
    (POST) or the URL param (GET), or None if neither was given."""
    return request.POST.get("code") or request.GET.get("code") or None


def has_valid_session(request):
    """Whether this session already has a verified access code."""
    return bool(request.session.get(SESSION_KEY))


def require_access_code(view_func):
    """View decorator that gates ``view_func`` behind a valid access code.

    - A session that already holds a verified code passes straight
      through — no re-prompting within the session.
    - A code submitted via the ``code`` POST field or GET param is
      checked against settings.ACCESS_CODES; a match marks the session
      verified. A GET submission then falls through to the view; a POST
      submission redirects (PRG) to the same path so the code isn't
      left sitting in a resubmittable POST body.
    - Anything else (no code yet, or a wrong one) renders the prompt
      page instead of the gated view — never a 500, never a redirect
      loop. A wrong code renders with a 403 status; no code yet renders
      with 200, since it isn't an invalid *attempt*. Either way the
      response never hints at whether a submitted code was close to
      correct — it's the same generic prompt either way.
    """

    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if has_valid_session(request):
            return view_func(request, *args, **kwargs)

        submitted = _submitted_code(request)

        if submitted is not None and submitted in _valid_codes():
            request.session[SESSION_KEY] = True
            if request.method == "POST":
                return redirect(request.path)
            return view_func(request, *args, **kwargs)

        was_invalid_attempt = submitted is not None
        status = 403 if was_invalid_attempt else 200
        return render(
            request,
            PROMPT_TEMPLATE,
            {"invalid": was_invalid_attempt},
            status=status,
        )

    return wrapped_view
