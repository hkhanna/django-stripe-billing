"""Stripe lifecycle webhook functionality. Webhooks where the user has taken
some action in Checkout or Portal are found elsewhere."""

from datetime import timedelta
from unittest.mock import Mock
from freezegun import freeze_time

import pytest
from django.utils import timezone
from django.urls import reverse

from .. import models, factories


@pytest.fixture
def customer():
    """Customer that is coming up for renewal"""
    user = factories.UserFactory(
        paying=True,
        customer__customer_id="cus",
    )
    assert "paid.paying" == user.customer.state  # Gut check
    return user.customer


@pytest.fixture
def subscription_event(customer, paid_plan):
    """Return a function that generates a Stripe Event payload with defaults of an active paid subscription."""

    def inner(**kwargs):
        type = kwargs.pop("type", "customer.subscription.updated")
        id = kwargs.pop("id", customer.subscription.id)
        customer_id = kwargs.pop("customer_id", customer.customer_id)
        current_period_end = kwargs.pop(
            "current_period_end", customer.current_period_end.timestamp()
        )
        price_id = kwargs.pop("price_id", paid_plan.price_id)
        cancel_at_period_end = kwargs.pop("cancel_at_period_end", False)
        created = kwargs.pop("created", timezone.now().timestamp())
        status = kwargs.pop("status", "active")

        payload = {
            "id": "evt_test",
            "object": "event",
            "type": type,
            "data": {
                "object": {
                    "id": id,
                    "customer": customer_id,
                    "current_period_end": current_period_end,
                    "items": {"data": [{"price": {"id": price_id}}]},
                    "cancel_at_period_end": cancel_at_period_end,
                    "created": created,
                    "status": status,
                }
            },
        }
        assert len(kwargs.keys()) == 0, "Unrecognized keys passed to payload fixture."
        return (
            locals()
        )  # For assertion convenience, we pass back all the variables at the top level as well.

    return inner


def test_create_event(client):
    """Create event"""
    url = reverse("billing:stripe_webhook")
    payload = {"id": "evt_test", "object": "event", "type": "test"}
    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 201
    assert 1 == models.StripeEvent.objects.count()


def test_bad_json(client):
    """Malformed JSON"""
    url = reverse("billing:stripe_webhook")
    payload = "bad json"
    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 400
    assert models.StripeEvent.objects.count() == 0


