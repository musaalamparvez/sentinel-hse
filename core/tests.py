from django.contrib.admin.sites import site as admin_site
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from core.models import Assignee, Closure, Report, Site


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
            category=Report.Category.NEAR_MISS,
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
                category=Report.Category.EQUIPMENT_FAILURE, category_other_detail=""
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
            category=Report.Category.NEAR_MISS,
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
