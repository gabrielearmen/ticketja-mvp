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

    O banco de dados guarda apenas o identificador público da
    imagem. O conteúdo do arquivo permanece no armazenamento
    persistente do Cloudinary.
    """

    resource_type = "image"
    root_folder = "ticketja"

    def get_available_name(self, name, max_length=None):
        """
        O identificador final será gerado com UUID no momento
        do upload, evitando colisões entre arquivos.
        """
        return name

    def _save(self, name, content):
        """
        Envia o arquivo ao Cloudinary e devolve o identificador
        que será armazenado no ImageField.
        """
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

        return upload_result["public_id"]

    def _open(self, name, mode="rb"):
        """
        Permite que o Django abra uma imagem já armazenada.

        A URL é sempre gerada pelo próprio Cloudinary.
        """
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
        """
        Remove a imagem do Cloudinary quando uma exclusão
        explícita for solicitada.
        """
        if not name:
            return

        cloudinary.uploader.destroy(
            name,
            resource_type=self.resource_type,
            invalidate=True,
        )

    def exists(self, name):
        """
        Consulta se o identificador existe no Cloudinary.
        """
        if not name:
            return False

        try:
            cloudinary.api.resource(
                name,
                resource_type=self.resource_type,
            )
        except NotFound:
            return False

        return True

    def size(self, name):
        """
        Retorna o tamanho original da imagem em bytes.
        """
        resource = cloudinary.api.resource(
            name,
            resource_type=self.resource_type,
        )
        return resource["bytes"]

    def url(self, name):
        """
        Gera uma URL pública segura utilizando HTTPS.
        """
        if not name:
            raise ValueError(
                "Não é possível gerar a URL de uma imagem vazia."
            )

        return cloudinary.CloudinaryImage(name).build_url(
            secure=True,
        )