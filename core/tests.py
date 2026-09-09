from unittest.mock import patch

from django.contrib.admin.sites import site as admin_site
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import path, reverse

from core.access import SESSION_KEY, has_valid_session, require_access_code
from core.models import Assignee, Closure, Report, Site
from core.tokens import report_pk_from_token, report_token


# --- test-only URLconf for the access-code gate tests below (#10) ---
#
# #8 and #11 (the real views this gate protects) don't exist yet, so
# there's no production view to point the decorator at. This dummy view
# and urlpatterns list exist only so AccessCodeGateTests can exercise
# @require_access_code through the real request/response cycle (session
# handling, redirects, CSRF) via the Django test client, without
# inventing a fake production page. It's wired in only when a test
# below overrides ROOT_URLCONF to this module.


def _gate_protected_view(request):
    return HttpResponse("secret dashboard content")


_gate_protected_view = require_access_code(_gate_protected_view)

urlpatterns = [
    path(
        "access-code-test-view/",
        _gate_protected_view,
        name="access-code-test-view",
    ),
]


class HealthCheckTests(TestCase):
    def test_returns_ok_status(self):
        response = self.client.get(reverse("health-check"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class ReportFormViewTests(TestCase):
    def test_loads_without_auth(self):
        response = self.client.get(reverse("report-form"))

        self.assertEqual(response.status_code, 200)

    def test_anonymous_checkbox_present(self):
        response = self.client.get(reverse("report-form"))

        self.assertContains(response, 'id="id_is_anonymous"')
        self.assertContains(response, 'type="checkbox"')

    def test_assignee_filter_endpoint_referenced(self):
        response = self.client.get(reverse("report-form"))

        self.assertContains(response, "/api/sites/")

    def test_lists_all_sites_in_dropdown(self):
        site_a = Site.objects.create(name="Site A")
        site_b = Site.objects.create(name="Site B")

        response = self.client.get(reverse("report-form"))

        self.assertContains(response, site_a.name)
        self.assertContains(response, site_b.name)

    def test_prefills_reporter_name_from_query_param(self):
        response = self.client.get(reverse("report-form"), {"name": "Jane Doe"})

        self.assertContains(response, 'value="Jane Doe"')

    def test_reporter_name_blank_when_not_available(self):
        response = self.client.get(reverse("report-form"))

        self.assertContains(response, 'id="id_reporter_name"')
        self.assertNotContains(response, 'name="reporter_name" value="J')


class ReportSubmissionTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(name="North Yard")
        self.other_site = Site.objects.create(name="South Yard")
        self.assignee = Assignee.objects.create(
            name="Jane Doe", email="jane@example.com"
        )
        self.site.assignees.add(self.assignee)
        self.unlinked_assignee = Assignee.objects.create(
            name="John Doe", email="john@example.com"
        )
        self.other_site.assignees.add(self.unlinked_assignee)

    def _valid_data(self, **overrides):
        data = dict(
            site=str(self.site.pk),
            is_anonymous="",
            reporter_name="Alex Reporter",
            category=Report.Category.SLIP_TRIP_FALL,
            category_other_detail="",
            description="A forklift nearly collided with a pedestrian.",
            location="Warehouse B, aisle 3",
            location_lat="",
            location_lng="",
            assignee=str(self.assignee.pk),
        )
        data.update(overrides)
        return data

    def test_valid_submission_creates_report_and_redirects(self):
        response = self.client.post(reverse("report-form"), self._valid_data())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("report-confirmation"))
        self.assertEqual(Report.objects.count(), 1)

        report = Report.objects.get()
        self.assertEqual(report.status, Report.Status.OPEN)
        self.assertIsNotNone(report.created_at)
        self.assertEqual(report.site, self.site)
        self.assertEqual(report.assignee, self.assignee)
        self.assertEqual(report.description, self._valid_data()["description"])

    def test_confirmation_page_shows_no_report_details(self):
        self.client.post(reverse("report-form"), self._valid_data())

        response = self.client.get(reverse("report-confirmation"), follow=False)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "submitted")
        self.assertNotContains(response, "Warehouse B")
        self.assertNotContains(response, "Alex Reporter")

    def test_valid_submission_with_gps_coordinates_but_no_location_text(self):
        response = self.client.post(
            reverse("report-form"),
            self._valid_data(location="", location_lat="51.5", location_lng="-0.1"),
        )

        self.assertEqual(response.status_code, 302)
        report = Report.objects.get()
        self.assertEqual(report.location, "")
        self.assertEqual(float(report.location_lat), 51.5)
        self.assertEqual(float(report.location_lng), -0.1)

    def test_missing_site_rerenders_form_with_error_and_preserves_values(self):
        response = self.client.post(reverse("report-form"), self._valid_data(site=""))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 0)
        self.assertContains(response, "Please select a site", status_code=400)
        self.assertContains(response, "Alex Reporter", status_code=400)

    def test_missing_category_is_rejected(self):
        response = self.client.post(
            reverse("report-form"), self._valid_data(category="")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 0)
        self.assertContains(response, "Please select a category", status_code=400)

    def test_missing_description_is_rejected(self):
        response = self.client.post(
            reverse("report-form"), self._valid_data(description="   ")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 0)
        self.assertContains(response, "Please enter a description", status_code=400)

    def test_missing_assignee_is_rejected(self):
        response = self.client.post(
            reverse("report-form"), self._valid_data(assignee="")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 0)
        self.assertContains(response, "Please select an assignee", status_code=400)

    def test_category_other_with_blank_detail_is_rejected(self):
        response = self.client.post(
            reverse("report-form"),
            self._valid_data(
                category=Report.Category.OTHER, category_other_detail=""
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 0)
        self.assertContains(
            response, "Please describe the category", status_code=400
        )

    def test_category_other_with_detail_is_accepted(self):
        response = self.client.post(
            reverse("report-form"),
            self._valid_data(
                category=Report.Category.OTHER,
                category_other_detail="Something unusual",
            ),
        )

        self.assertEqual(response.status_code, 302)
        report = Report.objects.get()
        self.assertEqual(report.category_other_detail, "Something unusual")

    def test_non_image_photo_is_rejected(self):
        bad_file = SimpleUploadedFile(
            "notes.txt", b"not an image", content_type="text/plain"
        )
        response = self.client.post(
            reverse("report-form"), self._valid_data(photo=bad_file)
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 0)
        self.assertContains(
            response, "Please choose a JPEG or PNG image", status_code=400
        )

    def test_oversized_photo_is_rejected(self):
        big_file = SimpleUploadedFile(
            "photo.jpg",
            b"x" * (10 * 1024 * 1024 + 1),
            content_type="image/jpeg",
        )
        response = self.client.post(
            reverse("report-form"), self._valid_data(photo=big_file)
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 0)
        self.assertContains(
            response, "Photo must be 10MB or smaller", status_code=400
        )

    def test_valid_photo_is_saved(self):
        photo = SimpleUploadedFile(
            "photo.jpg", b"fake-image-bytes", content_type="image/jpeg"
        )
        response = self.client.post(
            reverse("report-form"), self._valid_data(photo=photo)
        )

        self.assertEqual(response.status_code, 302)
        report = Report.objects.get()
        self.assertTrue(report.photo.name)
        report.photo.delete(save=False)

    def test_anonymous_submission_ignores_tampered_reporter_name(self):
        response = self.client.post(
            reverse("report-form"),
            self._valid_data(is_anonymous="on", reporter_name="Leaked Name"),
        )

        self.assertEqual(response.status_code, 302)
        report = Report.objects.get()
        self.assertTrue(report.is_anonymous)
        self.assertEqual(report.reporter_name, "")

    def test_assignee_not_linked_to_site_is_rejected(self):
        response = self.client.post(
            reverse("report-form"),
            self._valid_data(
                site=str(self.site.pk), assignee=str(self.unlinked_assignee.pk)
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 0)
        self.assertContains(
            response,
            "Please select an assignee for the selected site",
            status_code=400,
        )

    def test_missing_location_and_gps_is_rejected(self):
        response = self.client.post(
            reverse("report-form"),
            self._valid_data(location="", location_lat="", location_lng=""),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 0)
        self.assertContains(
            response,
            "Please enter a location or use your current location",
            status_code=400,
        )

    def test_location_text_without_gps_is_accepted(self):
        response = self.client.post(
            reverse("report-form"),
            self._valid_data(location="Warehouse B", location_lat="", location_lng=""),
        )

        self.assertEqual(response.status_code, 302)
        report = Report.objects.get()
        self.assertEqual(report.location, "Warehouse B")
        self.assertIsNone(report.location_lat)
        self.assertIsNone(report.location_lng)

    def test_valid_submission_emails_the_assignee_exactly_once(self):
        response = self.client.post(reverse("report-form"), self._valid_data())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, [self.assignee.email])

    def test_notification_email_includes_site_category_and_description(self):
        self.client.post(reverse("report-form"), self._valid_data())

        sent = mail.outbox[0]
        self.assertIn(self.site.name, sent.body)
        self.assertIn("Slip/Trip/Fall", sent.body)
        self.assertIn("forklift nearly collided", sent.body)

    def test_invalid_submission_sends_no_email(self):
        response = self.client.post(reverse("report-form"), self._valid_data(site=""))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_send_failure_does_not_block_report_creation_or_confirmation(self):
        with patch("core.emails.send_mail", side_effect=RuntimeError("smtp down")):
            response = self.client.post(reverse("report-form"), self._valid_data())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("report-confirmation"))
        self.assertEqual(Report.objects.count(), 1)

        confirmation = self.client.get(reverse("report-confirmation"))
        self.assertEqual(confirmation.status_code, 200)


