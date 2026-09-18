from pathlib import PurePosixPath
from urllib.request import urlopen
from uuid import uuid4

import cloudinary
import cloudinary.api
import cloudinary.uploader
from cloudinary.exceptions import NotFound
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible
from django.utils.text import slugify


@deconstructible
class CloudinaryMediaStorage(Storage):
    """
    Armazena imagens enviadas pelos usuários no Cloudinary.

    O banco guarda um nome virtual com extensão para manter
    compatibilidade com os validadores do Django. O Cloudinary
    continua recebendo somente o public_id real.
    """

    resource_type = "image"
    root_folder = "ticketja"

    supported_formats = {
        "jpg",
        "jpeg",
        "png",
        "webp",
    }

    def get_available_name(self, name, max_length=None):
        return name

    def _cloudinary_reference(self, name):
        """
        Separa o public_id real da extensão virtual armazenada
        pelo Django.

        Exemplo:
        ticketja/events/covers/abc.png
        retorna:
        ("ticketja/events/covers/abc", "png")
        """
        normalized_name = str(name).replace("\\", "/")
        stored_path = PurePosixPath(normalized_name)
        image_format = stored_path.suffix.lower().lstrip(".")

        if image_format in self.supported_formats:
            public_id = str(stored_path.with_suffix(""))
            return public_id, image_format

        # Compatibilidade com imagens armazenadas anteriormente
        # sem extensão.
        return normalized_name, None

    def _save(self, name, content):
        original_path = PurePosixPath(
            str(name).replace("\\", "/")
        )

        safe_folders = [
            slugify(part)
            for part in original_path.parent.parts
            if part not in {"", ".", ".."} and slugify(part)
        ]

        cloudinary_folder = "/".join(
            [self.root_folder, *safe_folders]
        )

        if hasattr(content, "seek"):
            content.seek(0)

        upload_result = cloudinary.uploader.upload(
            content,
            resource_type=self.resource_type,
            folder=cloudinary_folder,
            public_id=uuid4().hex,
            unique_filename=False,
            overwrite=False,
        )

        public_id = upload_result["public_id"]
        image_format = upload_result.get("format", "").lower()

        if image_format not in self.supported_formats:
            image_format = (
                original_path.suffix.lower().lstrip(".")
            )

        if image_format not in self.supported_formats:
            raise ValueError(
                "O Cloudinary não informou um formato de "
                "imagem permitido."
            )

        # A extensão é preservada para os validadores do Django.
        # Ela não faz parte do public_id real do Cloudinary.
        return f"{public_id}.{image_format}"

    def _open(self, name, mode="rb"):
        if mode not in {"r", "rb"}:
            raise ValueError(
                "O armazenamento do Cloudinary permite "
                "somente abertura para leitura."
            )

        with urlopen(self.url(name), timeout=15) as response:
            file_content = response.read()

        return ContentFile(
            file_content,
            name=PurePosixPath(name).name,
        )

    def delete(self, name):
        if not name:
            return

        public_id, _ = self._cloudinary_reference(name)

        cloudinary.uploader.destroy(
            public_id,
            resource_type=self.resource_type,
            invalidate=True,
        )

    def exists(self, name):
        if not name:
            return False

        public_id, _ = self._cloudinary_reference(name)

        try:
            cloudinary.api.resource(
                public_id,
                resource_type=self.resource_type,
            )
        except NotFound:
            return False

        return True

    def size(self, name):
        public_id, _ = self._cloudinary_reference(name)

        resource = cloudinary.api.resource(
            public_id,
            resource_type=self.resource_type,
        )

        return resource["bytes"]

    def url(self, name):
        if not name:
            raise ValueError(
                "Não é possível gerar a URL de uma imagem vazia."
            )

        public_id, image_format = (
            self._cloudinary_reference(name)
        )

        options = {
            "secure": True,
        }

        if image_format:
            options["format"] = image_format

        return cloudinary.CloudinaryImage(
            public_id
        ).build_url(**options)