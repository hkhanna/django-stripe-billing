from datetime import timedelta
import json
from django.utils import timezone
from django.contrib import admin
from django.urls import path, reverse
from django.shortcuts import get_object_or_404, redirect
from django.utils.html import format_html

from . import models, tasks


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
    list_display = [
        "__str__",
        "primary",
        "payload_type",
        "user",
        "status",
        "received_at",
        "event_actions",
    ]
    list_filter = ["type", "primary", "status"]
    search_fields = ["user__email", "payload_type", "type"]

    @admin.display(description="Actions")
    def event_actions(self, obj):
        return format_html(
            "<a class='button' href='{}'>Replay</a>",
            reverse("admin:replay_event", args=[obj.pk]),
        )

    def replay_event(self, request, pk):
        obj = get_object_or_404(models.StripeEvent, pk=pk)
        payload = json.loads(obj.body)
        event = models.StripeEvent.objects.create(
            event_id=obj.event_id,
            payload_type=payload["type"],
            headers=obj.headers,
            body=obj.body,
            status=models.StripeEvent.Status.NEW,
            note=f"Replay of event pk {obj.id}",
        )
        if hasattr(tasks, "shared_task"):
            tasks.process_stripe_event.apply(event.id, verify_signature=False)
        else:
            tasks.process_stripe_event(event.id, verify_signature=False)

        self.message_user(request, "Event replayed successfully.")
        return redirect("admin:billing_stripeevent_changelist")

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<pk>/replay",
                self.admin_site.admin_view(self.replay_event),
                name="replay_event",
            )
        ]
        return custom_urls + urls


class StripeEventAdminInline(admin.TabularInline):
    model = models.StripeEvent
    fields = ("__str__", "received_at", "event_id", "status")
    readonly_fields = ("__str__", "received_at", "event_id", "status")
    can_delete = False
    show_change_link = True
    ordering = ("-received_at",)

    def get_queryset(self, request):
        """Limit rows to past 180 days."""
        qs = super().get_queryset(request)
        return qs.filter(received_at__gte=timezone.now() - timedelta(days=180))

    def has_add_permission(self, request, obj=None):
        return False
