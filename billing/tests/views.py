from django.views.generic import TemplateView
from .. import mixins


class ProfileView(mixins.BillingMixin, TemplateView):
    template_name = "profile.html"
