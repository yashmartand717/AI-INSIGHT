from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from gyanbuddy_insights.models import EmailDelivery, DeliveryResolution


class Command(BaseCommand):
    help = "Reconcile an uncertain/blocked email after checking provider logs. Retries can duplicate email if the original was accepted."

    def add_arguments(self, parser):
        parser.add_argument("delivery_id")
        parser.add_argument("--action", choices=["mark-sent", "retry"], required=True)
        parser.add_argument("--operator", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--confirmed-not-sent", action="store_true")

    def handle(self, delivery_id, action, operator, reason, confirmed_not_sent, **options):
        if not operator.strip() or not reason.strip():
            raise CommandError("An operator and reconciliation reason are required")
        with transaction.atomic():
            row = EmailDelivery.objects.select_for_update().get(pk=delivery_id)
            if row.state not in ("uncertain", "blocked"):
                raise CommandError("Only uncertain or blocked deliveries can be reconciled")
            if action == "retry" and not confirmed_not_sent:
                raise CommandError("Check provider logs first, then use --confirmed-not-sent if no email was accepted")
            DeliveryResolution.objects.create(delivery=row, action=action, operator=operator, reason=reason)
            row.state = "pending" if action == "retry" else "sent"
            row.sent_at = None if action == "retry" else timezone.now()
            row.error_code = ""
            row.claim = None
            row.locked_until = None
            row.save()
        self.stdout.write(f"Delivery marked {row.state}; reconciliation logged.")
