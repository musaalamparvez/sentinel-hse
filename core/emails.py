"""Email notifications for core app events.

Kept in one place (rather than split across views/signals) per #7's
constraint to hook into the report save path from a single spot in core.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import NoReverseMatch, reverse

from core.tokens import report_token

logger = logging.getLogger(__name__)

DESCRIPTION_SNIPPET_LENGTH = 200


def _report_detail_path(report):
    """Link to the report's detail page (#8).

    Addressed by an unguessable signed token (core.tokens), not the raw
    sequential Report.id, per #8's acceptance criteria. Reverse still
    isn't allowed to blow up report creation if URL config is ever
    broken, so a NoReverseMatch falls back to a guessed (token-based)
    path instead of raising — send_new_report_notification's own
    try/except handles any other failure.
    """
    token = report_token(report)
    try:
        return reverse("report-detail", args=[token])
    except NoReverseMatch:
        return f"/reports/{token}/"


def send_new_report_notification(report, request=None):
    """Email report.assignee about a newly created report (#7).

    Best-effort: any send failure is logged and swallowed here so it
    never rolls back the already-created Report and never surfaces a
    raw error to the reporter.
    """
    detail_path = _report_detail_path(report)
    detail_url = (
        request.build_absolute_uri(detail_path)
        if request is not None
        else detail_path
    )

    snippet = report.description.strip()
    if len(snippet) > DESCRIPTION_SNIPPET_LENGTH:
        snippet = snippet[:DESCRIPTION_SNIPPET_LENGTH].rstrip() + "..."

    subject = f"New HSE report at {report.site.name}"
    message = (
        f"A new report has been submitted at {report.site.name}.\n\n"
        f"Category: {report.get_category_display()}\n"
        f"Description: {snippet}\n\n"
        f"View the report: {detail_url}\n"
    )

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [report.assignee.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception(
            "Failed to send new-report notification email for report %s",
            report.pk,
        )
