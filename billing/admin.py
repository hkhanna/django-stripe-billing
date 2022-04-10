from datetime import timedelta
import json
from django.utils import timezone
from django.utils.html import format_html
from django.contrib import admin
from django.urls import reverse
from django.shortcuts import redirect
from django.contrib.auth import get_user_model

User = get_user_model()

from . import models, tasks


class CustomerAdminInline(admin.StackedInline):
    model = models.Customer
    verbose_name_plural = "Customer Profile"
    can_delete = (
        False  # You can't delete a Customer in the admin without deleting the User.
    )
    readonly_fields = ("state", "subscription_link")

    def subscription_link(self, obj):
        if obj.subscription:
            path = reverse(
                f"admin:billing_stripesubscription_change",
                args=(obj.subscription.id,),
            )
            return format_html("<a href={}>{}</a>", path, obj.subscription)


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
        "payload_type",
        "subscription_status",
        "user_link",
        "received_at",
        "status",
    ]
    list_filter = ["payload_type", "status"]
    search_fields = ["user__email", "payload_type", "type"]
    ordering = ["-received_at"]
    actions = ["replay_event"]

    @admin.display(description="User")
    def user_link(self, obj):
        if obj.user:
            path = reverse(
                f"admin:{User._meta.app_label}_{User._meta.model_name}_change",
                args=(obj.user.id,),
            )
            return format_html("<a href={}>{}</a>", path, obj.user)

    def subscription_status(self, obj):
        if obj.payload_type.startswith("customer.subscription."):
            payload = json.loads(obj.body)
            return payload["data"]["object"]["status"]

    @admin.action(description="Replay event")
    def replay_event(self, request, queryset):

        for obj in queryset.all():
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
                tasks.process_stripe_event.apply(
                    kwargs={"event_id": event.id, "verify_signature": False}
                )
            else:
                tasks.process_stripe_event(event.id, verify_signature=False)

            self.message_user(request, f"Event  {obj.id} replayed successfully.")

        return redirect("admin:billing_stripeevent_changelist")


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


@admin.register(models.StripeSubscription)
class StripeSubscriptionAdmin(admin.ModelAdmin):
    can_delete = False
    ordering = ("-created",)
