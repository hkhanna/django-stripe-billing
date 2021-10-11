import json
import logging
from django.views.generic import View
from django.http import JsonResponse

from .. import models, tasks

logger = logging.getLogger(__name__)


class StripeWebhookAPIView(View):
    def post(self, request):
        try:
            payload = json.loads(request.body)
        except json.decoder.JSONDecodeError as e:
            return JsonResponse({"detail": "Invalid payload"}, status=400)

        if type(payload) != dict or "type" not in payload or "id" not in payload:
            return JsonResponse({"detail": "Invalid payload"}, status=400)

        headers = {}
        for key in request.headers:
            value = request.headers[key]
            if isinstance(value, str):
                headers[key] = value

        event = models.StripeEvent.objects.create(
            event_id=payload["id"],
            type=payload["type"],
            payload=payload,
            headers=headers,
            status=models.StripeEvent.Status.NEW,
        )
        logger.info(f"StripeEvent.id={event.id} StripeEvent.type={event.type} received")
        if hasattr(tasks, "shared_task"):
            tasks.process_stripe_event.delay(event.id)
        else:
            tasks.process_stripe_event(event.id)

        return JsonResponse({"detail": "Created"}, status=201)
