import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


# Diretório principal do projeto:
# C:\Users\gabri\Desktop\TicketJa
BASE_DIR = Path(__file__).resolve().parent.parent


# Carrega as variáveis privadas do arquivo .env.
# override=False impede que o arquivo local substitua variáveis
# definidas diretamente pelo servidor de produção.
load_dotenv(BASE_DIR / ".env", override=False)


def required_environment(name: str) -> str:
    """
    Obtém uma variável de ambiente obrigatória.

    O sistema interrompe a inicialização se a variável não existir
    ou estiver vazia. Isso evita iniciar com configuração incompleta.
    """
    value = os.environ.get(name, "").strip()

    if not value:
        raise ImproperlyConfigured(
            f"A variável de ambiente obrigatória {name} não foi configurada."
        )

    return value


def environment_boolean(name: str, default: bool = False) -> bool:
    """
    Converte uma variável de ambiente textual em verdadeiro ou falso.

    Valores aceitos:
    - verdadeiro: true, 1, yes, sim, on
    - falso: false, 0, no, nao, off
    """
    raw_value = os.environ.get(name)

    if raw_value is None:
        return default

    normalized_value = raw_value.strip().lower()

    true_values = {"true", "1", "yes", "sim", "on"}
    false_values = {"false", "0", "no", "nao", "off"}

    if normalized_value in true_values:
        return True

    if normalized_value in false_values:
        return False

    raise ImproperlyConfigured(
        f"A variável {name} deve representar um valor verdadeiro ou falso."
    )

def environment_integer(
    name: str,
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """
    Converte uma variável de ambiente em número inteiro.

    Também permite limitar os valores mínimo e máximo aceitos.
    Configurações inválidas interrompem a inicialização para evitar
    comportamentos inesperados em produção.
    """
    raw_value = os.environ.get(name)

    if raw_value is None:
        return default

    normalized_value = raw_value.strip()

    if not normalized_value:
        raise ImproperlyConfigured(
            f"A variável {name} não pode estar vazia."
        )

    try:
        value = int(normalized_value)
    except ValueError as error:
        raise ImproperlyConfigured(
            f"A variável {name} deve ser um número inteiro."
        ) from error

    if minimum is not None and value < minimum:
        raise ImproperlyConfigured(
            f"A variável {name} deve ser maior ou igual a "
            f"{minimum}."
        )

    if maximum is not None and value > maximum:
        raise ImproperlyConfigured(
            f"A variável {name} deve ser menor ou igual a "
            f"{maximum}."
        )

    return value

# Segurança fundamental do Django
SECRET_KEY = required_environment("DJANGO_SECRET_KEY")

if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY deve possuir pelo menos 50 caracteres."
    )


# DEBUG exibe informações técnicas detalhadas.
# Deve ser True somente no desenvolvimento local.
DEBUG = environment_boolean("DJANGO_DEBUG", default=False)


# Define os endereços pelos quais o Django aceita requisições.
ALLOWED_HOSTS = [
    host.strip()
    for host in required_environment("DJANGO_ALLOWED_HOSTS").split(",")
    if host.strip()
]

# O Render fornece automaticamente o endereço público do serviço.
# Ele é acrescentado somente no ambiente hospedado.
RENDER_EXTERNAL_HOSTNAME = os.environ.get(
    "RENDER_EXTERNAL_HOSTNAME",
    "",
).strip()

if (
    RENDER_EXTERNAL_HOSTNAME
    and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS
):
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)


# Autoriza formulários POST originados no domínio HTTPS do Render.
CSRF_TRUSTED_ORIGINS = []

if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(
        f"https://{RENDER_EXTERNAL_HOSTNAME}"
    )

# Aplicações oficiais fornecidas pelo Django
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]


# Aplicações próprias do TicketJá serão adicionadas aqui futuramente.
LOCAL_APPS = [
    "apps.accounts.apps.AccountsConfig",
    "apps.core.apps.CoreConfig",
    "apps.organizations.apps.OrganizationsConfig",
    "apps.events.apps.EventsConfig",
    "apps.kits.apps.KitsConfig",
    "apps.orders.apps.OrdersConfig",
    "apps.registrations.apps.RegistrationsConfig",
    "apps.marketplace.apps.MarketplaceConfig",
    "apps.payments.apps.PaymentsConfig",
]


INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

AUTH_USER_MODEL = "accounts.User"


# Camadas executadas em todas as requisições e respostas.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"


# Sistema de templates HTML do Django
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                (
                    "apps.organizations.context_processors."
                    "organizer_navigation"
                )
            ],
        },
    },
]


WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# Banco exclusivamente PostgreSQL.
# Não existe configuração SQLite ou fallback automático.
# Banco exclusivamente PostgreSQL.
# Não existe configuração SQLite ou fallback automático.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": required_environment("POSTGRES_DB"),
        "USER": required_environment("POSTGRES_USER"),
        "PASSWORD": required_environment("POSTGRES_PASSWORD"),
        "HOST": required_environment("POSTGRES_HOST"),
        "PORT": required_environment("POSTGRES_PORT"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "application_name": "ticketja",
        },
        "TEST": {
            "NAME": required_environment("POSTGRES_TEST_DB"),
        },
    }
}


# Validadores utilizados quando as contas forem implementadas.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# Idioma e horário inicial do projeto.
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Fortaleza"
USE_I18N = True
USE_TZ = True


# Arquivos públicos, como CSS, JavaScript e imagens da interface.
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

CLOUDINARY_URL = os.environ.get(
    "CLOUDINARY_URL",
    "",
).strip()

MEDIA_STORAGE_BACKEND = (
    "apps.core.storage.CloudinaryMediaStorage"
    if CLOUDINARY_URL
    else "django.core.files.storage.FileSystemStorage"
)

# Os testes não dependem de um manifesto produzido anteriormente
# pelo collectstatic. Produção continua usando arquivos versionados,
# comprimidos e com hash para cache seguro.
RUNNING_TESTS = "test" in sys.argv

STATICFILES_STORAGE_BACKEND = (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
    if RUNNING_TESTS
    else (
        "whitenoise.storage."
        "CompressedManifestStaticFilesStorage"
    )
)

