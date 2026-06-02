"""Fire-and-forget SQS notification publishing.

Swallows all exceptions so that a failed publish never rolls back a confirmed
booking.  Errors are logged for CloudWatch alerting.
"""
import json

from app.core.logging import log


async def publish_booking_confirmation(appointment_id: str) -> None:
    """Publish a BOOKING_CONFIRMATION event to the configured SQS queue.

    No-op when SQS_BOOKING_QUEUE_URL is not set (local / test environment).
    """
    from app.core.config import settings  # local import avoids circular deps at module load

    queue_url = settings.SQS_BOOKING_QUEUE_URL
    if not queue_url:
        return

    try:
        import aioboto3  # type: ignore[import]

        session = aioboto3.Session()
        async with session.client("sqs", region_name=settings.AWS_REGION) as sqs:
            await sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(
                    {"type": "BOOKING_CONFIRMATION", "appointmentId": appointment_id}
                ),
            )
    except Exception:
        log.exception(
            "sqs_publish_failed",
            appointment_id=appointment_id,
            queue_url=queue_url,
        )
