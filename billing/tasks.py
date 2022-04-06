import json
from datetime import datetime as dt
import logging
import traceback
import stripe

from django.utils import timezone
from django.contrib.auth import get_user_model

from . import models, settings, services

User = get_user_model()
EVENT_TYPE = models.StripeEvent.Type

try:
    from celery.utils.log import get_task_logger

    logger = get_task_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


def _preprocess_payload_type(event):
    payload = json.loads(event.body)
    data_object = payload["data"]["object"]
    event.type = EVENT_TYPE.UNKNOWN

    # invoice.paid -> new or renewed subscription
    if payload["type"] == "invoice.paid":
        # billing_reason=subscription_cycle means its a renewal, not a new subscription.
        # See https://stackoverflow.com/questions/22601521/stripe-webhook-events-renewal-of-subscription
        if data_object["billing_reason"] == "subscription_create":
            event.type = EVENT_TYPE.NEW_SUB
            event.primary = True
        elif data_object["billing_reason"] == "subscription_cycle":
            event.type = EVENT_TYPE.RENEW_SUB
            event.primary = True
        else:
            # Other billing_reasons should not happen.
            event.note = f"Unrecognized invoice.paid billing_reason: {data_object['billing_reason']}."
        # TODO: Upgrading and downgrading subscriptions may generate a "subscription_update" billing reason.

    # invoice.payment_failed -> payment isn't working (new or renewal)
    elif payload["type"] == "invoice.payment_failed":
        # You need the billing reason here too. Otherwise it tracks a
        # payment failure when the subscription is incomplete on setup.
        if data_object["billing_reason"] == "subscription_create":
            event.type = EVENT_TYPE.NEW_SUB
            event.primary = True
        if data_object["billing_reason"] == "subscription_cycle":
            event.type = EVENT_TYPE.PAYMENT_FAIL
            event.primary = True
        else:
            # Other billing_reasons should not happen.
            event.note = f"Unrecognized invoice.payment_failed billing_reason: {data_object['billing_reason']}."
        # TODO: Upgrading and downgrading subscriptions may generate a "subscription_update" billing reason.

    # customer.subscription.updated
    elif payload["type"] == "customer.subscription.updated":
        prev = payload["data"]["previous_attributes"]
        # Cancelation
        if (
            data_object["cancel_at_period_end"] is True
            and prev.get("cancel_at_period_end") is False
        ):
            event.type = EVENT_TYPE.CANCEL_SUB
            event.primary = True

        # Reactivation
        elif (
            data_object["cancel_at_period_end"] is False
            and prev.get("cancel_at_period_end") is True
        ):
            event.type = EVENT_TYPE.REACTIVATE_SUB
            event.primary = True

        # Renewal attempt (may ultimately fail or succeed)
        elif set(prev.keys()) == {
            "current_period_end",
            "current_period_start",
            "latest_invoice",
        }:
            event.type = EVENT_TYPE.RENEW_SUB
            event.primary = False

        # Subscription status changes are all non-primary events
        # The statuses `incomplete_expired` and `canceled` should not appear since those would only
        # come through the customer.subscription.deleted hook.
        # And we don't currently use `trialing` or `unpaid`.

        # Initial signup success: incomplete -> active
        # Can also occur if there's an initial failure followed by a payment repair, but there's no good way to
        # distinguish those here and it doesn't really matter anyway.
        elif prev.get("status") == "incomplete" and data_object["status"] == "active":
            event.type = EVENT_TYPE.NEW_SUB
            event.primary = False

        # Renewal failure
        elif prev.get("status") == "active" and data_object["status"] == "past_due":
            event.type = EVENT_TYPE.PAYMENT_FAIL
            event.primary = False

        # Payment fix success
        elif prev.get("status") == "past_due" and data_object["status"] == "active":
            event.type = EVENT_TYPE.PAYMENT_FIX
            event.primary = False

        else:
            event.note = f"Unrecognized customer.subscription.updated payload"

    # customer.subscription.deleted
    elif payload["type"] == "customer.subscription.deleted":
        event.type = EVENT_TYPE.DELETE_SUB
        event.primary = True

    if event.type == EVENT_TYPE.UNKNOWN:
        logger.error(
            f"StripeEvent.id={event.id} StripeEvent.payload_type={event.payload_type} Could not calculate StripeEvent.type"
        )

    event.save()
    return data_object


def _preprocess_type_info(event, data_object):
    info = {}

    if not event.primary:
        # No info necessary for non-primary events
        pass
    elif event.type in (EVENT_TYPE.NEW_SUB, EVENT_TYPE.RENEW_SUB):
        info["obj"] = "invoice"
        info["subscription_id"] = data_object["subscription"]
        info["billing_reason"] = data_object["billing_reason"]
        info["price_id"] = data_object["lines"]["data"][0]["plan"]["id"]
        info["period_end_ts"] = data_object["lines"]["data"][0]["period"]["end"]
    elif event.type == EVENT_TYPE.PAYMENT_FAIL:
        info["obj"] = "invoice"
        info["subscription_id"] = data_object["subscription"]
    elif event.type in (
        EVENT_TYPE.CANCEL_SUB,
        EVENT_TYPE.REACTIVATE_SUB,
        EVENT_TYPE.DELETE_SUB,
    ):
        info["obj"] = "subscription"
        info["subscription_id"] = data_object["id"]
        info["subscription_status"] = data_object["status"]
        info["cancel_at_period_end"] = data_object["cancel_at_period_end"]
    event.info = info
    event.save()
    return info


