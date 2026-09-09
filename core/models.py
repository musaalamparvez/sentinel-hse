from django.db import models


class Site(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Assignee(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField()
    sites = models.ManyToManyField(Site, related_name="assignees", blank=True)

    def __str__(self):
        return f"{self.name} <{self.email}>"


class Report(models.Model):
    class Category(models.TextChoices):
        UNSAFE_CONDITION = "unsafe_condition", "Unsafe Condition"
        UNSAFE_ACT = "unsafe_act", "Unsafe Act"
        NEAR_MISS = "near_miss", "Near Miss"
        EQUIPMENT_FAILURE = "equipment_failure", "Equipment Failure"
        ENVIRONMENTAL = "environmental", "Environmental"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        CLOSED = "closed", "Closed"

    # Reports carry HSE audit history for a site, so a site (or its assignee)
    # cannot be deleted out from under the reports that reference it.
    site = models.ForeignKey(Site, related_name="reports", on_delete=models.PROTECT)
    assignee = models.ForeignKey(
        Assignee, related_name="reports", on_delete=models.PROTECT
    )

    category = models.CharField(max_length=32, choices=Category.choices)
    category_other_detail = models.CharField(max_length=255, blank=True, default="")

    description = models.TextField()

    reporter_name = models.CharField(max_length=255, null=True, blank=True)
    is_anonymous = models.BooleanField(default=False)

    photo = models.FileField(upload_to="reports/", blank=True, null=True)

    location = models.CharField(max_length=255)
    location_lat = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    location_lng = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN
    )

    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Report #{self.pk} ({self.get_category_display()})"


class Closure(models.Model):
    # A Report's audit trail (its Closure) must survive even if the report
    # itself is later removed, so deletion is blocked rather than cascaded.
    report = models.OneToOneField(
        Report, related_name="closure", on_delete=models.PROTECT
    )
    note = models.TextField()
    photo = models.FileField(upload_to="closures/")
    closed_by = models.ForeignKey(
        Assignee, related_name="closures", on_delete=models.PROTECT
    )
    closed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Closure for Report #{self.report_id}"
