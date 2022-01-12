import logging
from unittest import mock

import stripe
from . import settings

stripe.api_key = settings.STRIPE_API_KEY

logger = logging.getLogger(__name__)


def stripe_customer_sync_metadata_email(user, stripe_customer_id):
    """If a Stripe customer has metadata, it should make sense.
    If there is no metadata, create it. If the metadata exists but
    appears wrong, log an error. Finally, sync the Stripe Customer's email
    to whatever is in the Django db."""
    if settings.STRIPE_API_KEY == "mock":
        return
    stripe_customer = stripe.Customer.retrieve(stripe_customer_id)
    metadata = stripe_customer.metadata
    customer_update = {}
    user_pk = metadata.get("user_pk", None)
    application = metadata.get("application", None)
    errored = False

    if not application:
        customer_update.setdefault("metadata", {})
        customer_update["metadata"]["application"] = settings.APPLICATION_NAME
    elif application != settings.APPLICATION_NAME:
        logger.error(
            f"User.id={user.pk} Application name {settings.APPLICATION_NAME} does not match Stripe metadata {application}"
        )
        errored = True

    if not user_pk:
        customer_update.setdefault("metadata", {})
        customer_update["metadata"]["user_pk"] = user.pk
    elif str(user_pk) != str(user.pk):
        logger.error(
            f"User.id={user.pk} does not match Stripe metadata user_pk {user_pk}."
        )
        errored = True

    if errored:
        return False

    if user.email != stripe_customer.email:
        logger.warning(
            f"User.id={user.pk} changed their email on Stripe to {stripe_customer.email}. Reverting."
        )
        customer_update["email"] = user.email
    if customer_update:
        stripe_modify_customer(stripe_customer_id, **customer_update)


def stripe_modify_customer(customer_id, **kwargs):
    if settings.STRIPE_API_KEY == "mock":
        return mock.MagicMock(id=customer_id)

    customer = stripe.Customer.modify(customer_id, **kwargs)
    return customer


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


def stripe_cancel_subscription(subscription_id, immediate=False):
    if settings.STRIPE_API_KEY == "mock":
        return None

    # From https://stripe.com/docs/billing/subscriptions/cancel#canceling
    if immediate:
        return stripe.Subscription.delete(subscription_id)
    else:
        return stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)


def stripe_check_webhook_signature(event):
    sig_header = event.headers["Stripe-Signature"].strip()
    stripe.Webhook.construct_event(
        event.body, sig_header, settings.STRIPE_WH_SECRET.strip()
    )