class SiteAssigneesEndpointTests(TestCase):
    def test_returns_only_assignees_linked_to_the_site(self):
        site = Site.objects.create(name="North Yard")
        other_site = Site.objects.create(name="South Yard")
        linked = Assignee.objects.create(name="Jane Doe", email="jane@example.com")
        unlinked = Assignee.objects.create(name="John Doe", email="john@example.com")
        site.assignees.add(linked)
        other_site.assignees.add(unlinked)

        response = self.client.get(
            reverse("site-assignees", args=[site.pk])
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["assignees"]), 1)
        self.assertEqual(data["assignees"][0]["name"], "Jane Doe")

    def test_returns_empty_list_for_site_with_zero_assignees(self):
        site = Site.objects.create(name="Empty Site")

        response = self.client.get(
            reverse("site-assignees", args=[site.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"assignees": []})

    def test_returns_404_for_nonexistent_site(self):
        response = self.client.get(reverse("site-assignees", args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_does_not_require_login(self):
        site = Site.objects.create(name="North Yard")

        response = self.client.get(
            reverse("site-assignees", args=[site.pk])
        )

        self.assertNotEqual(response.status_code, 302)


class SendNewReportNotificationTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(name="North Yard")
        self.assignee = Assignee.objects.create(
            name="Jane Doe", email="jane@example.com"
        )
        self.report = Report.objects.create(
            site=self.site,
            assignee=self.assignee,
            category=Report.Category.SLIP_TRIP_FALL,
            description="A forklift nearly collided with a pedestrian.",
            location="Warehouse B, aisle 3",
        )

    def test_sends_to_assignee_with_working_detail_link(self):
        from core.emails import send_new_report_notification

        send_new_report_notification(self.report)

        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, [self.assignee.email])
        # #8 now exists: the link resolves via reverse() to the report
        # detail page, addressed by an unguessable token rather than
        # the raw sequential Report.id.
        expected_path = reverse("report-detail", args=[report_token(self.report)])
        self.assertIn(expected_path, sent.body)
        self.assertNotIn(f"/reports/{self.report.pk}/", sent.body)


class ReportTokenTests(TestCase):
    """core.tokens: the unguessable identifier (#8) used to link to a
    report without exposing the sequential Report.id."""

    def setUp(self):
        self.site = Site.objects.create(name="North Yard")
        self.assignee = Assignee.objects.create(
            name="Jane Doe", email="jane@example.com"
        )
        self.report = Report.objects.create(
            site=self.site,
            assignee=self.assignee,
            category=Report.Category.EQUIPMENT,
            description="A guard rail is missing.",
            location="Warehouse B",
        )

    def test_token_is_not_the_raw_pk(self):
        token = report_token(self.report)

        self.assertNotEqual(token, str(self.report.pk))

    def test_token_round_trips_to_the_correct_pk(self):
        token = report_token(self.report)

        self.assertEqual(report_pk_from_token(token), self.report.pk)

    def test_tampered_token_does_not_resolve(self):
        token = report_token(self.report)
        tampered = token[:-1] + ("x" if token[-1] != "x" else "y")

        self.assertIsNone(report_pk_from_token(tampered))

    def test_garbage_token_does_not_resolve(self):
        self.assertIsNone(report_pk_from_token("not-a-real-token"))

    def test_swapping_the_signed_value_does_not_resolve(self):
        # Signed as pk=1 but claiming to be a different report's pk
        # shouldn't be possible by editing the plaintext part alone.
        token = report_token(self.report)
        value, _, sig = token.rpartition(":")
        forged = f"{self.report.pk + 999}:{sig}"

        self.assertIsNone(report_pk_from_token(forged))


@override_settings(ACCESS_CODES=["letmein"])
class ReportDetailViewTests(TestCase):
    """core.views.report_detail (#8): the assignee-facing report page,
    reached via an unguessable token and gated by the access code from
    #10."""

    def setUp(self):
        self.site = Site.objects.create(name="North Yard")
        self.assignee = Assignee.objects.create(
            name="Jane Doe", email="jane@example.com"
        )
        self.report = Report.objects.create(
            site=self.site,
            assignee=self.assignee,
            category=Report.Category.OTHER,
            category_other_detail="Loose scaffolding plank",
            description="A scaffolding plank looked loose on level 3.",
            reporter_name="Sam Reporter",
            is_anonymous=False,
            location="Warehouse B, aisle 3",
            status=Report.Status.OPEN,
        )
        self.url = reverse("report-detail", args=[report_token(self.report)])

    # --- reachability / gating ---

    def test_unauthenticated_request_shows_access_prompt_not_report(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Access code required")
        self.assertNotContains(response, self.report.description)

    def test_reachable_with_valid_access_code(self):
        response = self.client.get(self.url, {"code": "letmein"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.report.description)

    def test_access_code_is_remembered_for_later_requests_to_the_page(self):
        self.client.get(self.url, {"code": "letmein"})

        second = self.client.get(self.url)

        self.assertContains(second, self.report.description)

    def test_invalid_token_is_a_404_once_past_the_gate(self):
        bogus_url = reverse("report-detail", args=["not-a-real-token"])

        response = self.client.get(bogus_url, {"code": "letmein"})

        self.assertEqual(response.status_code, 404)

    # --- fields shown ---

    def test_shows_report_fields_relevant_to_resolving_it(self):
        response = self.client.get(self.url, {"code": "letmein"})

        self.assertContains(response, "North Yard")
        self.assertContains(response, "Loose scaffolding plank")
        self.assertContains(response, "A scaffolding plank looked loose on level 3.")
        self.assertContains(response, "Warehouse B, aisle 3")
        self.assertContains(response, "Open")

    def test_shows_reporter_name_when_not_anonymous(self):
        response = self.client.get(self.url, {"code": "letmein"})

        self.assertContains(response, "Sam Reporter")

    def test_hides_reporter_name_when_anonymous_even_if_stored(self):
        # Simulates a future task populating reporter_name despite
        # is_anonymous=True; the page must never leak it regardless.
        anon_report = Report.objects.create(
            site=self.site,
            assignee=self.assignee,
            category=Report.Category.OTHER,
            description="Anonymous near-miss report.",
            reporter_name="Should Never Appear",
            is_anonymous=True,
            location="Warehouse C",
        )
        url = reverse("report-detail", args=[report_token(anon_report)])

        response = self.client.get(url, {"code": "letmein"})

        self.assertNotContains(response, "Should Never Appear")

    # --- status transitions ---

    def test_open_to_in_progress_is_allowed(self):
        self.client.get(self.url, {"code": "letmein"})
        response = self.client.post(self.url, {"status": "in_progress"})

        self.assertEqual(response.status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.IN_PROGRESS)

    def test_in_progress_back_to_open_is_allowed(self):
        self.report.status = Report.Status.IN_PROGRESS
        self.report.save(update_fields=["status"])
        self.client.get(self.url, {"code": "letmein"})

        response = self.client.post(self.url, {"status": "open"})

        self.assertEqual(response.status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.OPEN)

    def test_tampering_to_closed_is_rejected_server_side(self):
        self.client.get(self.url, {"code": "letmein"})
        response = self.client.post(self.url, {"status": "closed"})

        self.assertEqual(response.status_code, 400)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.OPEN)

    def test_bogus_status_value_is_rejected(self):
        self.client.get(self.url, {"code": "letmein"})
        response = self.client.post(self.url, {"status": "not-a-status"})

        self.assertEqual(response.status_code, 400)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.OPEN)

    def test_status_update_without_access_code_is_gated_and_ignored(self):
        response = self.client.post(self.url, {"status": "in_progress"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Access code required")
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.OPEN)


class SiteModelTests(TestCase):
    def test_str_returns_name(self):
        site = Site.objects.create(name="North Yard")

        self.assertEqual(str(site), "North Yard")

    def test_can_exist_with_zero_assignees(self):
        site = Site.objects.create(name="Empty Site")

        self.assertEqual(site.assignees.count(), 0)


class AssigneeModelTests(TestCase):
    def test_str_returns_name_and_email(self):
        assignee = Assignee.objects.create(name="Jane Doe", email="jane@example.com")

        self.assertEqual(str(assignee), "Jane Doe <jane@example.com>")

    def test_can_exist_with_zero_sites(self):
        assignee = Assignee.objects.create(name="Jane Doe", email="jane@example.com")

        self.assertEqual(assignee.sites.count(), 0)

    def test_can_belong_to_multiple_sites(self):
        site_a = Site.objects.create(name="Site A")
        site_b = Site.objects.create(name="Site B")
        assignee = Assignee.objects.create(name="Jane Doe", email="jane@example.com")

        assignee.sites.add(site_a, site_b)

        self.assertEqual(assignee.sites.count(), 2)
        self.assertIn(assignee, site_a.assignees.all())
        self.assertIn(assignee, site_b.assignees.all())

    def test_site_can_have_multiple_assignees(self):
        site = Site.objects.create(name="Site A")
        assignee_a = Assignee.objects.create(name="Jane Doe", email="jane@example.com")
        assignee_b = Assignee.objects.create(name="John Doe", email="john@example.com")

        site.assignees.add(assignee_a, assignee_b)

        self.assertEqual(site.assignees.count(), 2)


def _make_photo(name="photo.jpg"):
    return SimpleUploadedFile(name, b"fake-image-bytes", content_type="image/jpeg")


class ReportModelTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(name="North Yard")
        self.assignee = Assignee.objects.create(
            name="Jane Doe", email="jane@example.com"
        )

    def _base_kwargs(self, **overrides):
        kwargs = dict(
            site=self.site,
            assignee=self.assignee,
            category=Report.Category.SLIP_TRIP_FALL,
            description="A forklift nearly collided with a pedestrian.",
            location="Warehouse B, aisle 3",
        )
        kwargs.update(overrides)
        return kwargs

    def test_status_defaults_to_open_on_creation(self):
        report = Report.objects.create(**self._base_kwargs())

        self.assertEqual(report.status, Report.Status.OPEN)

    def test_non_other_category_allows_blank_category_other_detail(self):
        report = Report.objects.create(
            **self._base_kwargs(
                category=Report.Category.EQUIPMENT, category_other_detail=""
            )
        )
        report.full_clean(exclude=["photo"])

        self.assertEqual(report.category_other_detail, "")

    def test_anonymous_report_allows_blank_reporter_name(self):
        report = Report.objects.create(
            **self._base_kwargs(is_anonymous=True, reporter_name="")
        )
        report.full_clean(exclude=["photo"])

        self.assertTrue(report.is_anonymous)
        self.assertEqual(report.reporter_name, "")

    def test_non_anonymous_report_allows_blank_reporter_name(self):
        report = Report.objects.create(
            **self._base_kwargs(is_anonymous=False, reporter_name="")
        )
        report.full_clean(exclude=["photo"])

        self.assertFalse(report.is_anonymous)
        self.assertEqual(report.reporter_name, "")

    def test_rejects_invalid_category(self):
        report = Report(**self._base_kwargs(category="not-a-real-category"))

        with self.assertRaises(ValidationError):
            report.full_clean(exclude=["photo"])

    def test_location_lat_and_lng_can_each_be_independently_null(self):
        report = Report.objects.create(
            **self._base_kwargs(location_lat=None, location_lng=51.5)
        )

        self.assertIsNone(report.location_lat)
        self.assertEqual(report.location_lng, 51.5)

    def test_photo_is_optional(self):
        report = Report.objects.create(**self._base_kwargs())

        self.assertFalse(report.photo)

    def test_can_be_created_with_a_photo(self):
        report = Report.objects.create(**self._base_kwargs(photo=_make_photo()))

        self.assertTrue(report.photo.name)
        report.photo.delete(save=False)


class ClosureModelTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(name="North Yard")
        self.assignee = Assignee.objects.create(
            name="Jane Doe", email="jane@example.com"
        )
        self.report = Report.objects.create(
            site=self.site,
            assignee=self.assignee,
            category=Report.Category.SLIP_TRIP_FALL,
            description="A forklift nearly collided with a pedestrian.",
            location="Warehouse B, aisle 3",
        )

    def test_can_be_created_with_note_and_photo(self):
        closure = Closure.objects.create(
            report=self.report,
            note="Guard rail installed and area re-marked.",
            photo=_make_photo(),
            closed_by=self.assignee,
        )
        closure.full_clean()

        self.assertEqual(closure.report, self.report)
        closure.photo.delete(save=False)

    def test_creating_closure_requires_note_and_photo(self):
        # Missing both.
        closure = Closure(
            report=self.report,
            note="",
            photo="",
            closed_by=self.assignee,
        )
        with self.assertRaises(ValidationError):
            closure.full_clean()

        # Note present, photo missing.
        closure = Closure(
            report=self.report,
            note="Guard rail installed.",
            photo="",
            closed_by=self.assignee,
        )
        with self.assertRaises(ValidationError):
            closure.full_clean()

        # Photo present, note missing.
        closure = Closure(
            report=self.report,
            note="",
            photo=_make_photo(),
            closed_by=self.assignee,
        )
        with self.assertRaises(ValidationError):
            closure.full_clean()

    def test_report_can_only_have_one_closure(self):
        Closure.objects.create(
            report=self.report,
            note="Guard rail installed.",
            photo=_make_photo(),
            closed_by=self.assignee,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Closure.objects.create(
                    report=self.report,
                    note="Second closure attempt.",
                    photo=_make_photo(),
                    closed_by=self.assignee,
                )

    def test_deleting_report_with_closure_is_protected(self):
        Closure.objects.create(
            report=self.report,
            note="Guard rail installed.",
            photo=_make_photo(),
            closed_by=self.assignee,
        )

        with self.assertRaises(ProtectedError):
            self.report.delete()


class AdminRegistrationTests(TestCase):
    def test_site_and_assignee_are_registered(self):
        self.assertIn(Site, admin_site._registry)
        self.assertIn(Assignee, admin_site._registry)

    def test_assignee_admin_uses_filter_horizontal_for_sites(self):
        assignee_admin = admin_site._registry[Assignee]

        self.assertIn("sites", assignee_admin.filter_horizontal)


class AdminSiteViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password123"
        )
        self.client.force_login(self.admin_user)

    def test_index_lists_site_and_assignee_under_core_app(self):
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sites")
        self.assertContains(response, "Assignees")

    def test_site_changelist_shows_name_and_linked_assignees_columns(self):
        Site.objects.create(name="North Yard")

        response = self.client.get(reverse("admin:core_site_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Name")
        self.assertContains(response, "Linked Assignees")

    def test_site_changelist_shows_dash_when_no_assignees(self):
        Site.objects.create(name="Empty Site")

        response = self.client.get(reverse("admin:core_site_changelist"))

        self.assertContains(response, "—")

    def test_site_changelist_shows_comma_separated_assignee_names(self):
        site = Site.objects.create(name="North Yard")
        assignee_a = Assignee.objects.create(name="Jane Doe", email="jane@example.com")
        assignee_b = Assignee.objects.create(name="John Doe", email="john@example.com")
        site.assignees.add(assignee_a, assignee_b)

        response = self.client.get(reverse("admin:core_site_changelist"))

        self.assertContains(response, "Jane Doe, John Doe")

    def test_assignee_changelist_shows_name_email_and_linked_sites_columns(self):
        Assignee.objects.create(name="Jane Doe", email="jane@example.com")

        response = self.client.get(reverse("admin:core_assignee_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Name")
        self.assertContains(response, "Email")
        self.assertContains(response, "Linked Sites")

    def test_assignee_changelist_shows_dash_when_no_sites(self):
        Assignee.objects.create(name="Jane Doe", email="jane@example.com")

        response = self.client.get(reverse("admin:core_assignee_changelist"))

        self.assertContains(response, "—")

    def test_assignee_changelist_shows_comma_separated_site_names(self):
        assignee = Assignee.objects.create(name="Jane Doe", email="jane@example.com")
        site_a = Site.objects.create(name="Site A")
        site_b = Site.objects.create(name="Site B")
        assignee.sites.add(site_a, site_b)

        response = self.client.get(reverse("admin:core_assignee_changelist"))

        self.assertContains(response, "Site A, Site B")

    def test_assignee_add_form_uses_filter_horizontal_widget_for_sites(self):
        response = self.client.get(reverse("admin:core_assignee_add"))

        self.assertEqual(response.status_code, 200)
        # filter_horizontal renders the sites <select> with the
        # SelectFilter2 "selectfilter" class (horizontal, not stacked).
        self.assertContains(response, 'class="selectfilter"')
        self.assertContains(response, "SelectFilter2.js")

    def test_saving_assignee_with_zero_sites_persists(self):
        response = self.client.post(
            reverse("admin:core_assignee_add"),
            data={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "sites": [],
            },
        )

        self.assertEqual(response.status_code, 302)
        assignee = Assignee.objects.get(name="Jane Doe")
        self.assertEqual(assignee.sites.count(), 0)

    def test_saving_assignee_with_one_site_persists(self):
        site = Site.objects.create(name="Site A")

        response = self.client.post(
            reverse("admin:core_assignee_add"),
            data={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "sites": [site.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        assignee = Assignee.objects.get(name="Jane Doe")
        self.assertEqual(list(assignee.sites.all()), [site])

    def test_saving_assignee_with_multiple_sites_persists(self):
        site_a = Site.objects.create(name="Site A")
        site_b = Site.objects.create(name="Site B")

        response = self.client.post(
            reverse("admin:core_assignee_add"),
            data={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "sites": [site_a.pk, site_b.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        assignee = Assignee.objects.get(name="Jane Doe")
        self.assertEqual(assignee.sites.count(), 2)
        self.assertIn(site_a, assignee.sites.all())
        self.assertIn(site_b, assignee.sites.all())

    def test_editing_assignee_can_change_site_links(self):
        assignee = Assignee.objects.create(name="Jane Doe", email="jane@example.com")
        site_a = Site.objects.create(name="Site A")
        site_b = Site.objects.create(name="Site B")
        assignee.sites.add(site_a)

        response = self.client.post(
            reverse("admin:core_assignee_change", args=[assignee.pk]),
            data={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "sites": [site_b.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        assignee.refresh_from_db()
        self.assertEqual(list(assignee.sites.all()), [site_b])

    def test_saving_site_with_zero_assignees_persists(self):
        response = self.client.post(
            reverse("admin:core_site_add"),
            data={"name": "New Site"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Site.objects.filter(name="New Site").exists())


@override_settings(ROOT_URLCONF=__name__, ACCESS_CODES=["letmein"])
class AccessCodeGateTests(TestCase):
    """Exercises @require_access_code (#10) against the dummy view/
    urlpatterns defined above, via the real Django test client."""

    url = "access-code-test-view"

    def test_missing_code_shows_prompt_not_500(self):
        response = self.client.get(reverse(self.url))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Access code required")
        self.assertNotContains(response, "secret dashboard content")

    def test_missing_code_prompt_is_not_flagged_as_an_invalid_attempt(self):
        response = self.client.get(reverse(self.url))

        self.assertNotContains(response, "isn&#x27;t valid")

    def test_valid_code_via_url_param_grants_access(self):
        response = self.client.get(reverse(self.url), {"code": "letmein"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "secret dashboard content")

    def test_valid_code_via_post_form_field_redirects_then_grants_access(self):
        response = self.client.post(reverse(self.url), {"code": "letmein"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse(self.url))

        followed = self.client.get(reverse(self.url))
        self.assertContains(followed, "secret dashboard content")

    def test_valid_code_is_remembered_for_the_session_no_reprompt(self):
        self.client.post(reverse(self.url), {"code": "letmein"})

        # Two more requests, no code attached either time.
        first = self.client.get(reverse(self.url))
        second = self.client.get(reverse(self.url))

        self.assertContains(first, "secret dashboard content")
        self.assertContains(second, "secret dashboard content")

    def test_valid_code_sets_the_session_flag(self):
        self.client.post(reverse(self.url), {"code": "letmein"})

        self.assertTrue(self.client.session.get(SESSION_KEY))

    def test_invalid_code_shows_prompt_not_500_or_hardcoded_view(self):
        response = self.client.post(reverse(self.url), {"code": "wrong-code"})

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Access code required", status_code=403)
        self.assertNotContains(
            response, "secret dashboard content", status_code=403
        )

    def test_invalid_code_does_not_leak_the_valid_code(self):
        response = self.client.post(reverse(self.url), {"code": "wrong-code"})

        self.assertNotContains(response, "letmein", status_code=403)

    def test_invalid_code_does_not_grant_a_session(self):
        self.client.post(reverse(self.url), {"code": "wrong-code"})

        self.assertFalse(self.client.session.get(SESSION_KEY))

    def test_repeated_missing_code_requests_do_not_loop_or_error(self):
        first = self.client.get(reverse(self.url))
        second = self.client.get(reverse(self.url))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

    @override_settings(ACCESS_CODES=[])
    def test_no_configured_codes_denies_by_default_rather_than_500(self):
        response = self.client.post(reverse(self.url), {"code": "letmein"})

        self.assertEqual(response.status_code, 403)
        self.assertNotContains(
            response, "secret dashboard content", status_code=403
        )

    def test_has_valid_session_reflects_session_state_directly(self):
        request = self.client.get(reverse(self.url)).wsgi_request
        self.assertFalse(has_valid_session(request))

        self.client.post(reverse(self.url), {"code": "letmein"})
        request = self.client.get(reverse(self.url)).wsgi_request
        self.assertTrue(has_valid_session(request))
