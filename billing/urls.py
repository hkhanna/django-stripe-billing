from django.urls import path

from . import views

app_name = "billing"
urlpatterns = [
    path(
        "create-subscription/",
        views.CreateSubscriptionAPIView.as_view(),
        name="create-subscription",
    ),
    path(
        "cure-failed-card/",
        views.CureFailedCardAPIView.as_view(),
        name="cure-failed-card",
    ),
    path(
        "cancel-subscription/",
        views.CancelSubscriptionAPIView.as_view(),
        name="cancel-subscription",
    ),
    path(
        "reactivate-subscription/",
        views.ReactivateSubscriptionAPIView.as_view(),
        name="reactivate-subscription",
    ),
    path("replace-card/", views.ReplaceCardAPIView.as_view(), name="replace-card"),
    path(
        "stripe/webhook/", views.StripeWebhookAPIView.as_view(), name="stripe_webhook"
    ),
]
