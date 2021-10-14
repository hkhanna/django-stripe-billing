from django.urls import path

from . import views

app_name = "billing"
urlpatterns = [
    path(
        "create-checkout-session/",
        views.CreateCheckoutSessionView.as_view(),
        name="create_checkout_session",
    ),
    path(
        "checkout-success/",
        views.CheckoutSuccessView.as_view(),
        name="checkout_success",
    ),
    path(
        "create-portal-session",
        views.CreatePortalView.as_view(),
        name="create_portal_session",
    ),
    path("stripe/webhook/", views.stripe_webhook_view, name="stripe_webhook"),
]
