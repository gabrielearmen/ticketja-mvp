from django.core.management.base import BaseCommand, CommandError

from apps.payments.reconciliation import reconcile_provider_payments


class Command(BaseCommand):
    help = "Concilia pagamentos recentes diretamente no provedor."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Quantidade máxima processada por execução.",
        )

    def handle(self, *args, **options):
        del args
        limit = options["limit"]

        if limit < 1 or limit > 1000:
            raise CommandError(
                "--limit deve estar entre 1 e 1000."
            )

        result = reconcile_provider_payments(limit=limit)

        self.stdout.write(
            self.style.SUCCESS(
                "Conciliação concluída: "
                f"{result.selected} selecionado(s), "
                f"{result.reconciled} conciliado(s), "
                f"{result.failed} falha(s)."
            )
        )

        if result.failed:
            raise CommandError(
                "Uma ou mais cobranças exigem nova tentativa ou análise."
            )