STORAGES = {
    "default": {
        "BACKEND": MEDIA_STORAGE_BACKEND,
    },
    "staticfiles": {
        "BACKEND": STATICFILES_STORAGE_BACKEND,
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Tipo padrão dos identificadores numéricos criados pelo Django.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Proteções aplicáveis tanto ao desenvolvimento quanto à produção.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Informa ao Django que o proxy da hospedagem recebeu a
# requisição original utilizando HTTPS.
SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

# No desenvolvimento usamos HTTP local.
# Em produção, estas proteções passam a exigir HTTPS.
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG


# HSTS só pode ser ativado quando HTTPS estiver configurado.
SECURE_HSTS_SECONDS = 0 if DEBUG else 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "core:home"

if DEBUG:
    EMAIL_BACKEND = (
        "django.core.mail.backends.console.EmailBackend"
    )
    DEFAULT_FROM_EMAIL = "TicketJá <nao-responda@ticketja.local>"
else:
    EMAIL_BACKEND = required_environment("EMAIL_BACKEND")
    DEFAULT_FROM_EMAIL = required_environment("DEFAULT_FROM_EMAIL")

# Tokens de confirmação e recuperação expiram após 24 horas.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24

# Tempo máximo de bloqueio das vagas enquanto o comprador
# conclui participantes e pagamento.
ORDER_RESERVATION_MINUTES = environment_integer(
    "ORDER_RESERVATION_MINUTES",
    default=15,
    minimum=5,
    maximum=60,
)
# Implementação concreta do provedor de pagamentos.
#
# O gateway fica desacoplado da regra de negócio. Futuramente
# poderemos substituir o Mercado Pago sem reescrever pedidos,
# inscrições, kits ou o restante do checkout.
PAYMENT_GATEWAY_CLASS = os.environ.get(
    "PAYMENT_GATEWAY_CLASS",
    (
        "apps.payments.gateways.mercado_pago."
        "MercadoPagoGateway"
    ),
).strip()


# Credencial privada utilizada exclusivamente no backend.
#
# Ela não pode aparecer em templates, JavaScript, GitHub,
# mensagens de erro ou logs.
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get(
    "MERCADO_PAGO_ACCESS_TOKEN",
    "",
).strip()

# Ativa os comportamentos oficiais de simulação do Mercado Pago.
# Nunca deve permanecer True quando forem utilizadas credenciais reais.
MERCADO_PAGO_TEST_MODE = environment_boolean(
    "MERCADO_PAGO_TEST_MODE",
    default=False,
)


# O Mercado Pago utiliza o mesmo endereço de API para testes e
# produção. O ambiente é determinado pela credencial utilizada.
MERCADO_PAGO_API_BASE_URL = os.environ.get(
    "MERCADO_PAGO_API_BASE_URL",
    "https://api.mercadopago.com",
).strip().rstrip("/")


# Limite máximo de espera de cada chamada ao provedor.
MERCADO_PAGO_TIMEOUT_SECONDS = environment_integer(
    "MERCADO_PAGO_TIMEOUT_SECONDS",
    default=15,
    minimum=5,
    maximum=60,
)


# A Payments API do Mercado Pago exige pelo menos 30 minutos.
# O padrão inclui uma margem operacional para que o prazo não fique
# abaixo do mínimo durante a preparação e o envio da requisição.
PAYMENT_PIX_EXPIRATION_MINUTES = environment_integer(
    "PAYMENT_PIX_EXPIRATION_MINUTES",
    default=35,
    minimum=30,
    maximum=1440,
)

# Prazo da sessão hospedada. É separado do PIX legado para que
# futuras regras do Checkout Pro não alterem cobranças antigas.
PAYMENT_CHECKOUT_EXPIRATION_MINUTES = environment_integer(
    "PAYMENT_CHECKOUT_EXPIRATION_MINUTES",
    default=35,
    minimum=30,
    maximum=1440,
)

PAYMENT_RECONCILIATION_MIN_INTERVAL_MINUTES = environment_integer(
    "PAYMENT_RECONCILIATION_MIN_INTERVAL_MINUTES",
    default=5,
    minimum=1,
    maximum=60,
)

PAYMENT_SETTLED_RECONCILIATION_INTERVAL_HOURS = environment_integer(
    "PAYMENT_SETTLED_RECONCILIATION_INTERVAL_HOURS",
    default=24,
    minimum=1,
    maximum=168,
)

PAYMENT_RECONCILIATION_LOOKBACK_DAYS = environment_integer(
    "PAYMENT_RECONCILIATION_LOOKBACK_DAYS",
    default=180,
    minimum=1,
    maximum=365,
)

# Chave utilizada exclusivamente para autenticar os Webhooks
# enviados pelo Mercado Pago.
#
# Não é o Access Token e nunca deve ser exposta em templates,
# JavaScript, GitHub ou mensagens de erro.
MERCADO_PAGO_WEBHOOK_SECRET = os.environ.get(
    "MERCADO_PAGO_WEBHOOK_SECRET",
    "",
).strip()


# Proteção contra corpos excessivamente grandes enviados ao endpoint.
PAYMENT_WEBHOOK_MAX_BODY_BYTES = environment_integer(
    "PAYMENT_WEBHOOK_MAX_BODY_BYTES",
    default=65536,
    minimum=1024,
    maximum=1048576,
)


# Marketplace Mercado Pago.
#
# O modo marketplace permanece desligado até OAuth, webhooks e
# homologação produtiva estarem concluídos. Isso impede que uma
# configuração parcial direcione dinheiro para a conta errada.
MARKETPLACE_PAYMENTS_ENABLED = environment_boolean(
    "MARKETPLACE_PAYMENTS_ENABLED",
    default=False,
)

# Fluxo usado para cobranças marketplace.
# "checkout_pro" redireciona o comprador ao ambiente seguro do
# Mercado Pago e permite os meios habilitados na conta do vendedor.
# "pix" existe somente para compatibilidade com cobranças antigas.
MARKETPLACE_CHECKOUT_MODE = os.environ.get(
    "MARKETPLACE_CHECKOUT_MODE",
    "checkout_pro",
).strip().lower()

MARKETPLACE_OAUTH_ENABLED = environment_boolean(
    "MARKETPLACE_OAUTH_ENABLED",
    default=False,
)

# Chaves Fernet separadas por vírgula. A primeira cifra valores novos;
# as demais permitem descriptografar valores durante rotação de chave.
# Nunca reutilize DJANGO_SECRET_KEY para esta finalidade.
MARKETPLACE_TOKEN_ENCRYPTION_KEYS = os.environ.get(
    "MARKETPLACE_TOKEN_ENCRYPTION_KEYS",
    "",
).strip()

MERCADO_PAGO_CLIENT_ID = os.environ.get(
    "MERCADO_PAGO_CLIENT_ID",
    "",
).strip()

MERCADO_PAGO_CLIENT_SECRET = os.environ.get(
    "MERCADO_PAGO_CLIENT_SECRET",
    "",
).strip()

MERCADO_PAGO_OAUTH_REDIRECT_URI = os.environ.get(
    "MERCADO_PAGO_OAUTH_REDIRECT_URI",
    "",
).strip()

MERCADO_PAGO_OAUTH_AUTHORIZE_URL = os.environ.get(
    "MERCADO_PAGO_OAUTH_AUTHORIZE_URL",
    "https://auth.mercadopago.com.br/authorization",
).strip()

MERCADO_PAGO_OAUTH_TOKEN_URL = os.environ.get(
    "MERCADO_PAGO_OAUTH_TOKEN_URL",
    "https://api.mercadopago.com/oauth/token",
).strip()

MARKETPLACE_OAUTH_STATE_TTL_MINUTES = environment_integer(
    "MARKETPLACE_OAUTH_STATE_TTL_MINUTES",
    default=10,
    minimum=5,
    maximum=30,
)
