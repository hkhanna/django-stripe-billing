from django.urls import path, include

from . import views

urlpatterns = [
    path("billing/", include("billing.urls")),
    path("profile/", views.ProfileView.as_view(), name="profile"),
]
