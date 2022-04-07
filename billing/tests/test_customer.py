"""Tests related to automatic Customer creation and model constraints. These are tests of type 1 and 2."""
# A customer is automatically created if a user does not have one, and it accomplishes this via signals.
# We also have some model constraints we want to test.

import pytest

from django.contrib.auth import get_user_model

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
    assert "ok" == user.customer.payment_state

    user.is_active = False
    user.save()
    assert mock_stripe_subscription.delete.call_count == 1


def test_delete_user_active_subscription(mock_stripe_subscription):
    """Hard deleting a User with an active Stripe subscription cancels the Subscription."""
    user = factories.UserFactory(paying=True)
    user.delete()
    assert mock_stripe_subscription.delete.call_count == 1
    assert 0 == models.Customer.objects.count()
