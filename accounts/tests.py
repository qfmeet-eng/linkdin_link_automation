import json

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import UserProfile


class ChatbotRegistrationTests(TestCase):
    def test_register_user_from_chatbot(self):
        payload = {
            "name": "Dhruv Patel",
            "phone": "9876543210",
            "email": "dhruv@example.com",
            "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
        }

        response = self.client.post(
            reverse("register_chatbot_user"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["success"])

        User = get_user_model()
        user = User.objects.get(email="dhruv@example.com")
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertEqual(user.profile.phone, "9876543210")

    def test_password_confirmation_must_match(self):
        payload = {
            "name": "Dhruv Patel",
            "phone": "9876543210",
            "email": "dhruv@example.com",
            "password": "StrongPass123!",
            "confirm_password": "WrongPass123!",
        }

        response = self.client.post(
            reverse("register_chatbot_user"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])

    def test_duplicate_phone_is_rejected(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="old@example.com",
            email="old@example.com",
            password="StrongPass123!",
            first_name="Old User",
        )
        UserProfile.objects.create(user=user, phone="9876543210")

        payload = {
            "name": "New User",
            "phone": "9876543210",
            "email": "new@example.com",
            "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
        }

        response = self.client.post(
            reverse("register_chatbot_user"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["message"], "User is already exist.")
        self.assertIn("phone", response.json()["errors"])

    def test_duplicate_email_is_rejected_as_existing_user(self):
        User = get_user_model()
        User.objects.create_user(
            username="old@example.com",
            email="old@example.com",
            password="StrongPass123!",
            first_name="Old User",
        )

        payload = {
            "name": "New User",
            "phone": "9876543211",
            "email": "old@example.com",
            "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
        }

        response = self.client.post(
            reverse("register_chatbot_user"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["message"], "User is already exist.")
        self.assertIn("email", response.json()["errors"])

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="noreply@example.com",
        APP_BASE_URL="http://testserver",
    )
    def test_forgot_password_sends_reset_email(self):
        User = get_user_model()
        User.objects.create_user(
            username="dhruv@example.com",
            email="dhruv@example.com",
            password="StrongPass123!",
            first_name="Dhruv",
        )

        response = self.client.post(
            reverse("forgot_password_user"),
            data=json.dumps({"email": "dhruv@example.com"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("http://testserver/reset/", mail.outbox[0].body)
