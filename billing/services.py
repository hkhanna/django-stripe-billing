import logging
from datetime import timedelta
from unittest import mock

import stripe
from django.utils import timezone
from rest_framework.exceptions import APIException
from . import settings

stripe.api_key = settings.STRIPE_API_KEY

logger = logging.getLogger(__name__)


def stripe_customer_check_metadata(user):
    """If a Stripe customer has metadata, it should make sense.
    If there is no metadata, create it. If the metadata exists but
    appears wrong, log an error."""
    if settings.STRIPE_API_KEY == "mock":
        return
    stripe_customer = stripe.Customer.retrieve(user.customer.customer_id)
    metadata = stripe_customer.metadata
    new_metadata = {}
    user_pk = metadata.get("user_pk", None)
    application = metadata.get("application", None)

    if not user_pk:
        new_metadata["user_pk"] = user.pk
    elif user_pk != user.pk:
        logger.error(
            f"User.id={user.pk} does not match Stripe metadata user_pk {user_pk}."
        )

    if not application:
        new_metadata["application"] = settings.APPLICATION_NAME
    elif application != settings.APPLICATION_NAME:
        logger.error(
            f"User.id={user.pk} Application name {settings.APPLICATION_NAME} does not match Stripe metadata {application}"
        )

    if new_metadata:
        stripe_modify_customer(user, metadata=new_metadata)


def stripe_create_customer(user):
    if settings.STRIPE_API_KEY == "mock":
        from . import factories

        return mock.MagicMock(id=factories.id("cus"))

    try:
        # Create a new customer object
        customer = stripe.Customer.create(
            name=user.name,
            email=user.email,
            metadata={"user_pk": user.pk, "application": settings.APPLICATION_NAME},
        )
        return customer

    except Exception as e:
        logger.exception("Error creating Stripe customer")
        raise APIException(  # TODO
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
