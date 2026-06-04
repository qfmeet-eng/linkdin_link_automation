import json
from unittest.mock import patch

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

    def test_login_user_by_username_creates_login_activity(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="admin_user",
            email="admin@example.com",
            password="StrongPass123!",
            first_name="Admin User",
        )

        response = self.client.post(
            reverse("login_chatbot_user"),
            data=json.dumps(
                {
                    "email": "admin_user",
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
        self.assertEqual(activity.email, "admin_user")

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

    def test_chatbot_logout_clears_session_and_redirects(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="logout_test@example.com",
            email="logout_test@example.com",
            password="StrongPass123!",
            first_name="Logout Test User",
        )
        self.client.force_login(user)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.id)

        response = self.client.get(reverse("chatbot_logout"))
        self.assertRedirects(response, reverse("chatbot_register"))
        self.assertNotIn("_auth_user_id", self.client.session)


class AdminAccessTests(TestCase):
    def test_user_details_view_unauthenticated_redirects_to_admin_login(self):
        response = self.client.get(reverse("user_details"))
        self.assertRedirects(response, f"{reverse('admin:login')}?next={reverse('user_details')}")

    def test_user_details_view_non_staff_redirects_to_admin_login(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="normal_user@example.com",
            email="normal_user@example.com",
            password="Password123!",
            is_staff=False,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("user_details"))
        self.assertRedirects(response, f"{reverse('admin:login')}?next={reverse('user_details')}")


class AdminCustomPanelTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.admin_user = self.User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
            password="AdminPass123!",
            first_name="Admin User",
            is_staff=True,
        )
        self.client.force_login(self.admin_user)

    def test_admin_create_user(self):
        payload = {
            "name": "Admin Created User",
            "phone": "9876543212",
            "email": "created@example.com",
            "password": "StrongPass123!",
            "is_active": True,
        }
        response = self.client.post(
            reverse("admin_create_user"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["success"])

        # Check DB
        user = self.User.objects.get(email="created@example.com")
        self.assertEqual(user.first_name, "Admin Created User")
        self.assertEqual(user.profile.phone, "9876543212")
        self.assertEqual(user.user_details.name, "Admin Created User")
        self.assertTrue(user.is_active)

    def test_admin_update_user(self):
        user = self.User.objects.create_user(
            username="to_update@example.com",
            email="to_update@example.com",
            password="OldPass123!",
            first_name="Old Name",
        )
        UserProfile.objects.create(user=user, phone="9876543213")

        payload = {
            "name": "New Name",
            "phone": "9876543214",
            "email": "updated@example.com",
            "password": "NewStrongPass123!",
            "is_active": False,
        }
        response = self.client.post(
            reverse("admin_update_user", kwargs={"user_id": user.id}),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

        user.refresh_from_db()
        self.assertEqual(user.email, "updated@example.com")
        self.assertEqual(user.first_name, "New Name")
        self.assertTrue(user.check_password("NewStrongPass123!"))
        self.assertEqual(user.profile.phone, "9876543214")
        self.assertFalse(user.is_active)

    def test_admin_delete_user(self):
        user = self.User.objects.create_user(
            username="to_delete@example.com",
            email="to_delete@example.com",
            password="DeletePass123!",
            first_name="To Delete",
        )
        UserProfile.objects.create(user=user, phone="9876543215")

        response = self.client.post(
            reverse("admin_delete_user", kwargs={"user_id": user.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertFalse(self.User.objects.filter(id=user.id).exists())

    def test_admin_toggle_status(self):
        user = self.User.objects.create_user(
            username="toggle@example.com",
            email="toggle@example.com",
            password="TogglePass123!",
            first_name="Toggle User",
            is_active=True,
        )
        response = self.client.post(
            reverse("admin_toggle_status", kwargs={"user_id": user.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])

        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_admin_login_activities(self):
        user = self.User.objects.create_user(
            username="logs@example.com",
            email="logs@example.com",
            password="LogsPass123!",
            first_name="Logs User",
        )
        LoginActivity.objects.create(
            user=user,
            email="logs@example.com",
            success=True,
            ip_address="192.168.1.1",
            user_agent="Firefox",
        )
        response = self.client.get(
            reverse("admin_login_activities", kwargs={"user_id": user.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(len(response.json()["activities"]), 1)
        self.assertEqual(response.json()["activities"][0]["ip_address"], "192.168.1.1")

    @patch('accounts.views.get_linkedin_user_data')
    def test_linkedin_callback_existing_user_logs_in(self, mock_get_user_data):
        # Create an existing user
        User = get_user_model()
        user = User.objects.create_user(
            username="linkedin_user@example.com",
            email="linkedin_user@example.com",
            password="StrongPass123!",
            first_name="LinkedIn User",
        )
        UserProfile.objects.create(user=user, phone="9876543219")

        # Mock the API callback response
        mock_get_user_data.return_value = {
            "email": "linkedin_user@example.com",
            "name": "LinkedIn User",
            "first_name": "LinkedIn",
            "last_name": "User",
            "linkedin_id": "li_123",
        }

        # Set session state
        session = self.client.session
        session["linkedin_oauth_state"] = "test_state"
        session.save()

        # Call the callback
        response = self.client.get(
            reverse("linkedin_oauth_callback") + "?code=test_code&state=test_state"
        )

        # It should log the user in directly and redirect to /home/
        self.assertRedirects(response, "/home/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.id)

    @patch('accounts.views.get_linkedin_user_data')
    def test_linkedin_callback_new_user_redirects_to_chatbot(self, mock_get_user_data):
        # Mock the API callback response
        mock_get_user_data.return_value = {
            "email": "new_linkedin@example.com",
            "name": "New LinkedIn User",
            "first_name": "New LinkedIn",
            "last_name": "User",
            "linkedin_id": "li_456",
        }

        # Set session state
        session = self.client.session
        session["linkedin_oauth_state"] = "test_state"
        session.save()

        # Call the callback
        response = self.client.get(
            reverse("linkedin_oauth_callback") + "?code=test_code&state=test_state"
        )

        # It should redirect to /?linkedin_auth=success
        self.assertRedirects(response, "/?linkedin_auth=success")
        self.assertEqual(
            self.client.session["linkedin_user_data"]["email"],
            "new_linkedin@example.com",
        )
