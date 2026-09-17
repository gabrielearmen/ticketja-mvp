from django.urls import path

from .views import (
    AccountLoginView,
    AccountLogoutView,
    AccountPasswordResetCompleteView,
    AccountPasswordResetConfirmView,
    AccountPasswordResetDoneView,
    AccountPasswordResetView,
    AccountRegistrationView,
    RegistrationDoneView,
    activate_account,
    AccountDashboardView,
)


app_name = "accounts"


urlpatterns = [
        path(
        "minha-conta/",
        AccountDashboardView.as_view(),
        name="dashboard",
    ),
    path(
        "entrar/",
        AccountLoginView.as_view(),
        name="login",
    ),
    path(
        "cadastro/",
        AccountRegistrationView.as_view(),
        name="register",
    ),
    path(
        "cadastro/concluido/",
        RegistrationDoneView.as_view(),
        name="registration_done",
    ),
    path(
        "confirmar-email/<uidb64>/<token>/",
        activate_account,
        name="activate",
    ),
    path(
        "esqueci-minha-senha/",
        AccountPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "esqueci-minha-senha/instrucoes/",
        AccountPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "redefinir-senha/<uidb64>/<token>/",
        AccountPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "redefinir-senha/concluido/",
        AccountPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path(
        "sair/",
        AccountLogoutView.as_view(),
        name="logout",
    ),
]