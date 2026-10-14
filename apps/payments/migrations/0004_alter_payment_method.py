from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0003_remove_payment_pay_status_valid_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="payment",
            name="pay_method_valid",
        ),
        migrations.AlterField(
            model_name="payment",
            name="method",
            field=models.CharField(
                choices=[
                    ("gratuito", "Gratuito"),
                    ("checkout_pro", "Checkout Pro"),
                    ("pix", "PIX"),
                    ("boleto", "Boleto"),
                    ("cartao", "Cartão"),
                ],
                max_length=20,
                verbose_name="meio de pagamento",
            ),
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    method__in=[
                        "gratuito",
                        "checkout_pro",
                        "pix",
                        "boleto",
                        "cartao",
                    ]
                ),
                name="pay_method_valid",
            ),
        ),
    ]
