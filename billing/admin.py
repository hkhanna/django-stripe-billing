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
    list_display = ["__str__", "status", "received_at"]