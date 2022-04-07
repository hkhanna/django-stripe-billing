import json
from datetime import datetime as dt
import logging
from re import T
import traceback
import stripe

from django.utils import timezone

from . import models, settings, services

try:
    from celery.utils.log import get_task_logger

    logger = get_task_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


def link_user_to_event(event, customer_id):
    """When an event comes in, try to match on the customer_id. If it can't, try to
    match on the email."""

    customer = models.Customer.objects.filter(customer_id=customer_id).first()
    if not customer:
        # Couldn't find the user via customer_id, so try matching on email.
        stripe_customer = stripe.Customer.retrieve(customer_id)
        customer = models.Customer.objects.get(user__email=stripe_customer.email)

    event.user = customer.user
    event.save()

    # Set customer_id if not already set.
    if not customer.customer_id:
        customer.customer_id = customer_id
        customer.save()

    return customer


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

        payload = json.loads(event.body)
        data_object = payload["data"]["object"]

        # If the payload_type is customer.subscription.*,
        # create or update the appropriate StripeSubscription.
        if event.payload_type.startswith("customer.subcription."):
            # Extract the relevant attributes from the event payload
            id = data_object["id"]
            customer_id = data_object["customer"]
            current_period_end = data_object["current_period_end"]
            price_id = data_object["items"]["data"][0]["price"]["id"]
            cancel_at_period_end = data_object["cancel_at_period_end"]
            created = data_object["created"]
            status = data_object["status"]

            # Create or update StripeSubscription
            subscription = models.StripeSubscription.objects.filter(id=id).first()
            if not subscription:
                subscription = models.StripeSubscription(id=id)

            subscription.current_period_end = dt.fromtimestamp(
                current_period_end, tz=timezone.utc
            )
            subscription.price_id = price_id
            subscription.cancel_at_period_end = cancel_at_period_end
            subscription.created = dt.fromtimestamp(created, tz=timezone.utc)
            subscription.status = status
            subscription.save()

            # Link Customer/User to Event and StripeSubscription
            try:
                user = link_user_to_event(event, customer_id)
                customer = user.customer
            except models.Customer.DoesNotExist:
                # If a user is being hard deleted so the subscription is immediately canceled,
                # this will happen, so we need to be ok with a user not existing in that case.
                if subscription.status == "canceled":
                    logger.warning(
                        f"StripeEvent.id={event.id} could not locate a user who may have been hard deleted."
                    )
                    event.status = models.StripeEvent.Status.PROCESSED
                    event.save()
                    return
            else:
                # Otherwise, it's a genuine error since we can't locate the user.
                raise

            if not subscription.customer:
                subscription.customer = customer
                subscription.save()
            else:
                # Integrity check: if the StripeSubscription already has a customer, it should match
                # the incoming subscription update.
                assert subscription.customer == customer

            # Sync the Customer with the StripeSubscription.

            # If a Customer somehow erroneously has multiple StripeSubscriptions,
            # prefer the active one, followed by past_due. If there are still multiple,
            # take the latest created one. That's what this equality check does because
            # of how customer.subscription the property is defined.
            if subscription.customer == customer.subscription:
                # Sync the plan and end date if the subscription is active.
                if subscription.status == models.StripeSubscription.Status.ACTIVE:
                    plan = models.Plan.objects.get(price_id=subscription.price_id)
                    customer.plan = plan
                    customer.current_period_end = subscription.current_period_end

                # If the subscription is finally deleted, downgrade the customer to free_default and
                # zero-out the current_period_end. (TODO test)
                if subscription.status == models.StripeSubscription.Status.CANCELED:
                    plan = models.Plan.objects.get(type=models.Plan.Type.FREE_DEFAULT)
                    customer.plan = plan
                    customer.current_period_end = None

            # TODO retry when payment is fixed
            # TODO link event to StripeSubscription and display in admin
            # TODO move replay button to admin action
            # TODO test every StripeSubscription state

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
