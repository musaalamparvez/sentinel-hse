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
