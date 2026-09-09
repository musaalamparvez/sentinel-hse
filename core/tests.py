from django.test import TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_returns_ok_status(self):
        response = self.client.get(reverse("health-check"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