def _preprocess_user(event):
    # TODO
    if event.primary is False:
        return None, None

    if event.type == EVENT_TYPE.NEW_SUB:
        event.user = User.objects.get(pk=event.info["user_pk"])
    elif event.type in (
        EVENT_TYPE.RENEW_SUB,
        EVENT_TYPE.PAYMENT_FAIL,
        EVENT_TYPE.CANCEL_SUB,
        EVENT_TYPE.REACTIVATE_SUB,
    ):
        event.user = User.objects.get(
            customer__subscription_id=event.info["subscription_id"]
        )
    elif event.type == EVENT_TYPE.DELETE_SUB:
        # This will happen if we hard delete a user, so need to be prepared
        # for a user to not exist.
        event.user = User.objects.filter(
            customer__subscription_id=event.info["subscription_id"]
        ).first()
        if not event.user:
            logger.warning(
                f"StripeEvent.id={event.id} could not locate a user who may have been hard deleted."
            )
    else:
        return None, None

    event.save()
    customer = event.user.customer
    return event.user, customer


def process_stripe_event(event_id, verify_signature=True):
    """Handler for Stripe Events"""
    logger.info(f"StripeEvent.id={event_id} process_stripe_event task started")
    event = models.StripeEvent.objects.get(pk=event_id)
    customer = None
    try:
        event.status = models.StripeEvent.Status.PENDING
        event.save()

        if verify_signature and settings.STRIPE_WH_SECRET:
            services.stripe_check_webhook_signature(event)

        data_object = _preprocess_payload_type(event)
        info = _preprocess_type_info(event, data_object)
        user, customer = _preprocess_user(event)

        # Non-primary events don't need any processing
        if event.primary is False:
            event.status = models.StripeEvent.Status.IGNORED

        # Successful checkout session
        elif event.type == EVENT_TYPE.NEW_SUB:
            # Get the Plan the Customer signed up for.
            price_id = info["price_id"]
            plan = models.Plan.objects.get(price_id=price_id)

            """ TODO
            # Set customer_id if not already set.
            # Otherwise, confirm the customer_id matches the one on the User.Customer.
            if not customer.customer_id:
                customer.customer_id = session.customer.id
            elif customer.customer_id != session.customer.id:
                # This should never happen. If it does, log an error
                # and update the customer_id for the User.Customer.
                logger.error(
                    f"User.id={user.id} has a customer_id of {customer.customer_id} but the session customer_id is {session.customer.id}."
                )
                customer.customer_id = session.customer.id
            """
            customer.subscription_id = info["subscription_id"]
            customer.plan = plan
            customer.current_period_end = dt.fromtimestamp(
                info["period_end_ts"], tz=timezone.utc
            )
            customer.payment_state = models.Customer.PaymentState.OK

            event.status = models.StripeEvent.Status.PROCESSED

        # Renewal
        elif event.type == EVENT_TYPE.RENEW_SUB:
            period_end_ts = info["period_end_ts"]
            period_end = dt.fromtimestamp(period_end_ts, tz=timezone.utc)
            customer.current_period_end = period_end
            event.status = models.StripeEvent.Status.PROCESSED

        # Payment failure
        elif event.type == EVENT_TYPE.PAYMENT_FAIL:
            customer.payment_state = (
                models.Customer.PaymentState.REQUIRES_PAYMENT_METHOD
            )
            event.status = models.StripeEvent.Status.PROCESSED

        # Cancelation
        elif event.type == EVENT_TYPE.CANCEL_SUB:
            customer.payment_state = models.Customer.PaymentState.OFF
            event.status = models.StripeEvent.Status.PROCESSED

        # Reactivate a not-yet-canceled subscription
        elif event.type == EVENT_TYPE.REACTIVATE_SUB:
            customer.payment_state = models.Customer.PaymentState.OK
            event.status = models.StripeEvent.Status.PROCESSED

        # Deletion (final cancelation)
        # Either past due or user canceled intentionally
        elif event.type == EVENT_TYPE.DELETE_SUB:
            if customer:
                # It's possible there may be no Customer if the user was hard deleted.
                # Downgrade to free_default.new
                customer.payment_state = models.Customer.PaymentState.OFF
                customer.plan = models.Plan.objects.get(
                    type=models.Plan.Type.FREE_DEFAULT
                )
                customer.current_period_end = None
                customer.subscription_id = None
            event.status = models.StripeEvent.Status.PROCESSED

        else:
            event.status = models.StripeEvent.Status.IGNORED
    except Exception as e:
        logger.exception(f"StripeEvent.id={event.id} in error state")
        event.status = models.StripeEvent.Status.ERROR
        event.note = traceback.format_exc()
    finally:
        logger.debug(f"StripeEvent.id={event.id} Saving StripeEvent")
        if customer:
            customer.save()
        event.save()


try:
    from celery import shared_task

    process_stripe_event = shared_task(process_stripe_event)
except ImportError:
    pass
