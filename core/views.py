from django.core.files.uploadedfile import UploadedFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.models import Assignee, Report, Site

MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_PHOTO_CONTENT_TYPES = {"image/jpeg", "image/png"}


def health_check(request):
    return JsonResponse({"status": "ok"})


def _validate_report_submission(request):
    """Validate the report form POST data.

    Returns (cleaned_data, errors) where errors is a dict of
    field_name -> list of error strings. cleaned_data holds the values
    to use if there are no errors for that field (already coerced/blanked
    where relevant, e.g. reporter_name for anonymous submissions).
    """
    data = request.POST
    files = request.FILES

    errors = {}
    cleaned = {}

    # --- site ---
    site = None
    site_id = data.get("site", "").strip()
    if not site_id:
        errors.setdefault("site", []).append("Please select a site.")
    else:
        try:
            site = Site.objects.get(pk=site_id)
        except (Site.DoesNotExist, ValueError, TypeError):
            errors.setdefault("site", []).append("Please select a valid site.")
    cleaned["site"] = site

    # --- is_anonymous / reporter_name ---
    is_anonymous = data.get("is_anonymous") in ("on", "true", "True", "1")
    cleaned["is_anonymous"] = is_anonymous
    if is_anonymous:
        # Ignore/blank any reporter_name that arrives, even if a client
        # bypassed the disabled field on the form.
        cleaned["reporter_name"] = ""
    else:
        cleaned["reporter_name"] = data.get("reporter_name", "").strip()

    # --- category ---
    category = data.get("category", "").strip()
    if not category:
        errors.setdefault("category", []).append("Please select a category.")
    elif category not in Report.Category.values:
        errors.setdefault("category", []).append("Please select a valid category.")
    cleaned["category"] = category

    category_other_detail = data.get("category_other_detail", "").strip()
    if category == Report.Category.OTHER and not category_other_detail:
        errors.setdefault("category_other_detail", []).append(
            "Please describe the category."
        )
    cleaned["category_other_detail"] = category_other_detail

    # --- description ---
    description = data.get("description", "").strip()
    if not description:
        errors.setdefault("description", []).append("Please enter a description.")
    cleaned["description"] = description

    # --- photo ---
    photo = files.get("photo")
    if photo is not None:
        if not isinstance(photo, UploadedFile) or (
            photo.content_type not in ALLOWED_PHOTO_CONTENT_TYPES
        ):
            errors.setdefault("photo", []).append(
                "Please choose a JPEG or PNG image."
            )
        elif photo.size > MAX_PHOTO_BYTES:
            errors.setdefault("photo", []).append("Photo must be 10MB or smaller.")
    cleaned["photo"] = photo if "photo" not in errors else None

    # --- location / location_lat / location_lng ---
    location = data.get("location", "").strip()
    location_lat = data.get("location_lat", "").strip()
    location_lng = data.get("location_lng", "").strip()

    parsed_lat = None
    parsed_lng = None
    if location_lat and location_lng:
        try:
            parsed_lat = float(location_lat)
            parsed_lng = float(location_lng)
        except ValueError:
            parsed_lat = None
            parsed_lng = None

    if not location and parsed_lat is None:
        errors.setdefault("location", []).append(
            "Please enter a location or use your current location."
        )

    cleaned["location"] = location
    cleaned["location_lat"] = parsed_lat
    cleaned["location_lng"] = parsed_lng

    # --- assignee (validated against site) ---
    assignee = None
    assignee_id = data.get("assignee", "").strip()
    if not assignee_id:
        errors.setdefault("assignee", []).append("Please select an assignee.")
    else:
        try:
            assignee = Assignee.objects.get(pk=assignee_id)
        except (Assignee.DoesNotExist, ValueError, TypeError):
            errors.setdefault("assignee", []).append("Please select a valid assignee.")
        else:
            if site is not None and not assignee.sites.filter(pk=site.pk).exists():
                errors.setdefault("assignee", []).append(
                    "Please select an assignee for the selected site."
                )
                assignee = None
    cleaned["assignee"] = assignee

    return cleaned, errors


def report_form(request):
    """Render the public, no-login near-miss report form, and handle
    its submission.

    GET renders a blank (or pre-filled) form. POST validates and saves
    a Report, then redirects (PRG) to a confirmation page. On validation
    failure, POST re-renders the form with the submitted values and
    per-field errors, without saving anything.
    """
    sites = Site.objects.order_by("name")

    if request.method == "POST":
        cleaned, errors = _validate_report_submission(request)

        if not errors:
            Report.objects.create(
                site=cleaned["site"],
                assignee=cleaned["assignee"],
                category=cleaned["category"],
                category_other_detail=cleaned["category_other_detail"],
                description=cleaned["description"],
                reporter_name=cleaned["reporter_name"],
                is_anonymous=cleaned["is_anonymous"],
                photo=cleaned["photo"],
                location=cleaned["location"],
                location_lat=cleaned["location_lat"],
                location_lng=cleaned["location_lng"],
                status=Report.Status.OPEN,
            )
            return redirect("report-confirmation")

        context = {
            "sites": sites,
            "reporter_name": request.POST.get("reporter_name", ""),
            "categories": Report.Category.choices,
            "other_category_value": Report.Category.OTHER,
            "errors": errors,
            "submitted": request.POST,
        }
        return render(request, "core/report_form.html", context, status=400)

    reporter_name = request.GET.get("name") or request.session.get("reporter_name") or ""

    context = {
        "sites": sites,
        "reporter_name": reporter_name,
        "categories": Report.Category.choices,
        "other_category_value": Report.Category.OTHER,
    }
    return render(request, "core/report_form.html", context)


def report_confirmation(request):
    """Plain "thanks" page shown after a successful report submission.

    Deliberately shows no report details, so it can't be used to
    deanonymize an anonymous submission (e.g. via a shared/guessed URL).
    """
    return render(request, "core/report_confirmation.html")


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
