from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)


class EmailAuthenticationForm(AuthenticationForm):
    """
    Formulário público de autenticação por e-mail.
    """

    username = forms.EmailField(
        label="E-mail",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "placeholder": "voce@exemplo.com",
                "inputmode": "email",
            }
        ),
    )

    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "placeholder": "Digite sua senha",
            }
        ),
    )

    error_messages = {
        "invalid_login": (
            "Não foi possível entrar com os dados informados. "
            "Confira o e-mail e a senha."
        ),
        "inactive": (
            "Não foi possível entrar com os dados informados. "
            "Confira o e-mail e a senha."
        ),
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().casefold()


class AccountRegistrationForm(UserCreationForm):
    """
    Cadastra uma conta de acesso ainda não confirmada.
    """

    first_name = forms.CharField(
        label="Nome",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "given-name",
                "placeholder": "Seu nome",
            }
        ),
    )

    last_name = forms.CharField(
        label="Sobrenome",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "family-name",
                "placeholder": "Seu sobrenome",
            }
        ),
    )

    email = forms.EmailField(
        label="E-mail",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "placeholder": "voce@exemplo.com",
                "inputmode": "email",
            }
        ),
    )

    password1 = forms.CharField(
        label="Senha",
        strip=False,
        help_text=(
            "Use uma senha longa, difícil de adivinhar "
            "e diferente de seus dados pessoais."
        ),
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "Crie uma senha segura",
            }
        ),
    )

    password2 = forms.CharField(
        label="Confirme a senha",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "Digite a senha novamente",
            }
        ),
    )

    class Meta:
        model = get_user_model()
        fields = (
            "first_name",
            "last_name",
            "email",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().casefold()
        user_model = get_user_model()

        if user_model.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Não foi possível concluir o cadastro com este e-mail."
            )

        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.is_active = False

        if commit:
            user.save()

        return user

class AccountPasswordResetForm(PasswordResetForm):
    """
    Solicita recuperação sem revelar se a conta existe.
    """

    email = forms.EmailField(
        label="E-mail",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "placeholder": "voce@exemplo.com",
                "inputmode": "email",
            }
        ),
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().casefold()


class AccountSetPasswordForm(SetPasswordForm):
    """
    Valida e define a nova senha da conta.
    """

    new_password1 = forms.CharField(
        label="Nova senha",
        strip=False,
        help_text=(
            "Use uma senha longa, difícil de adivinhar "
            "e diferente de seus dados pessoais."
        ),
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "Crie uma nova senha",
            }
        ),
    )

    new_password2 = forms.CharField(
        label="Confirme a nova senha",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "Digite a nova senha novamente",
            }
        ),
    )