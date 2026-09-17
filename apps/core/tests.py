from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse


class HomeViewTests(TestCase):
    def test_home_page_is_available(self):
        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertContains(
            response,
            "Encontre sua próxima prova.",
        )

    def test_home_is_focused_on_event_discovery(self):
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, 'role="search"')
        self.assertContains(response, 'id="eventos"')
        self.assertContains(response, "Próximos eventos")
        self.assertNotContains(
            response,
            "Uma credencial por participante",
        )

    def test_search_values_are_preserved(self):
        response = self.client.get(
            reverse("core:home"),
            {
                "q": "Corrida",
                "local": "Fortaleza",
            },
        )

        self.assertContains(response, 'value="Corrida"')
        self.assertContains(response, 'value="Fortaleza"')
        self.assertContains(response, "Nenhum evento encontrado")

    def test_required_static_files_exist(self):
        required_files = (
            "css/base.css",
            "css/components.css",
            "css/pages/home.css",
            "img/logo-ticketja.svg",
            "img/favicon.svg",
        )

        for file_path in required_files:
            with self.subTest(file_path=file_path):
                self.assertIsNotNone(finders.find(file_path))