def test_unrecognized_type(client):
    """Unrecognized event type"""
    url = reverse("billing:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "bad.type",
        "data": {"object": None},
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert (
        models.StripeEvent.Status.IGNORED == models.StripeEvent.objects.first().status
    )


def test_subscription_event_new_stripe_subscription(
    customer, client, subscription_event
):
    """A Stripe Subscription event payload should correctly create a StripeSubscription."""
    url = reverse("billing:stripe_webhook")
    event_json = subscription_event()
    customer.stripesubscription_set.all().delete()
    assert 0 == models.StripeSubscription.objects.count()

    payload = event_json["payload"]
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert 1 == models.StripeEvent.objects.count()
    event = models.StripeEvent.objects.first()
    assert models.StripeEvent.Status.PROCESSED == event.status

    assert 1 == models.StripeSubscription.objects.count()
    subscription = models.StripeSubscription.objects.first()

    assert subscription.id == event_json["id"]
    assert subscription.customer.customer_id == event_json["customer_id"]
    assert (
        subscription.current_period_end.timestamp() == event_json["current_period_end"]
    )
    assert subscription.price_id == event_json["price_id"]
    assert subscription.cancel_at_period_end == event_json["cancel_at_period_end"]
    assert subscription.created.timestamp() == event_json["created"]
    assert subscription.status == event_json["status"]


def test_subscription_event_update_stripe_subscription(client, subscription_event):
    """A Stripe Subscription event payload should correctly update a StripeSubscription."""
    url = reverse("billing:stripe_webhook")
    event_attributes = {
        "current_period_end": (timezone.now() + timedelta(days=45)).timestamp(),
        # "price_id": "new_price" -- not available until we can upgrade plans
        "cancel_at_period_end": True,
        "created": timezone.now().timestamp(),
        "status": "past_due",
    }
    event_json = subscription_event(**event_attributes)
    # Ensure event_json is correct
    for k, v in event_attributes.items():
        assert event_json[k] == v

    payload = event_json["payload"]
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert 1 == models.StripeEvent.objects.count()
    event = models.StripeEvent.objects.first()
    assert models.StripeEvent.Status.PROCESSED == event.status

    assert 1 == models.StripeSubscription.objects.count()
    subscription = models.StripeSubscription.objects.first()

    assert subscription.id == event_json["id"]
    assert subscription.customer.customer_id == event_json["customer_id"]
    assert (
        subscription.current_period_end.timestamp() == event_json["current_period_end"]
    )
    assert subscription.price_id == event_json["price_id"]
    assert subscription.cancel_at_period_end == event_json["cancel_at_period_end"]
    assert subscription.created.timestamp() == event_json["created"]
    assert subscription.status == event_json["status"]


def test_link_event_to_user(client, customer, subscription_event):
    """A Stripe Event should be connected to a User."""
    url = reverse("billing:stripe_webhook")
    payload = subscription_event()["payload"]
    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 201
    event = models.StripeEvent.objects.first()
    assert event.user == customer.user


def test_user_not_found(client, mock_stripe_customer, subscription_event):
    """If a user can't be found, error."""
    url = reverse("billing:stripe_webhook")
    mock_stripe_customer.retrieve.return_value.email = "notfound@example.com"
    payload = subscription_event(id="sub_new", customer_id="cus_new")["payload"]

    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 201
    event = models.StripeEvent.objects.first()
    assert event.status == models.StripeEvent.Status.ERROR
    assert event.user == None
    assert "Customer.DoesNotExist" in event.note


def test_persist_customer_id(user, client, mock_stripe_customer, subscription_event):
    """A Customer without a Stripe customer_id gets it set on the first subscription event."""
    mock_stripe_customer.retrieve.return_value.email = user.email
    url = reverse("billing:stripe_webhook")
    event_json = subscription_event(id="sub_new", customer_id="cus_new")
    assert user.customer.customer_id is None

    payload = event_json["payload"]
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    user.customer.refresh_from_db()
    assert user.customer.customer_id == "cus_new"


def test_subscription_customer_mismatch(
    user, client, subscription_event, mock_stripe_customer
):
    """If a subscription already belongs to a different customer in the database than
    the customer_id reported on the event, something is wrong.
    This could happen if someone changes who the StripeSubscription instance is connected to in the admin."""
    mock_stripe_customer.retrieve.return_value.email = user.email
    url = reverse("billing:stripe_webhook")
    payload = subscription_event(customer_id="cus_different")["payload"]
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    event = models.StripeEvent.objects.first()
    assert event.status == models.StripeEvent.Status.ERROR
    assert "Integrity error" in event.note


def test_multiple_subscriptions_sync(client, subscription_event, monkeypatch):
    """If a customer has multiple subscriptions, the sync function is only called for the correct one."""
    mock = Mock()
    monkeypatch.setattr(models.StripeSubscription, "sync_to_customer", mock)
    url = reverse("billing:stripe_webhook")

    payload = subscription_event(id="sub_different", status="past_due")["payload"]
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert mock.call_count == 0

    payload = subscription_event(status="past_due")["payload"]
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert mock.call_count == 1


def test_payment_update_active(
    client, customer, subscription_event, mock_stripe_invoice
):
    """An update to a Subscription's payment method does not do anything if the Subscription is
    active."""
    url = reverse("billing:stripe_webhook")
    payload = subscription_event()["payload"]
    payload["data"]["previous_attributes"] = {"default_payment_method": "pm_new"}
    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 201
    event = models.StripeEvent.objects.first()
    assert event.status == models.StripeEvent.Status.PROCESSED
    assert event.user.customer == customer
    assert mock_stripe_invoice.list.call_count == 0
    assert mock_stripe_invoice.pay.call_count == 0


@pytest.mark.parametrize("status", ["incomplete", "past_due"])
def test_payment_update_and_retry(
    client, subscription_event, customer, status, mock_stripe_invoice
):
    """An update to a Subscription's payment method when not active automatically retries the last open invoice."""
    mock_stripe_invoice.list.return_value = {
        "data": [{"status": "open", "id": "inv_123"}]
    }
    url = reverse("billing:stripe_webhook")

    payload = subscription_event(status=status)["payload"]
    payload["data"]["previous_attributes"] = {"default_payment_method": "pm_new"}

    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 201
    event = models.StripeEvent.objects.first()
    assert event.status == models.StripeEvent.Status.PROCESSED
    assert event.user.customer == customer
    assert mock_stripe_invoice.list.call_count == 1
    assert mock_stripe_invoice.pay.call_count == 1
