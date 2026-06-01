from django.contrib.auth.views import PasswordResetCompleteView, PasswordResetConfirmView
from django.urls import path
from django.urls import reverse_lazy

from .views import (
    chatbot_register_page,
    favicon,
    forgot_password_user,
    login_chatbot_user,
    register_chatbot_user,
)


urlpatterns = [
    path("", chatbot_register_page, name="chatbot_register"),
    path("favicon.ico", favicon, name="favicon"),
    path("api/register/", register_chatbot_user, name="register_chatbot_user"),
    path("api/login/", login_chatbot_user, name="login_chatbot_user"),
    path("api/forgot-password/", forgot_password_user, name="forgot_password_user"),
    path(
        "reset/<uidb64>/<token>/",
        PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/complete/",
        PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
]
