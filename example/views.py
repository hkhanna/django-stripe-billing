from datetime import datetime as dt
from django.shortcuts import render
from django.contrib.auth import get_user_model
from django.views.generic import RedirectView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from billing import models

User = get_user_model()


class IndexView(RedirectView):
    pattern_name = "account_login"


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "example/profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["plan_id"] = (
            models.Plan.objects.filter(type=models.Plan.Type.PAID_PUBLIC).first().id
        )
        return context
