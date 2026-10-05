from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from gyanbuddy_insights.models import Batch


class Command(BaseCommand):
    help = "Retry failed generation after fixing configuration or provider errors. Does not send email."

    def add_arguments(self, parser):
        parser.add_argument("batch_id")

    def handle(self, batch_id, **options):
        with transaction.atomic():
            batch = Batch.objects.select_for_update().get(pk=batch_id)
            if batch.published_at:
                raise CommandError("Published reports are immutable. Submit a new revision event instead.")
            count = batch.reports.filter(state="failed").update(state="queued", attempts=0, available_at=None, locked_until=None, claim=None, error_code="")
        self.stdout.write(f"Queued {count} failed reports. The dispatcher will pick them up.")
