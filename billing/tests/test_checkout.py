import pytest
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone

from .. import factories, settings, models


@pytest.fixture
def session(user, paid_plan, mock_stripe_checkout):
    session = mock_stripe_checkout.Session.retrieve.return_value
    current_period_end = timezone.now() + timedelta(days=30)
    session.client_reference_id = user.id
    session.subscription.id = "sub_paid"
    session.subscription.status = "active"
    session.subscription.current_period_end = current_period_end.timestamp()
    session.customer.id = factories.id("cus")
    session.line_items = {"data": [{"price": {"id": paid_plan.price_id}}]}
    return session


def test_create_checkout_session_happy(auth_client, paid_plan, mock_stripe_checkout):
    """create_checkout_session creates a Stripe Session
    and redirects to the appropriate URL"""
    url = reverse(
        "billing:create_checkout_session",
        kwargs={"slug": paid_plan.slug, "pk": paid_plan.id},
    )
    response = auth_client.post(url, {})
    assert mock_stripe_checkout.Session.create.call_count == 1
    assert response.status_code == 302
    assert response.url == mock_stripe_checkout.Session.create.return_value.url


def test_create_checkout_session_bad_plan_id(
    auth_client, paid_plan, mock_stripe_checkout
):
    """Bad plan id should cancel the checkout flow"""
    url = reverse(
        "billing:create_checkout_session",
        kwargs={"slug": paid_plan.slug, "pk": paid_plan.id + 1},
    )
    response = auth_client.post(url, {})
    assert mock_stripe_checkout.Session.create.called is False
    assert response.status_code == 302
    assert response.url == settings.CHECKOUT_CANCEL_URL


def test_create_checkout_session_unmatched_plan_slug(
    auth_client, paid_plan, mock_stripe_checkout
):
    """A plan slug that doesn't match the id should fail"""
    url = reverse(
        "billing:create_checkout_session",
        kwargs={"slug": "badslug", "pk": paid_plan.id},
    )
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
    url = reverse(
        "billing:create_checkout_session",
        kwargs={"slug": paid_plan.slug, "pk": paid_plan.id},
    )
    response = auth_client.post(url, {})
    assert mock_stripe_checkout.Session.create.called is False
    assert response.status_code == 302
    assert response.url == settings.CHECKOUT_CANCEL_URL


def test_nonpublic_plan(auth_client, mock_stripe_checkout):
    """Billing Plans that are not public cannot be accessed via Checkout"""
    plan = factories.PlanFactory(type=models.Plan.Type.FREE_PRIVATE)
    url = reverse(
        "billing:create_checkout_session",
        kwargs={"slug": plan.slug, "pk": plan.id},
    )
    response = auth_client.post(url, {})
    assert mock_stripe_checkout.Session.create.called is False
    assert response.status_code == 302


def test_create_subscription_metadata(
    caplog, auth_client, user, session, mock_stripe_customer
):
    """Successful checkout session updates metadata on Stripe Customer"""
    mock_stripe_customer.retrieve.return_value.metadata = {}
    mock_stripe_customer.retrieve.return_value.email = user.email
    url = reverse("billing:checkout_success")
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
    url = reverse("billing:checkout_success")
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
    url = reverse("billing:checkout_success")
    query_params = {"session_id": factories.id("sess")}

    with caplog.at_level("ERROR"):
        response = auth_client.get(url, query_params)

    assert 302 == response.status_code
    assert settings.CHECKOUT_SUCCESS_URL == response.url
    assert mock_stripe_customer.modify.call_count == 1
    assert mock_stripe_customer.modify.call_args.kwargs["email"] == user.email


def test_webhook_create_subscription(client, customer, paid_plan, mock_stripe_customer):
    """invoice.paid should set the customer_id, plan, current_period_end, payment_state"""
    mock_period_end = (timezone.now() + timedelta(days=30)).timestamp()
    mock_stripe_customer.retrieve.return_value.email = customer.user.email

    url = reverse("billing:stripe_webhook")
    payload = {
        "id": "evt_test",
        "object": "event",
        "type": "invoice.paid",
        "data": {
            "object": {
                "billing_reason": "subscription_create",
                "customer": "cus",
                "subscription": "sub",
                "lines": {
                    "data": [
                        {
                            "plan": {"id": paid_plan.price_id},
                            "period": {"end": mock_period_end},
                        }
                    ]
                },
            }
        },
    }

    response = client.post(url, payload, content_type="application/json")
    assert 201 == response.status_code

    customer.refresh_from_db()
    assert paid_plan == customer.plan
    assert customer.customer_id == "cus"
    assert customer.payment_state == models.Customer.PaymentState.OK
    assert mock_period_end == customer.current_period_end.timestamp()
    assert "sub" == customer.subscription_id
    assert "paid.paying" == customer.state
    assert (
        models.StripeEvent.Status.PROCESSED == models.StripeEvent.objects.first().status
    )
