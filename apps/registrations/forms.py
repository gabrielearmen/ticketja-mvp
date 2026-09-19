from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseModelFormSet
from django.forms import modelformset_factory

from .models import Registration


class RegistrationParticipantForm(forms.ModelForm):
    class Meta:
        model = Registration

        fields = (
            "full_name",
            "document_type",
            "document_number",
            "birth_date",
            "email",
            "phone",
            "emergency_contact_name",
            "emergency_contact_phone",
        )

        labels = {
            "full_name": "Nome completo",
            "document_type": "Tipo de documento",
            "document_number": "Número do documento",
            "birth_date": "Data de nascimento",
            "email": "E-mail do participante",
            "phone": "Telefone do participante",
            "emergency_contact_name": (
                "Nome do contato de emergência"
            ),
            "emergency_contact_phone": (
                "Telefone de emergência"
            ),
        }

        help_texts = {
            "email": (
                "Opcional. O comprovante principal será enviado "
                "à conta do comprador."
            ),
            "phone": "Opcional.",
            "emergency_contact_name": (
                "Preencha os dois campos de emergência ou "
                "deixe ambos vazios."
            ),
        }

        widgets = {
            "full_name": forms.TextInput(
                attrs={
                    "autocomplete": "name",
                }
            ),
            "document_type": forms.Select(),
            "document_number": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "inputmode": "text",
                }
            ),
            "birth_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={
                    "type": "date",
                    "autocomplete": "bday",
                },
            ),
            "email": forms.EmailInput(
                attrs={
                    "autocomplete": "email",
                }
            ),
            "phone": forms.TextInput(
                attrs={
                    "autocomplete": "tel",
                    "inputmode": "tel",
                }
            ),
            "emergency_contact_name": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                }
            ),
            "emergency_contact_phone": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "inputmode": "tel",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["full_name"].required = True
        self.fields["document_type"].required = True
        self.fields["document_number"].required = True
        self.fields["birth_date"].required = True

        self.fields["birth_date"].input_formats = (
            "%Y-%m-%d",
        )

        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class BaseRegistrationParticipantFormSet(
    BaseModelFormSet
):
    """
    Impede que o comprador remova, duplique ou substitua IDs
    de participantes no POST.
    """

    def __init__(self, *args, **kwargs):
        queryset = kwargs.get("queryset")

        self.expected_ids = set()

        if queryset is not None:
            self.expected_ids = {
                str(registration_id)
                for registration_id in (
                    queryset.values_list(
                        "id",
                        flat=True,
                    )
                )
            }

        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()

        if any(self.errors):
            return

        submitted_ids = []

        for form in self.forms:
            registration = form.cleaned_data.get("id")

            if registration is None:
                raise ValidationError(
                    "A lista de participantes é inválida."
                )

            submitted_ids.append(
                str(registration.id)
            )

        if len(submitted_ids) != len(set(submitted_ids)):
            raise ValidationError(
                "Um participante foi enviado mais de uma vez."
            )

        if set(submitted_ids) != self.expected_ids:
            raise ValidationError(
                "A lista de participantes foi alterada."
            )


RegistrationParticipantFormSet = modelformset_factory(
    Registration,
    form=RegistrationParticipantForm,
    formset=BaseRegistrationParticipantFormSet,
    extra=0,
    can_delete=False,
)