from django.test import TestCase
from django.urls import reverse

from core.models import Assignee, Site


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
