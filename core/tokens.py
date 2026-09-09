"""Unguessable identifiers for linking directly to a Report (#8).

The assignee report detail page must be addressed by something other
than the sequential integer ``Report.id`` — as defense-in-depth
alongside the access-code gate (#10), not a substitute for it. Rather
than add a UUID column (and a migration) to the already-closed-out
Report model (#3), this signs the pk with Django's ``signing`` module
(HMAC over SECRET_KEY): the resulting token is unguessable without the
secret key, and requires no schema change.

The token never expires (a ``Signer``, not a ``TimestampSigner``) —
there's no requirement that report-detail links go stale, and doing so
would just break old emails for no benefit.
"""

from django.core import signing

REPORT_DETAIL_SALT = "core.tokens.report-detail"


def _signer():
    return signing.Signer(salt=REPORT_DETAIL_SALT)


def report_token(report):
    """Return an unguessable token identifying ``report``, suitable for
    use in a URL."""
    return _signer().sign(str(report.pk))


def report_pk_from_token(token):
    """Return the Report pk encoded in ``token``, or None if the token
    is missing, malformed, or has been tampered with."""
    try:
        return int(_signer().unsign(token))
    except (signing.BadSignature, ValueError, TypeError):
        return None
