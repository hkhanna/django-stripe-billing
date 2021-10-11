import logging
from urllib.parse import urlparse
from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import redirect
from django.contrib import messages
import stripe

from .. import models, settings

User = get_user_model()
logger = logging.getLogger(__name__)

for setting in ("CHECKOUT_SUCCESS_URL", "CHECKOUT_CANCEL_URL"):
    missing = []
    if getattr(settings, setting) is None:
        missing.append(setting)
    if len(missing) > 0:
        missing = ", ".join(missing)
        raise ImproperlyConfigured(
            f"Checkout views need {missing} settings configured."
        )


class CreateCheckoutSessionView(LoginRequiredMixin, View):
    def post(self, request):
        # Redirect to cancel url if no price id or if price id not in Plan
        plan = models.Plan.objects.filter(
            id=request.POST.get("plan_id", None), type=models.Plan.Type.PAID_PUBLIC
        ).first()
        if not plan:
            logger.error(
                f"In CreateCheckoutSessionView, invalid plan_id provided: {request.POST.get('plan_id', None)}"
            )
            messages.error(request, "Invalid billing plan.")
            return redirect(settings.CHECKOUT_CANCEL_URL)

        # User must not have an active billing plan
        # If a user is trying to switch between paid plans, this is the wrong endpoint.
        customer = request.user.customer
        if customer.state not in ("free_default.new", "free_default.canceled"):
            logger.error(
                f"User.id={request.user.id} attempted to create a checkout session while having an active billing plan."
            )
            messages.error(request, "User already has a subscription.")
            return redirect(settings.CHECKOUT_CANCEL_URL)

        # If it's not an absolute URL, make it one.
        success_url = settings.CHECKOUT_SUCCESS_URL
        if not urlparse(success_url).netloc:
            success_url = f"https://{request.get_host()}{success_url}"
        success_url += "?session_id={CHECKOUT_SESSION_ID}"

        cancel_url = settings.CHECKOUT_CANCEL_URL
        if not urlparse(cancel_url).netloc:
            cancel_url = f"https://{request.get_host()}{cancel_url}"

        # Create Session if all is well.
        session = stripe.checkout.Session.create(
            success_url=success_url,
            cancel_url=cancel_url,
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": plan.price_id, "quantity": 1}],
            customer=customer.customer_id,  # TODO: Test by hand that this is properly set.
            customer_email=request.user.email,  # TODO: If users change their email on the checkout page, how to handle? What if this doesn't match what's already on the Stripe customer?
            client_reference_id=request.user.pk,
        )
        return redirect(session.url, permanent=False)


class CheckoutSuccessView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect(settings.CHECKOUT_SUCCESS_URL)
