from django import forms
from django.core.exceptions import ValidationError

from apps.registrations.validators import validate_cpf


class PaymentPayerForm(forms.Form):
    """Dados estritamente necessários para emitir a cobrança PIX."""

    full_name = forms.CharField(
        label="Nome completo do pagador",
        max_length=200,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "name",
                "class": "form-control",
            }
        ),
    )
    document_number = forms.CharField(
        label="CPF do pagador",
        max_length=18,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "inputmode": "numeric",
                "class": "form-control",
                "placeholder": "000.000.000-00",
            }
        ),
    )

    def clean_full_name(self):
        normalized = " ".join(
            self.cleaned_data["full_name"].split()
        )

        if len(normalized.split()) < 2:
            raise ValidationError(
                "Informe o nome e o sobrenome do pagador."
            )

        return normalized

    def clean_document_number(self):
        return validate_cpf(
            self.cleaned_data["document_number"]
        )

    def payer_payload(self):
        full_name = self.cleaned_data["full_name"]
        first_name, last_name = full_name.split(" ", 1)

        return {
            "first_name": first_name,
            "last_name": last_name,
            "document_type": "CPF",
            "document_number": self.cleaned_data[
                "document_number"
            ],
        }


class HostedCheckoutConfirmationForm(forms.Form):
    """
    Confirmação protegida por CSRF antes do redirecionamento.

    O Mercado Pago coleta os dados necessários ao meio escolhido;
    o TicketJá não recebe nem armazena dados de cartão.
    """
