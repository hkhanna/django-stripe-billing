"""Tests related to automatic Customer creation and model constraints."""
# A customer is automatically created if a user does not have one, and it accomplishes this via signals.
# We also have some model constraints we want to test.

import pytest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from .. import models, factories

User = get_user_model()


def test_save_user_create_customer():
    """Saving a User without a Customer automatically creates a Customer with the free_default plan.
    This tests both the automatic creation of a Customer and the automatic creation of a free_default plan."""

    # Not using the UserFactory here to really emphasize that we're saving a User and triggering
    # the signal.
    user = User.objects.create_user(
        first_name="Firstname",
        last_name="Lastname",
        username="Firstname Lastname",
        email="user@example.com",
    )
    assert user.customer.state == "free_default.new"
    assert models.Customer.objects.filter(user=user).exists() is True
    assert 1 == models.Plan.objects.filter(type=models.Plan.Type.FREE_DEFAULT).count()


def test_save_user_create_customer_exists():
    """Saving a User that has a Customer does not create a Customer."""
    user = factories.UserFactory()
    customer_id = user.customer.id
    user.save()
    customer = models.Customer.objects.get(user=user)
    assert customer_id == customer.id


def test_save_user_save_customer():
    """Saving a User with a related Customer saves the Customer as well."""
    user = factories.UserFactory()
    customer_id = "cus_xyz"
    user.customer.customer_id = customer_id
    user.save()
    customer = models.Customer.objects.get(user=user)
    assert customer_id == customer.customer_id


@pytest.mark.parametrize(
    "field,value,should_call",
    [
        ("first_name", factories.fake.first_name(), True),
        ("last_name", factories.fake.last_name(), True),
        ("email", factories.fake.safe_email(), True),
        (
            "is_staff",
            True,
            False,  # Don't call out to Stripe unless name or email changed.
        ),
    ],
)
def test_update_user_stripe(field, value, should_call, mock_stripe_customer):
    """Updating a User's first_name, last_name, or email also updates it in Stripe."""
    user = factories.UserFactory(paying=True)
    setattr(user, field, value)
    user.save()
    assert mock_stripe_customer.modify.called is should_call


def test_soft_delete_user_active_subscription(mock_stripe_subscription):
    """Soft deleting a User with an active Stripe subscription cancels the Subscription."""
    user = factories.UserFactory(paying=True)
    user.save()
    assert mock_stripe_subscription.modify.called is False
    assert user.customer.subscription.status == models.StripeSubscription.Status.ACTIVE

    user.is_active = False
    user.save()
    assert mock_stripe_subscription.delete.call_count == 1


def test_delete_user_active_subscription(mock_stripe_subscription):
    """Hard deleting a User with an active Stripe subscription cancels the Subscription."""
    user = factories.UserFactory(paying=True)
    user.delete()
    assert mock_stripe_subscription.delete.call_count == 1
    assert 0 == models.Customer.objects.count()


def test_subscription_multiple():
    """If a Customer has multiple StripeSubscriptions, prefer the active one."""
    user = factories.UserFactory(paying=True)
    customer = user.customer
    factories.StripeSubscriptionFactory(customer=customer, status="incomplete")
    customer.refresh_from_db()
    assert customer.stripesubscription_set.count() == 2
    assert customer.subscription.status == "active"


def test_no_subscriptions(customer):
    """If a Customer has no StripeSubscription, return None for Customer.subscription"""
    customer.stripesubscription_set.all().delete()
    customer.refresh_from_db()
    assert customer.subscription is None


def test_cancel_subscription_immediately(mock_stripe_subscription):
    """Immediately canceling a subscription calls out to Stripe to cancel immediately."""
    user = factories.UserFactory(paying=True)
    customer = user.customer
    customer.cancel_subscription(immediate=True)
    assert mock_stripe_subscription.delete.called is True
    assert (
        customer.state == "paid.paying"
    )  # No change to state until we receive the webhook.


## -- Customer State Calculation Testing -- ##

CUSTOMER_STATES = [
    ["Never paid", models.Plan.Type.FREE_DEFAULT, None, None, None, "free_default.new"],
    [
        # N.B. This can happen if the payment fails after attachment. It also happens every time
        # a new Subscription is created. It's a very first step and quickly overriden if payment succeeds.
        # Because of that we are ignoring that blip since it's unlikely to affect anyone.
        "Incomplete",
        models.Plan.Type.PAID_PUBLIC,
        timezone.now() + timedelta(days=30),
        False,
        "incomplete",
        "free_default.incomplete.requires_payment_method",
    ],
    [
        "Incomplete Expired",
        models.Plan.Type.PAID_PUBLIC,
        timezone.now() + timedelta(days=30),
        False,
        "incomplete_expired",
        "free_default.new",
    ],
    [
        "Active / Renewed / Reactivated",
        models.Plan.Type.PAID_PUBLIC,
        timezone.now() + timedelta(days=30),
        False,
        "active",
        "paid.paying",
    ],
    [
        "Payment failure",
        models.Plan.Type.PAID_PUBLIC,
        timezone.now() + timedelta(days=3),
        False,
        "past_due",
        "paid.past_due.requires_payment_method",
    ],
    [
        "Payment failure, plan expired but not yet canceled",
        models.Plan.Type.PAID_PUBLIC,
        timezone.now() - timedelta(days=1),
        False,
        "past_due",
        "free_default.past_due.requires_payment_method",
    ],
    [
        "Will cancel",
        models.Plan.Type.PAID_PUBLIC,
        timezone.now() + timedelta(days=10),
        True,
        "active",
        "paid.will_cancel",
    ],
    [
        "Missed final cancelation webhook",
        models.Plan.Type.PAID_PUBLIC,
        timezone.now() - timedelta(days=1),
        True,
        "active",
        "free_default.canceled.missed_webhook",
    ],
    [
        "Canceled",
        models.Plan.Type.PAID_PUBLIC,
        timezone.now(),
        True,  # This shouldn't matter. It's probably True if the user intentionally canceled, and False if it was payment failure.
        "canceled",
        "free_default.new",
    ],
    [
        "Free Private Indefinite",
        models.Plan.Type.FREE_PRIVATE,
        None,
        None,
        None,
        "free_private.indefinite",
    ],
    [
        "Free Private Will Expire",
        models.Plan.Type.FREE_PRIVATE,
        timezone.now() + timedelta(days=100),
        None,
        None,
        "free_private.will_expire",
    ],
    [
        "Free Private Expired",
        models.Plan.Type.FREE_PRIVATE,
        timezone.now() - timedelta(days=1),
        None,
        None,
        "free_private.expired",
    ],
]


@pytest.mark.parametrize(
    "name,plan_type,current_period_end,cancel_at_period_end,subscription_status,customer_state",
    CUSTOMER_STATES,
)
def test_customer_state(
    customer,
    name,
    plan_type,
    current_period_end,
    cancel_at_period_end,
    subscription_status,
    customer_state,
):
    factories.PlanFactory(paid=True)
    factories.PlanFactory(type=models.Plan.Type.FREE_PRIVATE)
    assert customer.state == "free_default.new"

    plan = models.Plan.objects.filter(type=plan_type).first()
    customer.plan = plan
    customer.current_period_end = current_period_end
    customer.save()

    if subscription_status:
        factories.StripeSubscriptionFactory(
            customer=customer,
            price_id=plan.price_id,
            current_period_end=current_period_end,
            cancel_at_period_end=cancel_at_period_end,
            status=subscription_status,
        )

    assert customer.state == customer_state
