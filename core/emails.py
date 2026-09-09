"""Email notifications for core app events.

Kept in one place (rather than split across views/signals) per #7's
constraint to hook into the report save path from a single spot in core.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)

DESCRIPTION_SNIPPET_LENGTH = 200


def _report_detail_path(report):
    """Best-effort link to the report's detail page.

    The report detail page (#8) doesn't exist yet, so there's no real
    URL to link to. Try the URL name it's expected to register
    ("report-detail") so this starts resolving correctly automatically
    once #8 adds it; until then, fall back to a plain guessed path.
    """
    try:
        return reverse("report-detail", args=[report.pk])
    except NoReverseMatch:
        return f"/reports/{report.pk}/"


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
