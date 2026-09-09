from django.contrib import admin

from core.models import Assignee, Site


def _joined_names_or_dash(related_manager):
    names = [obj.name for obj in related_manager.all()]
    return ", ".join(names) if names else "—"


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "linked_assignees")

    @admin.display(description="Linked Assignees")
    def linked_assignees(self, obj):
        return _joined_names_or_dash(obj.assignees)


@admin.register(Assignee)
class AssigneeAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "linked_sites")
    filter_horizontal = ("sites",)

    @admin.display(description="Linked Sites")
    def linked_sites(self, obj):
        return _joined_names_or_dash(obj.sites)
