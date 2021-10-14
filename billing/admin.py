from datetime import timedelta
from django.utils import timezone
from django.contrib import admin

from . import models


class CustomerAdminInline(admin.StackedInline):
    model = models.Customer
    verbose_name_plural = "Customer Profile"
    can_delete = (
        False  # You can't delete a Customer in the admin without deleting the User.
    )
    readonly_fields = ("state",)


@admin.register(models.Limit)
class LimitAdmin(admin.ModelAdmin):
    list_display = ("name", "default")


class PlanLimitInline(admin.TabularInline):
    model = models.PlanLimit
    extra = 0


@admin.register(models.Plan)
class PlanAdmin(admin.ModelAdmin):
    inlines = [PlanLimitInline]


@admin.register(models.StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_select_related = ["user"]
    list_display = ["__str__", "payload_type", "user", "status", "received_at"]


class StripeEventAdminInline(admin.TabularInline):
    model = models.StripeEvent
    fields = ("type", "received_at", "event_id", "status")
    readonly_fields = ("type", "received_at", "event_id", "status")
    can_delete = False
    show_change_link = True
    ordering = ("-received_at",)

    def get_queryset(self, request):
        """Limit rows to past 180 days."""
        qs = super().get_queryset(request)
        return qs.filter(received_at__gte=timezone.now() - timedelta(days=180))

    def has_add_permission(self, request, obj=None):
        return False
