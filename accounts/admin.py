from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import LoginActivity, User, UserProfile


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "is_staff", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "created_at")
    search_fields = ("user__first_name", "user__email", "phone")
    list_filter = ("created_at",)


@admin.register(LoginActivity)
class LoginActivityAdmin(admin.ModelAdmin):
    list_display = ("email", "user", "success", "ip_address", "login_at")
    search_fields = ("email", "user__email", "user__first_name", "ip_address")
    list_filter = ("success", "login_at")
    readonly_fields = (
        "user",
        "email",
        "success",
        "failure_reason",
        "ip_address",
        "user_agent",
        "login_at",
    )
