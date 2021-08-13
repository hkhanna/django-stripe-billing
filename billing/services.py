import logging
from datetime import timedelta
from unittest import mock

import stripe
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import APIException

stripe.api_key = settings.STRIPE_API_KEY
user_pk_key = settings.BILLING_APPLICATION_NAME + "_user_pk"

logger = logging.getLogger(__name__)


def stripe_get_customer(user):
    if settings.STRIPE_API_KEY == "mock":
        return None

    candidate = None
    try:
        customers = stripe.Customer.list(email=user.email)
        if len(customers.data) == 0:
            return None
        if len(customers.data) > 1:
            logger.error(f"User.email={user.email} more than 1 Stripe Customer found")

        for customer in customers.data:
            pk = getattr(customer.metadata, user_pk_key, None)
            if pk is None:
                candidate = customer
            elif str(pk) == str(user.pk):
                return customer
            else:
                logger.error(
                    f"User.email={user.email} found Stripe customer but user_id does not match."
                )

    except Exception as e:
        logger.exception(f"User.email={user.email} Error listing Stripe customers")

    return candidate


def check_update_stripe_customer_metadata(user, customer):
    """Confirm the correct metadata is on the Stripe customer and, if not, correct it in Stripe."""
    pk = getattr(customer.metadata, user_pk_key, None)
    if pk is None:
        stripe_modify_customer(user, metadata={user_pk_key: user.pk})
        return True
    elif str(pk) == str(user.pk):
        return False
    else:
        logger.error(
            f"User.email={user.email} check_update_stripe_customer_metadata was called with a bad value for the user's primary key"
        )
        return False


def stripe_create_customer(user):
    if settings.STRIPE_API_KEY == "mock":
        from . import factories

        return mock.MagicMock(id=factories.id("cus"))

    try:
        # Create a new customer object
        customer = stripe.Customer.create(
            name=user.name,
            email=user.email,
            metadata={user_pk_key: user.pk},
        )
        return customer

    except Exception as e:
        logger.exception("Error creating Stripe customer")
        raise APIException(
            "These was a problem connecting to Stripe. Please try again."
        )


def stripe_modify_customer(user, **kwargs):
    if settings.STRIPE_API_KEY == "mock":
        return mock.MagicMock(id=user.customer.customer_id)

    customer = stripe.Customer.modify(user.customer.customer_id, **kwargs)
    return customer


def stripe_create_subscription(customer_id, payment_method_id, price_id):
    if settings.STRIPE_API_KEY == "mock":
        from . import factories

        return (
            mock.MagicMock(
                id=factories.id("sub"),
                status="active",
                current_period_end=(timezone.now() + timedelta(days=30)).timestamp(),
            ),
            mock.MagicMock(card=factories.cc_info()),
        )

    # From https://stripe.com/docs/billing/subscriptions/fixed-price#collect-payment
    payment_method = stripe.PaymentMethod.attach(
        payment_method_id, customer=customer_id
    )
    subscription = stripe.Subscription.create(
        customer=customer_id,
        items=[{"price": price_id}],
        expand=["latest_invoice.payment_intent"],
        default_payment_method=payment_method_id,
    )

    return subscription, payment_method


def stripe_replace_card(customer_id, subscription_id, payment_method_id):
    if settings.STRIPE_API_KEY == "mock":
        from . import factories

        return mock.MagicMock(card=factories.cc_info())

    payment_method = stripe.PaymentMethod.attach(
        payment_method_id, customer=customer_id
    )
    stripe.Subscription.modify(
        subscription_id, default_payment_method=payment_method_id
    )
    return payment_method


def stripe_retry_latest_invoice(customer_id):
    if settings.STRIPE_API_KEY == "mock":
        from . import factories

        return {
            "status": "paid",
            "lines": {
                "data": [
                    {
                        "period": {
                            "end": factories.fake.future_datetime(
                                end_date="+30d"
                            ).timestamp()
                        }
                    }
                ]
            },
        }

    invoice_list = stripe.Invoice.list(customer=customer_id, limit=1)["data"]

    # There must be a latest invoice
    if len(invoice_list) == 0:
        logger.error(
            f"stripe customer {customer_id} has no invoices but stripe_retry_latest_invoice was called"
        )
        return None

    # The latest invoice must have status as open
    invoice = invoice_list[0]
    if invoice["status"] != "open":
        logger.error(
            f"stripe customer {customer_id} invoice {invoice['id']} is set to status {invoice['status']}"
            f" in stripe_retry_latest_invoice."
        )
        return None

    invoice = stripe.Invoice.pay(invoice["id"])
    return invoice


def stripe_cancel_subscription(subscription_id):
    if settings.STRIPE_API_KEY == "mock":
        return None

    # From https://stripe.com/docs/billing/subscriptions/cancel#canceling
    return stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)


def stripe_reactivate_subscription(subscription_id):
    if settings.STRIPE_API_KEY == "mock":
        return None

    # https://stripe.com/docs/billing/subscriptions/cancel#reactivating-canceled-subscriptions
    return stripe.Subscription.modify(subscription_id, cancel_at_period_end=False)
