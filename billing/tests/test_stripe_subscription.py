"""Tests related to StripeSubscription model."""

import pytest

from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from .. import models, factories

User = get_user_model()


@pytest.mark.parametrize(
    "status", ["incomplete", "incomplete_expired", "active", "past_due", "canceled"]
)
def test_sync_active(customer, paid_plan, status):
    """Only an active StripeSubscription syncs the Plan and current_period_end to the Customer"""
    subscription = factories.StripeSubscriptionFactory(
        customer=customer,
        status=status,
        price_id=paid_plan.price_id,
        current_period_end=timezone.now() + timedelta(days=30),
        dont_sync_to_customer=True,
    )
    customer.refresh_from_db()
    assert (
        customer.plan
        == models.Plan.objects.filter(type=models.Plan.Type.FREE_DEFAULT).first()
    )

    subscription.sync_to_customer()

    customer.refresh_from_db()
    if status == "active":
        assert customer.plan == paid_plan
        assert customer.current_period_end == subscription.current_period_end
    else:
        assert customer.plan != paid_plan
        assert customer.current_period_end != subscription.current_period_end


@pytest.mark.parametrize(
    "status", ["incomplete", "incomplete_expired", "active", "past_due", "canceled"]
)
def test_sync_canceled(customer, paid_plan, status):
    """Only a canceled or incomplete_expired StripeSubscription downgrades
    the Customer to free_default and zeroes out current_period_end"""
    subscription = factories.StripeSubscriptionFactory(
        customer=customer,
        status="active",
        price_id=paid_plan.price_id,
        current_period_end=timezone.now() + timedelta(days=30),
    )
    assert customer.plan == paid_plan

    subscription.status = status
    subscription.save()
    subscription.sync_to_customer()

    customer.refresh_from_db()
    free_default = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
    if status in (
        models.StripeSubscription.Status.CANCELED,
        models.StripeSubscription.Status.INCOMPLETE,
        models.StripeSubscription.Status.INCOMPLETE_EXPIRED,
    ):
        assert customer.plan == free_default
        assert customer.current_period_end == None
    else:
        assert customer.plan == paid_plan
        assert customer.current_period_end == subscription.current_period_end
