from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
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
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.generic import FormView, TemplateView

from apps.orders.models import OrderStatus
from apps.orders.selectors import orders_for_buyer_area
from apps.organizations.selectors import (
    resolve_active_organizer_membership,
)
from apps.payments.models import OPEN_PAYMENT_STATUSES

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


def build_buyer_order_card(order):
    """
    Transforma um pedido em dados simples para apresentação.

    A função não altera o pedido e não executa regras financeiras.
    Ela somente decide como o estado atual será apresentado.
    """
    items = tuple(order.items.all())

    registrations = tuple(
        registration
        for item in items
        for registration in item.registrations.all()
    )

    expected_participants = sum(
        item.quantity
        for item in items
    )

    completed_participants = sum(
        registration.completed_at is not None
        for registration in registrations
    )

    latest_payment = (
        order.buyer_area_payments[0]
        if order.buyer_area_payments
        else None
    )

    effective_status = order.status

    if (
        order.status == OrderStatus.AWAITING_PAYMENT
        and order.is_expirable
    ):
        effective_status = OrderStatus.EXPIRED

    if effective_status in (
        OrderStatus.DRAFT,
        OrderStatus.AWAITING_PAYMENT,
    ):
        state = "in-progress"
    elif effective_status == OrderStatus.PAID:
        state = "paid"
    else:
        state = "closed"

    if effective_status == OrderStatus.DRAFT:
        action_label = "Continuar pedido"
        action_url = reverse(
            "orders:checkout-detail",
            kwargs={"public_code": order.public_code},
        )

    elif effective_status == OrderStatus.AWAITING_PAYMENT:
        if (
            latest_payment is not None
            and latest_payment.status in OPEN_PAYMENT_STATUSES
        ):
            action_label = "Continuar pagamento"
            action_url = reverse(
                "payments:detail",
                kwargs={"public_code": order.public_code},
            )
        else:
            action_label = "Continuar inscrição"
            action_url = reverse(
                "registrations:participants",
                kwargs={"public_code": order.public_code},
            )

    elif effective_status == OrderStatus.PAID:
        action_label = "Ver confirmação"
        action_url = reverse(
            "payments:detail",
            kwargs={"public_code": order.public_code},
        )

    else:
        action_label = "Ver evento"
        action_url = reverse(
            "events:public-detail",
            kwargs={"event_id": order.event_id},
        )

    return {
        "order": order,
        "state": state,
        "status": effective_status,
        "status_label": OrderStatus(effective_status).label,
        "expected_participants": expected_participants,
        "completed_participants": completed_participants,
        "latest_payment": latest_payment,
        "action_label": action_label,
        "action_url": action_url,
    }


class AccountDashboardView(LoginRequiredMixin, TemplateView):
    """
    Área principal do comprador autenticado.
    """

    template_name = "accounts/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        organizer_membership = (
            resolve_active_organizer_membership(self.request)
        )

        orders = orders_for_buyer_area(
            buyer=self.request.user,
        )

        order_cards = [
            build_buyer_order_card(order)
            for order in orders
        ]

        context.update(
            {
                "organizer_membership": organizer_membership,
                "order_cards": order_cards,
                "orders_in_progress": sum(
                    card["state"] == "in-progress"
                    for card in order_cards
                ),
                "paid_orders": sum(
                    card["state"] == "paid"
                    for card in order_cards
                ),
                "closed_orders": sum(
                    card["state"] == "closed"
                    for card in order_cards
                ),
            }
        )

        return context