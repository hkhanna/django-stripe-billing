import pytest
from django.urls import reverse

from .. import factories, models


@pytest.fixture
def user():
    user = factories.UserFactory(
        paying=True,
        customer__customer_id="cus",
    )
    assert "paid.paying" == user.customer.state  # Gut check
    return user


def test_portal_happy(auth_client, mock_stripe_billing_portal):
    """A Customer can create a Stripe Portal session"""
    url = reverse("billing:create_portal_session")
    response = auth_client.post(url)
    assert mock_stripe_billing_portal.Session.create.call_count == 1
    assert response.status_code == 302
    # URL for the Portal itself
    assert response.url == mock_stripe_billing_portal.Session.create.return_value.url


def test_portal_wrong_state(auth_client, customer, mock_stripe_billing_portal):
    """A Customer with an inapproprate state should not be able to access the Stripe Portal"""
    customer.stripesubscription_set.all().delete()
    customer.plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
    customer.current_period_end = None
    customer.save()
    assert customer.state == "free_default.new"

    payload = {"return_url": "http://example.com/return_url"}
    url = reverse("billing:create_portal_session")
    response = auth_client.post(url, payload)
    assert mock_stripe_billing_portal.Session.create.call_count == 0
    assert response.status_code == 302
    # URL on the app since it never makes it to the Portal session.
    assert response.url == "http://example.com/return_url"
