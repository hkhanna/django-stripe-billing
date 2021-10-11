from django.urls import path

from ..views import api, webhook

app_name = "billing"
urlpatterns = [
    path(
        "stripe/webhook/", webhook.StripeWebhookAPIView.as_view(), name="stripe_webhook"
    ),
    path(
        "create-subscription/",
        api.CreateSubscriptionAPIView.as_view(),
        name="create-subscription",
    ),
    path(
        "cure-failed-card/",
        api.CureFailedCardAPIView.as_view(),
        name="cure-failed-card",
    ),
    path(
        "cancel-subscription/",
        api.CancelSubscriptionAPIView.as_view(),
        name="cancel-subscription",
    ),
    path(
        "reactivate-subscription/",
        api.ReactivateSubscriptionAPIView.as_view(),
        name="reactivate-subscription",
    ),
    path("replace-card/", api.ReplaceCardAPIView.as_view(), name="replace-card"),
]
