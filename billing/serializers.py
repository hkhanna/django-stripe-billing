from rest_framework import serializers
from django.utils import timezone

from . import models


class PlanSerializer(serializers.ModelSerializer):
    limits = serializers.SerializerMethodField()

    def get_limits(self, obj):
        """If the PlanLimit has a value, use that. Otherwise use the Limit default."""
        plan_limits = {
            plan_limit.limit.name: plan_limit.value
            for plan_limit in obj.planlimit_set.all()
        }
        other_limits = {
            limit.name: limit.default
            for limit in models.Limit.objects.exclude(plans=obj)
        }
        return {**plan_limits, **other_limits}

    class Meta:
        model = models.Plan
        fields = ["name", "display_price", "type", "limits"]
        read_only_fields = ["name", "display_price", "type", "limits"]


class CustomerSerializer(serializers.ModelSerializer):
    plan = serializers.SerializerMethodField(read_only=True)

    def get_plan(self, obj):
        """If the Customer's plan is not expired, we use it. Otherwise we substitute in the free_default plan
        as the Customer's effective plan."""
        plan = obj.plan

        plan_expired = (
            obj.current_period_end is not None
            and obj.current_period_end < timezone.now()
        )
        if plan_expired:
            # If the Plan is expired, use the values from the free_default plan
            plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
        elif (
            obj.current_period_end is None and plan.type == models.Plan.Type.PAID_PUBLIC
        ):
            # If current_period_end is None, use the values from the free_default plan if the user's plan is PAID_PUBLIC.
            # I.e., free_private plans without current_period_end exist indefinitely.
            plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)

        plan_serializer = PlanSerializer(instance=plan)
        return plan_serializer.data

    class Meta:
        model = models.Customer
        fields = ["current_period_end", "payment_state", "cc_info", "state", "plan"]
        read_only_fields = [
            "current_period_end",
            "payment_state",
            "cc_info",
            "state",
            "plan",
        ]


class CreateSubscriptionSerializer(serializers.Serializer):
    payment_method_id = serializers.CharField(max_length=254)
    plan_id = serializers.IntegerField(min_value=1)

    def validate_plan_id(self, value):
        # Billing Plan must exist and be accessible
        self.plan = models.Plan.objects.filter(
            id=value, type=models.Plan.Type.PAID_PUBLIC
        ).first()
        if not self.plan:
            raise serializers.ValidationError("Billing plan does not exist.")

        # User must not have an active billing plan
        # If a user is trying to switch between paid plans, this is the wrong endpoint.
        customer = self.context["request"].user.customer
        if customer.state not in ("free_default.new", "free_default.canceled"):
            raise serializers.ValidationError("User already has a subscription.")

        return value
