from django.core.management.base import (
    BaseCommand,
    CommandError,
)

from apps.orders.services import (
    expire_stale_reservations,
)


class Command(BaseCommand):
    help = (
        "Marca como expiradas as reservas que ultrapassaram "
        "o prazo de pagamento."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help=(
                "Quantidade máxima de pedidos processados "
                "por transação."
            ),
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]

        if batch_size <= 0:
            raise CommandError(
                "--batch-size deve ser maior que zero."
            )

        total_expired = 0

        while True:
            expired_count = expire_stale_reservations(
                batch_size=batch_size,
            )

            total_expired += expired_count

            if expired_count < batch_size:
                break

        self.stdout.write(
            self.style.SUCCESS(
                f"{total_expired} reserva(s) expirada(s)."
            )
        )