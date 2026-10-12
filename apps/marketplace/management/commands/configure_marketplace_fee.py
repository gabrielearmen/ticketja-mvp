from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.marketplace.models import FeeBearer, MarketplaceFeePolicy


class Command(BaseCommand):
    help = "Ativa uma política versionada de comissão do TicketJá."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--percentage", required=True)
        parser.add_argument(
            "--fixed-per-ticket",
            default="0.00",
            help=(
                "Mantido por compatibilidade; a política atual exige 0.00."
            ),
        )
        parser.add_argument(
            "--fee-bearer",
            choices=FeeBearer.values,
            default=FeeBearer.BUYER,
        )
        parser.add_argument("--minimum-fee")
        parser.add_argument("--maximum-fee")

    def _decimal(self, value, option_name, *, nullable=False):
        if nullable and value in {None, ""}:
            return None

        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise CommandError(
                f"{option_name} deve ser um valor decimal válido."
            ) from error

    @transaction.atomic
    def handle(self, *args, **options):
        del args
        percentage = self._decimal(
            options["percentage"],
            "--percentage",
        )
        fixed_amount = self._decimal(
            options["fixed_per_ticket"],
            "--fixed-per-ticket",
        )
        minimum_fee = self._decimal(
            options["minimum_fee"],
            "--minimum-fee",
            nullable=True,
        )
        maximum_fee = self._decimal(
            options["maximum_fee"],
            "--maximum-fee",
            nullable=True,
        )
        reference_time = timezone.now()

        if fixed_amount != Decimal("0.00"):
            raise CommandError(
                "A política comercial atual não possui cobrança fixa "
                "por ingresso. Use --fixed-per-ticket 0.00."
            )

        if minimum_fee is not None or maximum_fee is not None:
            raise CommandError(
                "A política comercial atual não possui taxa mínima ou "
                "máxima. Omita --minimum-fee e --maximum-fee."
            )

        current_policies = list(
            MarketplaceFeePolicy.objects
            .select_for_update()
            .filter(is_active=True)
        )

        for current_policy in current_policies:
            current_policy.is_active = False
            current_policy.effective_until = reference_time
            current_policy.save(
                update_fields=(
                    "is_active",
                    "effective_until",
                    "updated_at",
                )
            )

        policy = MarketplaceFeePolicy(
            name=options["name"].strip(),
            fee_bearer=options["fee_bearer"],
            percentage_rate=percentage,
            fixed_amount_per_ticket=fixed_amount,
            minimum_fee=minimum_fee,
            maximum_fee=maximum_fee,
            effective_from=reference_time,
            is_active=True,
        )

        try:
            policy.full_clean()
        except ValidationError as error:
            raise CommandError(
                "; ".join(error.messages)
            ) from error

        policy.save(force_insert=True)

        self.stdout.write(
            self.style.SUCCESS(
                f'Política "{policy.name}" ativada com sucesso.'
            )
        )
