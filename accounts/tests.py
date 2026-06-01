import json

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import LoginActivity, UserProfile


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

    def test_favicon_returns_empty_response(self):
        response = self.client.get(reverse("favicon"))

        self.assertEqual(response.status_code, 204)

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

    def test_login_user_creates_login_activity(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="login@example.com",
            email="login@example.com",
            password="StrongPass123!",
            first_name="Login User",
        )

        response = self.client.post(
            reverse("login_chatbot_user"),
            data=json.dumps(
                {
                    "email": "login@example.com",
                    "password": "StrongPass123!",
                }
            ),
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
            HTTP_USER_AGENT="Django test client",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(str(self.client.session["_auth_user_id"]), str(user.id))

        activity = LoginActivity.objects.get(user=user)
        self.assertTrue(activity.success)
        self.assertEqual(activity.email, "login@example.com")
        self.assertEqual(activity.ip_address, "127.0.0.1")

    def test_invalid_login_creates_failed_activity(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="login@example.com",
            email="login@example.com",
            password="StrongPass123!",
            first_name="Login User",
        )

        response = self.client.post(
            reverse("login_chatbot_user"),
            data=json.dumps(
                {
                    "email": "login@example.com",
                    "password": "WrongPass123!",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()["success"])

        activity = LoginActivity.objects.get(user=user)
        self.assertFalse(activity.success)
        self.assertEqual(activity.failure_reason, "Invalid email or password")

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
