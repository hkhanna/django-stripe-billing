import pytest
import json
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone

from .. import factories, settings, models


@pytest.fixture
def session(user, paid_plan, mock_stripe_checkout):
    session = mock_stripe_checkout.Session.retrieve.return_value
    current_period_end = timezone.now() + timedelta(days=30)
    cc_info = factories.cc_info()
    session.client_reference_id = user.id
    session.subscription.id = "sub_paid"
    session.subscription.status = "active"
    session.subscription.current_period_end = current_period_end.timestamp()
    session.subscription.default_payment_method.card = cc_info
    session.customer.id = factories.id("cus")
    session.line_items = {"data": [{"price": {"id": paid_plan.price_id}}]}
    return session


def test_create_checkout_session_happy(auth_client, paid_plan, mock_stripe_checkout):
    """create_checkout_session creates a Stripe Session
    and redirects to the appropriate URL"""
    url = reverse("billing_checkout:create_checkout_session")
    payload = {"plan_id": paid_plan.id}
    response = auth_client.post(url, payload)
    assert mock_stripe_checkout.Session.create.call_count == 1
    assert response.status_code == 302
    assert response.url == mock_stripe_checkout.Session.create.return_value.url


def test_create_checkout_session_bad_plan_id(
    auth_client, paid_plan, mock_stripe_checkout
):
    """Bad plan id should cancel the checkout flow"""
    url = reverse("billing_checkout:create_checkout_session")
    payload = {"plan_id": paid_plan.id + 1}
    response = auth_client.post(url, payload)
    assert mock_stripe_checkout.Session.create.called is False
    assert response.status_code == 302
    assert response.url == settings.CHECKOUT_CANCEL_URL


def test_create_checkout_session_bad_plan_id(
    auth_client, paid_plan, mock_stripe_checkout
):
    """No plan id should cancel the checkout flow"""
    url = reverse("billing_checkout:create_checkout_session")
    payload = {}
    response = auth_client.post(url, payload)
    assert mock_stripe_checkout.Session.create.called is False
    assert response.status_code == 302
    assert response.url == settings.CHECKOUT_CANCEL_URL


def test_create_checkout_session_already_paid(
    auth_client, paid_plan, user, mock_stripe_checkout
):
    """A User with an existing subscription may not access the create_checkout_session endpoint."""
    factories.set_customer_paying(user.customer)
    url = reverse("billing_checkout:create_checkout_session")
    payload = {"plan_id": paid_plan.id}
    response = auth_client.post(url, payload)
    assert mock_stripe_checkout.Session.create.called is False
    assert response.status_code == 302
    assert response.url == settings.CHECKOUT_CANCEL_URL


def test_nonpublic_plan(auth_client, mock_stripe_checkout):
    """Billing Plans that are not public cannot be accessed via Checkout"""
    plan = factories.PlanFactory(type=models.Plan.Type.FREE_PRIVATE)
    url = reverse("billing_checkout:create_checkout_session")
    payload = {"plan_id": plan.id}
    response = auth_client.post(url, payload)
    assert mock_stripe_checkout.Session.create.called is False
    assert response.status_code == 302


def test_create_subscription_metadata(
    caplog, auth_client, user, session, mock_stripe_customer
):
    """Successful checkout session updates metadata on Stripe Customer"""
    mock_stripe_customer.retrieve.return_value.metadata = {}
    mock_stripe_customer.retrieve.return_value.email = user.email
    url = reverse("billing_checkout:checkout_success")
    query_params = {"session_id": factories.id("sess")}

    with caplog.at_level("ERROR"):
        response = auth_client.get(url, query_params)

    assert 302 == response.status_code
    assert settings.CHECKOUT_SUCCESS_URL == response.url
    assert mock_stripe_customer.retrieve.call_count == 1
    assert mock_stripe_customer.modify.call_count == 1
    assert len(caplog.records) == 0


@pytest.mark.parametrize(
    "application,logs", [(settings.APPLICATION_NAME, 1), ("bad", 2)]
)
def test_create_subscription_bad_metadata(
    application, logs, caplog, auth_client, session, mock_stripe_customer
):
    """Bad metadata does not update the Stripe Customer and logs an error"""
    mock_stripe_customer.retrieve.return_value.metadata = {
        "user_pk": "bad",
        "application": application,
    }
    url = reverse("billing_checkout:checkout_success")
    query_params = {"session_id": factories.id("sess")}

    with caplog.at_level("ERROR"):
        response = auth_client.get(url, query_params)

    assert 302 == response.status_code
    assert settings.CHECKOUT_SUCCESS_URL == response.url
    assert mock_stripe_customer.retrieve.call_count == 1
    assert mock_stripe_customer.modify.call_count == 0
    assert len(caplog.records) == logs


def test_create_subscription_changed_email(
    caplog, auth_client, user, session, mock_stripe_customer
):
    """If a User changes their email during the Checkout process, revert it."""
    mock_stripe_customer.retrieve.return_value.metadata = {}
    mock_stripe_customer.retrieve.return_value.email = "new@example.com"
    url = reverse("billing_checkout:checkout_success")
    query_params = {"session_id": factories.id("sess")}

    with caplog.at_level("ERROR"):
        response = auth_client.get(url, query_params)

    assert 302 == response.status_code
    assert settings.CHECKOUT_SUCCESS_URL == response.url
    assert mock_stripe_customer.modify.call_count == 1
    assert mock_stripe_customer.modify.call_args.kwargs["email"] == user.email


def test_webhook_create_subscription(
    client, user, paid_plan, session, mock_stripe_checkout
):
    """checkout.session.completed should set the customer_id, plan, current_period_end,
    payment_state and card_info"""
    url = reverse("billing_api:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {"id": factories.id("sess")}},
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert mock_stripe_checkout.Session.retrieve.call_count == 1

    user.refresh_from_db()
    assert paid_plan == user.customer.plan
    assert user.customer.customer_id == session.customer.id
    assert user.customer.payment_state == models.Customer.PaymentState.OK
    assert (
        session.subscription.current_period_end
        == user.customer.current_period_end.timestamp()
    )
    assert "sub_paid" == user.customer.subscription_id
    assert "paid.paying" == user.customer.state
    assert json.dumps(user.customer.cc_info, sort_keys=True) == json.dumps(
        session.subscription.default_payment_method.card,
        sort_keys=True,
    )
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )


def test_webhook_create_subscription_mismatched_customer_id(
    client, user, session, mock_stripe_checkout
):
    """A mismatched customer_id returned from the Session should log an error and update the User's customer_id."""
    url = reverse("billing_api:stripe_webhook")
    user.customer.customer_id = "cus_mismatch"
    user.customer.save()
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {"id": factories.id("sess")}},
    }
    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code
    assert mock_stripe_checkout.Session.retrieve.call_count == 1
    user.refresh_from_db()
    assert user.customer.customer_id == session.customer.id
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )


def test_link_event_to_user(client, user, session):
    url = reverse("billing_api:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {"id": factories.id("sess")}},
    }
    response = client.post(url, payload, content_type="application/json")
    assert response.status_code == 201
    event = models.StripeEvent.objects.first()
    assert event.user == user
