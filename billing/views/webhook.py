import json
import logging
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

from .. import models, tasks

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook_view(request):
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
        payload_type=payload["type"],
        body=request.body.decode("utf-8"),
        headers=headers,
        status=models.StripeEvent.Status.NEW,
    )
    logger.info(f"StripeEvent.id={event.id} StripeEvent.type={event.type} received")
    if hasattr(tasks, "shared_task"):
        tasks.process_stripe_event.delay(event.id)
    else:
        tasks.process_stripe_event(event.id)

    return JsonResponse({"detail": "Created"}, status=201)
