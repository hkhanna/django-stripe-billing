from django.urls import path

from ..views import checkout, webhook

app_name = "billing_checkout"
urlpatterns = [
    path(
        "create-checkout-session/",
        checkout.CreateCheckoutSessionView.as_view(),
        name="create_checkout_session",
    ),
    path(
        "checkout-success/",
        checkout.CheckoutSuccessView.as_view(),
        name="checkout_success",
    ),
    path(
        "create-portal-session",
        checkout.CreatePortalView.as_view(),
        name="create_portal_session",
    ),
    path("stripe/webhook/", webhook.stripe_webhook_view, name="stripe_webhook"),
]
