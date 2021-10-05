import logging
from datetime import datetime as dt
from django.shortcuts import render
from django.contrib.auth import get_user_model
from django.views.generic import RedirectView, TemplateView

from . import models

User = get_user_model()


class IndexView(RedirectView):
    pattern_name = "account_login"


class ProfileView(TemplateView):
    template_name = "example/profile.html"
