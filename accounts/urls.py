from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetCompleteView, PasswordResetConfirmView
from django.urls import path
from django.urls import reverse_lazy

from .views import (
    chatbot_register_page,
    favicon,
    forgot_password_user,
    home_view,
    linkedin_oauth_callback,
    linkedin_oauth_start,
    linkedin_userinfo_api,
    login_chatbot_user,
    register_chatbot_user,
    scrape_linkedin_view,
    user_details_view,
)


urlpatterns = [
    path("", chatbot_register_page, name="chatbot_register"),
    path("home/", home_view, name="home"),
    path("user-details/", user_details_view, name="user_details"),
    path("favicon.ico", favicon, name="favicon"),
    path("api/register/", register_chatbot_user, name="register_chatbot_user"),
    path("api/login/", login_chatbot_user, name="login_chatbot_user"),
    path("api/forgot-password/", forgot_password_user, name="forgot_password_user"),
    path("api/linkedin-scrape/", scrape_linkedin_view, name="linkedin_scrape"),
    path("auth/linkedin/", linkedin_oauth_start, name="linkedin_oauth_start"),
    path("auth/linkedin/callback/", linkedin_oauth_callback, name="linkedin_oauth_callback"),
    path("auth/linkedin/userinfo/", linkedin_userinfo_api, name="linkedin_userinfo_api"),
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
