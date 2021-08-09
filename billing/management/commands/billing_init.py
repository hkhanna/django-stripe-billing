from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from billing import models


class Command(BaseCommand):
    help = "Initialize billing app"

    def handle(self, *args, **options):
        """Creates a free_default plan. Also grabs all existing Users and just saves them,
        triggering the Customer creation signal."""
        models.Plan.objects.get_or_create(
            type=models.Plan.Type.FREE_DEFAULT,
            defaults={"name": "Default (Free)", "display_price": 0},
        )

        User = get_user_model()
        for user in User.objects.all():
            user.save()
        print("Initialization complete.")
