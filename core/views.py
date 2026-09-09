from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core import emails
from core.access import require_access_code
from core.models import Assignee, Closure, Report, Site
from core.tokens import report_pk_from_token, report_token

# Status values an assignee is allowed to set from the report detail
# page (#8). Closed is deliberately excluded — only the closure flow
# (#9) may set status=Closed.
ASSIGNEE_SETTABLE_STATUSES = {Report.Status.OPEN, Report.Status.IN_PROGRESS}

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
            report = Report.objects.create(
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
            emails.send_new_report_notification(report, request)
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


@require_access_code
def report_detail(request, token):
    """Assignee-facing report detail page (#8).

    Reached via an unguessable signed token (core.tokens), not the raw
    Report.id, and gated by the same access-code check as the
    dashboard (#10) via @require_access_code. Lets the assignee move
    status between Open and In Progress in either direction; tampering
    with the posted status to anything else (in particular "closed",
    which only #9's closure flow may set) is rejected server-side and
    never changes the stored status.
    """
    pk = report_pk_from_token(token)
    if pk is None:
        raise Http404("Invalid or tampered report link.")
    report = get_object_or_404(Report, pk=pk)

    status_error = False
    if request.method == "POST":
        submitted_status = request.POST.get("status", "")
        if submitted_status not in ASSIGNEE_SETTABLE_STATUSES:
            status_error = True
        else:
            if report.status != submitted_status:
                report.status = submitted_status
                report.save(update_fields=["status"])
            return redirect("report-detail", token=token)

    context = {
        "report": report,
        "status_error": status_error,
        "token": token,
    }
    return render(
        request,
        "core/report_detail.html",
        context,
        status=400 if status_error else 200,
    )


@require_access_code
def report_close(request, token):
    """Closure form for a Report (#9), reached from the report detail
    page (#8) via the same unguessable token and access-code gate.

    Requires a note and a photo (matching the validation already
    enforced at the model level, per ClosureModelTests) before a
    Closure can be created. On success, creates the Closure, sets
    Report.status = Closed and Report.closed_at = now(), then redirects
    back to the detail page. A Report that already has a Closure can't
    be closed again — that's rejected with a clear message rather than
    letting the one-to-one IntegrityError bubble up.
    """
    pk = report_pk_from_token(token)
    if pk is None:
        raise Http404("Invalid or tampered report link.")
    report = get_object_or_404(Report, pk=pk)

    already_closed = hasattr(report, "closure")

    errors = {}
    submitted = None

    if request.method == "POST" and not already_closed:
        submitted = request.POST
        note = submitted.get("note", "").strip()
        photo = request.FILES.get("photo")

        if not note:
            errors.setdefault("note", []).append("A closure note is required.")
        if not photo:
            errors.setdefault("photo", []).append("A closure photo is required.")

        if not errors:
            try:
                with transaction.atomic():
                    Closure.objects.create(
                        report=report,
                        note=note,
                        photo=photo,
                        closed_by=report.assignee,
                    )
                    report.status = Report.Status.CLOSED
                    report.closed_at = timezone.now()
                    report.save(update_fields=["status", "closed_at"])
            except IntegrityError:
                # Two concurrent submissions raced past the already_closed
                # check above; the DB's one-to-one constraint is the
                # backstop, but the caller still gets a clear message
                # rather than a raw 500.
                already_closed = True
            else:
                return redirect("report-detail", token=token)

    context = {
        "report": report,
        "already_closed": already_closed,
        "errors": errors,
        "submitted": submitted,
        "token": token,
    }
    return render(
        request,
        "core/report_close.html",
        context,
        status=409 if already_closed else (400 if errors else 200),
    )


@require_access_code
def dashboard(request):
    """Supervisor/safety officer dashboard (#11): every Report, newest
    first, filterable by Site and Status via query-string params.

    Gated by the same access-code check as the report detail page
    (#8/#10). Filters are applied via a plain query-string GET reload
    (``?site=<id>&status=<value>``) — no JS required for MVP. Either
    filter may be applied alone or together; an empty ``site``/``status``
    (or an absent one) means "don't filter on this dimension", so
    clearing filters is just a link back to the bare dashboard URL.
    """
    reports = Report.objects.select_related("site").order_by("-created_at")

    site_id = request.GET.get("site", "").strip()
    selected_site = None
    if site_id:
        try:
            selected_site = Site.objects.get(pk=site_id)
        except (Site.DoesNotExist, ValueError, TypeError):
            selected_site = None
        else:
            reports = reports.filter(site=selected_site)

    status = request.GET.get("status", "").strip()
    if status and status in Report.Status.values:
        reports = reports.filter(status=status)
    else:
        status = ""

    rows = [(report, report_token(report)) for report in reports]

    context = {
        "rows": rows,
        "sites": Site.objects.order_by("name"),
        "statuses": Report.Status.choices,
        "selected_site_id": str(selected_site.pk) if selected_site else "",
        "selected_status": status,
        "has_filters": bool(selected_site or status),
    }
    return render(request, "core/dashboard.html", context)


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
