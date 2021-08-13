import logging
from datetime import datetime as dt
from django.shortcuts import render
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
import stripe

from . import serializers, models, services, tasks

User = get_user_model()
logger = logging.getLogger(__name__)


class CreateSubscriptionAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = serializers.CreateSubscriptionSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer

        # If the customer doesn't have a stripe customer_id, check if there's a matching customer on Stripe.
        # If not, create a Stripe customer now.
        if not customer.customer_id:
            existing = services.stripe_get_customer(request.user)
            if existing:
                customer.customer_id = existing.id
                customer.save()
                services.check_update_stripe_customer_metadata(request.user, existing)
            else:
                stripe_customer = services.stripe_create_customer(request.user)
                customer.customer_id = stripe_customer.id
                customer.save()

        try:
            subscription, payment_method = services.stripe_create_subscription(
                customer_id=customer.customer_id,
                payment_method_id=serializer.validated_data["payment_method_id"],
                price_id=serializer.plan.price_id,
            )
        except stripe.error.CardError as e:
            raise ValidationError(e.error.message)

        customer.subscription_id = subscription.id
        customer.plan = serializer.plan
        cc_info = payment_method.card
        customer.cc_info = {
            k: cc_info[k]
            for k in cc_info
            if k in ("brand", "last4", "exp_month", "exp_year")
        }
        if subscription.status == "active":
            customer.current_period_end = dt.fromtimestamp(
                subscription.current_period_end, tz=timezone.utc
            )
            customer.payment_state = models.Customer.PaymentState.OK
            customer.save()
            return Response(status=201)
        else:
            logger.info(
                f"User.id={request.user.id} payment failed in CreateSubscriptionAPIView"
            )
            customer.current_period_end = None
            customer.payment_state = (
                models.Customer.PaymentState.REQUIRES_PAYMENT_METHOD
            )
            customer.save()
            raise ValidationError(
                "Payment could not be processed. Please try again or use another card."
            )


class CureFailedCardAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if "payment_method_id" not in request.data:
            raise ValidationError("No payment_method_id provided.")

        customer = request.user.customer
        # Make sure there is a subscription and the payment state is set to PAYMENT_REQUIRES_PAYMENT_METHOD
        if (
            customer.subscription_id
            and customer.payment_state
            == models.Customer.PaymentState.REQUIRES_PAYMENT_METHOD
        ):
            try:
                payment_method = services.stripe_replace_card(
                    customer.customer_id,
                    customer.subscription_id,
                    request.data["payment_method_id"],
                )
                cc_info = payment_method.card
                customer.cc_info = {
                    k: cc_info[k]
                    for k in cc_info
                    if k in ("brand", "last4", "exp_month", "exp_year")
                }
                customer.save()
                invoice = services.stripe_retry_latest_invoice(customer.customer_id)
                if invoice["status"] == "paid":
                    customer.current_period_end = dt.fromtimestamp(
                        invoice["lines"]["data"][0]["period"]["end"], tz=timezone.utc
                    )
                    customer.payment_state = models.Customer.PaymentState.OK
                    customer.save()
            except stripe.error.CardError as e:
                # N.B. stripe.Invoice.pay raises a CardError if the payment doesn't go through.
                raise ValidationError(e.error.message)
        else:
            raise ValidationError("You cannot cure a failed payment for this customer.")

        return Response(status=201)


class CancelSubscriptionAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.user.customer.payment_state == models.Customer.PaymentState.OFF:
            raise ValidationError("No active subscription to cancel.")

        services.stripe_cancel_subscription(request.user.customer.subscription_id)
        request.user.customer.payment_state = models.Customer.PaymentState.OFF
        request.user.customer.save()
        return Response(status=201)


class ReactivateSubscriptionAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        customer = request.user.customer
        # Make sure there is an active subscription that will be canceled at the end of the period
        if customer.state == "paid.will_cancel":
            services.stripe_reactivate_subscription(customer.subscription_id)
            request.user.customer.payment_state = models.Customer.PaymentState.OK
            request.user.customer.save()
            return Response(status=201)
        else:
            raise ValidationError("You cannot reactivate this subscription.")


class ReplaceCardAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if "payment_method_id" not in request.data:
            raise ValidationError("No payment_method_id provided.")

        customer = request.user.customer
        # Make sure there is an active subscription
        if (
            customer.subscription_id
            and customer.payment_state != models.Customer.PaymentState.OFF
        ):
            try:
                payment_method = services.stripe_replace_card(
                    customer.customer_id,
                    customer.subscription_id,
                    request.data["payment_method_id"],
                )
            except stripe.error.CardError as e:
                raise ValidationError(e.error.message)
            cc_info = payment_method.card
            request.user.customer.cc_info = {
                k: cc_info[k]
                for k in cc_info
                if k in ("brand", "last4", "exp_month", "exp_year")
            }
            request.user.customer.save()
            return Response(status=201)
        else:
            raise ValidationError("You cannot replace card for this customer.")


class StripeWebhookAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        payload = request.data

        if type(payload) != dict or "type" not in payload or "id" not in payload:
            raise ValidationError("Invalid payload")

        headers = {}
        for key in request.headers:
            value = request.headers[key]
            if isinstance(value, str):
                headers[key] = value

        event = models.StripeEvent.objects.create(
            event_id=payload["id"],
            type=payload["type"],
            payload=payload,
            headers=headers,
            status=models.StripeEvent.Status.NEW,
        )
        logger.info(f"StripeEvent.id={event.id} StripeEvent.type={event.type} received")
        if hasattr(tasks, "shared_task"):
            tasks.process_stripe_event.delay(event.id)
        else:
            tasks.process_stripe_event(event.id)

        return Response(status=201)
