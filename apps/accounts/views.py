from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import get_user_model
from apps.organizations.selectors import (
    resolve_active_organizer_membership,
)
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.generic import FormView, TemplateView

from .forms import (
    AccountPasswordResetForm,
    AccountRegistrationForm,
    AccountSetPasswordForm,
    EmailAuthenticationForm,
)
from .services import send_account_activation_email
from .tokens import account_activation_token


class AccountLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return self.get_redirect_url() or reverse_lazy("core:home")


class AccountLogoutView(LogoutView):
    next_page = reverse_lazy("core:home")


class AccountRegistrationView(FormView):
    template_name = "accounts/register.html"
    form_class = AccountRegistrationForm
    success_url = reverse_lazy("accounts:registration_done")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("core:home")

        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            user = form.save()

            send_account_activation_email(
                user=user,
                request=self.request,
            )

        return super().form_valid(form)


class RegistrationDoneView(TemplateView):
    template_name = "accounts/registration_done.html"


def activate_account(request, uidb64, token):
    user_model = get_user_model()
    user = None

    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = user_model.objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, user_model.DoesNotExist):
        pass

    if (
        user is not None
        and not user.is_active
        and account_activation_token.check_token(user, token)
    ):
        user.is_active = True
        user.save(update_fields=["is_active"])

        messages.success(
            request,
            "E-mail confirmado. Agora você já pode entrar.",
        )

        return redirect("accounts:login")

    return render(
        request,
        "accounts/activation_invalid.html",
        status=400,
    )


class AccountPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset.html"
    form_class = AccountPasswordResetForm
    email_template_name = "accounts/emails/password_reset.txt"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class AccountPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class AccountPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = AccountSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")


class AccountPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"

class AccountDashboardView(LoginRequiredMixin, TemplateView):
    """
    Área principal do comprador autenticado.
    """

    template_name = "accounts/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["organizer_membership"] = (
            resolve_active_organizer_membership(self.request)
        )

        context["orders"] = ()

        return context