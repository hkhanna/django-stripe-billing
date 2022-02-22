import json
import logging
from urllib.parse import urlparse
from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import get_user_model
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

import stripe

from . import models, settings, services, tasks

User = get_user_model()
logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook_view(request):
    try:
        payload = json.loads(request.body)
    except json.decoder.JSONDecodeError as e:
        return JsonResponse({"detail": "Invalid payload"}, status=400)

    if type(payload) != dict or "type" not in payload or "id" not in payload:
        return JsonResponse({"detail": "Invalid payload"}, status=400)

    headers = {}
    for key in request.headers:
        value = request.headers[key]
        if isinstance(value, str):
            headers[key] = value

    event = models.StripeEvent.objects.create(
        event_id=payload["id"],
        payload_type=payload["type"],
        body=request.body.decode("utf-8"),
        headers=headers,
        status=models.StripeEvent.Status.NEW,
    )
    logger.info(f"StripeEvent.id={event.id} StripeEvent.type={event.type} received")
    if hasattr(tasks, "shared_task"):
        tasks.process_stripe_event.delay(event.id)
    else:
        tasks.process_stripe_event(event.id)

    return JsonResponse({"detail": "Created"}, status=201)


class CreateCheckoutSessionView(LoginRequiredMixin, View):
    def post(self, request, slug, pk):
        # Redirect to cancel url if no price id or if price id not in Plan
        plan = models.Plan.objects.filter(
            id=pk,
            type__in=[models.Plan.Type.PAID_PUBLIC, models.Plan.Type.PAID_PRIVATE],
        ).first()
        if not plan:
            logger.error(f"In CreateCheckoutSessionView, invalid plan id={pk}")
            messages.error(request, "Invalid billing plan.")
            return redirect(settings.CHECKOUT_CANCEL_URL)

        # Verify they have the correct name of the plan
        if plan.slug != slug:
            logger.error(
                f"In CreateCheckoutSessionView, invalid slug {slug} for plan id={pk}"
            )
            messages.error(request, "Invalid billing plan.")
            return redirect(settings.CHECKOUT_CANCEL_URL)

        # User must not have an active billing plan
        # If a user is trying to switch between paid plans, this is the wrong endpoint.
        customer = request.user.customer
        if customer.state not in (
            "free_default.new",
            "free_private.expired",
        ):
            logger.error(
                f"User.id={request.user.id} attempted to create a checkout session while having an active billing plan."
            )
            messages.error(request, "User already has a subscription.")
            return redirect(settings.CHECKOUT_CANCEL_URL)

        success_url = reverse("billing:checkout_success")
        success_url = f"{request.scheme}://{request.get_host()}{success_url}"
        success_url += "?session_id={CHECKOUT_SESSION_ID}"

        # If it's not an absolute URL, make it one.
        cancel_url = settings.CHECKOUT_CANCEL_URL
        if not urlparse(str(cancel_url)).netloc:
            cancel_url = f"{request.scheme}://{request.get_host()}{cancel_url}"

        # Send either customer_id or customer_email (Stripe does not allow both)
        if customer.customer_id:
            customer_email = None
        else:
            customer_email = request.user.email

        # Create Session if all is well.
        session = stripe.checkout.Session.create(
            success_url=success_url,
            cancel_url=cancel_url,
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": plan.price_id, "quantity": 1}],
            client_reference_id=request.user.pk,
            # Only one of customer or customer_email may be provided
            customer=customer.customer_id,
            customer_email=customer_email,
        )
        return redirect(session.url, permanent=False)


class CheckoutSuccessView(LoginRequiredMixin, View):
    def get(self, request):
        session_id = request.GET.get("session_id")
        if not session_id:
            messages.error(request, "No session id provided.")
            return redirect(settings.CHECKOUT_CANCEL_URL)

        try:
            session = stripe.checkout.Session.retrieve(session_id, expand=["customer"])
        except stripe.error.InvalidRequestError as e:
            messages.error(request, "Invalid session id provided.")
            return redirect(settings.CHECKOUT_CANCEL_URL)

        # Gut check the client_reference_id is correct and customer id is expected.
        if str(session.client_reference_id) != str(request.user.pk):
            msg = f"User.id={request.user.id} does not match session.client_reference_id={session.client_reference_id}"
            logger.error(msg)
            messages.error(
                request,
                "There was a problem processing your request. Please try again later.",
            )
            return redirect(settings.CHECKOUT_CANCEL_URL)

        customer = request.user.customer
        if customer.customer_id and (session.customer.id != customer.customer_id):
            msg = f"customer_id={customer.customer_id} on user.customer does not match session.customer.id={session.customer.id}"
            logger.error(msg)
            messages.error(
                request,
                "There was a problem processing your request. Please try again later.",
            )
            return redirect(settings.CHECKOUT_CANCEL_URL)

        # If users change their email on the checkout page, this will change it back
        # on the Stripe Customer.
        services.stripe_customer_sync_metadata_email(request.user, session.customer.id)
        messages.success(request, "Successfully subscribed!")

        return redirect(settings.CHECKOUT_SUCCESS_URL)


class CreatePortalView(LoginRequiredMixin, View):
    def post(self, request):

        # If it's not an absolute URL, make it one.
        return_url = request.POST.get("return_url", settings.PORTAL_RETURN_URL)
        if not urlparse(str(return_url)).netloc:
            return_url = f"{request.scheme}://{request.get_host()}{return_url}"

        # User should be able to access the Portal.
        customer = request.user.customer
        if customer.state not in (
            "free_default.past_due.requires_payment_method",
            "paid.past_due.requires_payment_method",
            "paid.paying",
            "paid.will_cancel",
        ):
            logger.error(
                f"User.id={request.user.id} attempted to create a portal session with an inappropriate state."
            )
            messages.error(request, "User does not have access.")
            return redirect(return_url)

        customer_id = request.user.customer.customer_id

        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )

        return redirect(session.url, permanent=False)
