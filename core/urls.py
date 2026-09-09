from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health_check, name="health-check"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("report/", views.report_form, name="report-form"),
    path(
        "report/thanks/",
        views.report_confirmation,
        name="report-confirmation",
    ),
    path(
        "api/sites/<int:site_id>/assignees/",
        views.site_assignees,
        name="site-assignees",
    ),
    path(
        "reports/<str:token>/",
        views.report_detail,
        name="report-detail",
    ),
    path(
        "reports/<str:token>/close/",
        views.report_close,
        name="report-close",
    ),
]
