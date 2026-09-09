from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from core.models import Assignee, Report, Site


def health_check(request):
    return JsonResponse({"status": "ok"})


def report_form(request):
    """Render the public, no-login near-miss report form (GET only).

    Saving the report is handled elsewhere (#6) — this view only renders
    the form and its initial data.
    """
    sites = Site.objects.order_by("name")
    reporter_name = request.GET.get("name") or request.session.get("reporter_name") or ""

    context = {
        "sites": sites,
        "reporter_name": reporter_name,
        "categories": Report.Category.choices,
        "other_category_value": Report.Category.OTHER,
    }
    return render(request, "core/report_form.html", context)


def site_assignees(request, site_id):
    """Return the Assignees linked to a Site, as JSON. No login required.

    Used by the report form's client-side JS to re-populate the assignee
    dropdown when the selected Site changes.
    """
    site = get_object_or_404(Site, pk=site_id)
    assignees = Assignee.objects.filter(sites=site).order_by("name").values(
        "id", "name"
    )
    return JsonResponse({"assignees": list(assignees)})
