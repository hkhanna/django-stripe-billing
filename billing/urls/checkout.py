from django.urls import path

from ..views import checkout

app_name = "billing"
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
]
