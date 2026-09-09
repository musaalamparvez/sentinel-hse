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
