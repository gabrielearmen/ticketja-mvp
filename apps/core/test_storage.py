from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import SimpleTestCase

from .storage import CloudinaryMediaStorage


class CloudinaryMediaStorageTests(SimpleTestCase):
    def setUp(self):
        self.storage = CloudinaryMediaStorage()

    @patch("apps.core.storage.cloudinary.uploader.upload")
    def test_save_preserves_image_extension(
        self,
        mocked_upload,
    ):
        mocked_upload.return_value = {
            "public_id": (
                "ticketja/events/covers/2026/09/image-id"
            ),
            "format": "png",
        }

        stored_name = self.storage.save(
            "events/covers/2026/09/capa.png",
            ContentFile(b"image-content"),
        )

        self.assertEqual(
            stored_name,
            (
                "ticketja/events/covers/2026/09/"
                "image-id.png"
            ),
        )

    @patch("apps.core.storage.cloudinary.api.resource")
    def test_size_uses_public_id_without_extension(
        self,
        mocked_resource,
    ):
        mocked_resource.return_value = {
            "bytes": 2048,
        }

        size = self.storage.size(
            "ticketja/events/covers/image-id.png"
        )

        self.assertEqual(size, 2048)

        mocked_resource.assert_called_once_with(
            "ticketja/events/covers/image-id",
            resource_type="image",
        )

    @patch("apps.core.storage.cloudinary.uploader.destroy")
    def test_delete_uses_public_id_without_extension(
        self,
        mocked_destroy,
    ):
        self.storage.delete(
            "ticketja/events/covers/image-id.webp"
        )

        mocked_destroy.assert_called_once_with(
            "ticketja/events/covers/image-id",
            resource_type="image",
            invalidate=True,
        )