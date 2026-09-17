from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """
    Responsável pela criação consistente de usuários comuns
    e administradores da plataforma.
    """

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """
        Implementação central utilizada por todos os tipos de usuário.
        """
        if not email:
            raise ValueError("O endereço de e-mail é obrigatório.")

        normalized_email = self.normalize_email(email).strip().casefold()

        user = self.model(
            email=normalized_email,
            **extra_fields,
        )

        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_user(self, email, password=None, **extra_fields):
        """
        Cria um usuário comum, sem acesso administrativo.
        """
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)

        return self._create_user(
            email=email,
            password=password,
            **extra_fields,
        )

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Cria um administrador geral da plataforma.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(
                "Um superusuário precisa possuir is_staff=True."
            )

        if extra_fields.get("is_superuser") is not True:
            raise ValueError(
                "Um superusuário precisa possuir is_superuser=True."
            )

        return self._create_user(
            email=email,
            password=password,
            **extra_fields,
        )