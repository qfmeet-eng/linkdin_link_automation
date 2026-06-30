import json
import re
import secrets
from json import JSONDecodeError
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponse, HttpResponseRedirect
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.template.loader import render_to_string
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from accounts.models import LoginActivity, UserProfile, UserDetails, ScrapedProfile, LinkedInConfig, LeadActivity
from django.utils import timezone

PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")
USER_EXISTS_MESSAGE = "User is already exist."
DATABASE_NOT_READY_MESSAGE = "Database tables missing che. Pehla python manage.py migrate run karo."


def user_details_view(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect(f"{reverse('admin:login')}?next={request.path}")
    details_list = UserDetails.objects.all().order_by("-created_at")
    linkedin_config = LinkedInConfig.objects.first()
    scraped_profiles = ScrapedProfile.objects.all().order_by("-created_at")
    return render(request, "accounts/user_details.html", {
        "details_list": details_list,
        "linkedin_config": linkedin_config,
        "scraped_profiles": scraped_profiles,
    })


@require_POST
def admin_create_user(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"success": False, "message": "Permission denied."}, status=403)
    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip().replace(" ", "")
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    is_active = data.get("is_active", True)
    if not isinstance(is_active, bool):
        is_active = str(is_active).lower() == "true"

    errors = {}

    if not name:
        errors["name"] = "Naam required che."
    elif len(name) > 150:
        errors["name"] = "Naam 150 characters karta ochhu hovu joiye."

    if not phone:
        errors["phone"] = "Mobile number required che."
    elif not PHONE_RE.match(phone):
        errors["phone"] = "Mobile number 10 thi 15 digits no hovo joiye."

    if not email:
        errors["email"] = "Email required che."
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors["email"] = "Email address valid nathi."

    if not password:
        errors["password"] = "Password required che."

    User = get_user_model()

    try:
        email_exists = email and (
            User.objects.filter(email__iexact=email).exists()
            or User.objects.filter(username__iexact=email).exists()
        )
        phone_exists = phone and UserProfile.objects.filter(phone=phone).exists()
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()

    if email_exists:
        errors["email"] = USER_EXISTS_MESSAGE

    if phone_exists:
        errors["phone"] = USER_EXISTS_MESSAGE

    if password:
        try:
            user_candidate = User(username=email, email=email, first_name=name)
            validate_password(password, user=user_candidate)
        except ValidationError as exc:
            errors["password"] = " ".join(exc.messages)

    if errors:
        return JsonResponse(
            {
                "success": False,
                "message": next(iter(errors.values())),
                "errors": errors,
            },
            status=400,
        )

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=name,
                is_active=is_active,
            )
            UserProfile.objects.create(user=user, phone=phone)
            UserDetails.objects.create(
                user=user,
                name=name,
                email=email,
                phone=phone,
            )
    except IntegrityError:
        return JsonResponse(
            {
                "success": False,
                "message": USER_EXISTS_MESSAGE,
                "errors": {"user": USER_EXISTS_MESSAGE},
            },
            status=409,
        )
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()

    return JsonResponse(
        {
            "success": True,
            "message": "User successfully created.",
        },
        status=201,
    )


@require_POST
def admin_update_user(request, user_id):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"success": False, "message": "Permission denied."}, status=403)
    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    User = get_user_model()
    user = User.objects.filter(id=user_id).first()
    if not user:
        return JsonResponse({"success": False, "message": "User not found."}, status=404)

    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip().replace(" ", "")
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    is_active = data.get("is_active", True)
    if not isinstance(is_active, bool):
        is_active = str(is_active).lower() == "true"

    errors = {}

    if not name:
        errors["name"] = "Naam required che."
    elif len(name) > 150:
        errors["name"] = "Naam 150 characters karta ochhu hovu joiye."

    if not phone:
        errors["phone"] = "Mobile number required che."
    elif not PHONE_RE.match(phone):
        errors["phone"] = "Mobile number 10 thi 15 digits no hovo joiye."

    if not email:
        errors["email"] = "Email required che."
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors["email"] = "Email address valid nathi."

    try:
        email_exists = email and (
            User.objects.filter(email__iexact=email).exclude(id=user_id).exists()
            or User.objects.filter(username__iexact=email).exclude(id=user_id).exists()
        )
        phone_exists = phone and UserProfile.objects.filter(phone=phone).exclude(user_id=user_id).exists()
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()

    if email_exists:
        errors["email"] = USER_EXISTS_MESSAGE

    if phone_exists:
        errors["phone"] = USER_EXISTS_MESSAGE

    if password:
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            errors["password"] = " ".join(exc.messages)

    if errors:
        return JsonResponse(
            {
                "success": False,
                "message": next(iter(errors.values())),
                "errors": errors,
            },
            status=400,
        )

    try:
        with transaction.atomic():
            user.username = email
            user.email = email
            user.first_name = name
            user.is_active = is_active
            if password:
                user.set_password(password)
            user.save()

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.phone = phone
            profile.save()

            details, _ = UserDetails.objects.get_or_create(user=user)
            details.name = name
            details.email = email
            details.phone = phone
            details.save()
    except IntegrityError:
        return JsonResponse(
            {
                "success": False,
                "message": USER_EXISTS_MESSAGE,
                "errors": {"user": USER_EXISTS_MESSAGE},
            },
            status=409,
        )
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()

    return JsonResponse(
        {
            "success": True,
            "message": "User successfully updated.",
        }
    )


@require_POST
def admin_delete_user(request, user_id):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"success": False, "message": "Permission denied."}, status=403)
    User = get_user_model()
    user = User.objects.filter(id=user_id).first()
    if not user:
        return JsonResponse({"success": False, "message": "User not found."}, status=404)

    try:
        user.delete()
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()

    return JsonResponse(
        {
            "success": True,
            "message": "User successfully deleted.",
        }
    )


@require_POST
def admin_toggle_status(request, user_id):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"success": False, "message": "Permission denied."}, status=403)
    User = get_user_model()
    user = User.objects.filter(id=user_id).first()
    if not user:
        return JsonResponse({"success": False, "message": "User not found."}, status=404)

    try:
        user.is_active = not user.is_active
        user.save()
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()

    return JsonResponse(
        {
            "success": True,
            "is_active": user.is_active,
            "message": f"User status changed to {'Active' if user.is_active else 'Inactive'}.",
        }
    )


def admin_login_activities(request, user_id):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"success": False, "message": "Permission denied."}, status=403)
    User = get_user_model()
    user = User.objects.filter(id=user_id).first()
    if not user:
        return JsonResponse({"success": False, "message": "User not found."}, status=404)

    try:
        activities = LoginActivity.objects.filter(email=user.email).order_by("-login_at")[:50]
        data = []
        for act in activities:
            data.append({
                "login_at": act.login_at.strftime("%Y-%m-%d %H:%M:%S") if act.login_at else "",
                "success": act.success,
                "failure_reason": act.failure_reason,
                "ip_address": act.ip_address or "—",
                "user_agent": act.user_agent or "—",
            })
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()

    return JsonResponse(
        {
            "success": True,
            "activities": data,
        }
    )


@require_POST
def api_update_linkedin_config(request):
    """
    Update the LinkedIn session cookie stored in the database.
    POST /api/admin/config/update/
    """
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"success": False, "message": "Permission denied."}, status=403)

    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    cookie_val = str(data.get("li_at_cookie", "")).strip()

    try:
        config, created = LinkedInConfig.objects.get_or_create(id=1)
        config.li_at_cookie = cookie_val
        config.save()

        last_updated = config.updated_at.strftime("%d %b %Y, %H:%M") if config.updated_at else "Now"

        return JsonResponse({
            "success": True,
            "message": "LinkedIn configuration successfully updated.",
            "last_updated": last_updated,
            "is_set": bool(cookie_val)
        })
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Database error: {str(e)}"}, status=500)


def admin_scraped_profile_detail(request, profile_id):
    """Get full details of a specific scraped profile (admin view)."""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"success": False, "message": "Permission denied."}, status=403)

    try:
        profile = ScrapedProfile.objects.filter(id=profile_id).first()
        if not profile:
            return JsonResponse({"success": False, "message": "Profile not found."}, status=404)
            
        return JsonResponse({
            "success": True,
            "profile": {
                "id": profile.id,
                "url": profile.url,
                "name": profile.name,
                "headline": profile.headline,
                "location": profile.location,
                "about": profile.about,
                "experience": profile.experience,
                "education": profile.education,
                "skills": profile.skills,
                "raw_pdf_text": profile.raw_pdf_text,
                "created_at": profile.created_at.strftime("%d %b %Y, %H:%M"),
                "scraped_by": profile.user.email if profile.user else "System",
            }
        })
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Database error: {str(e)}"}, status=500)


@require_POST
def admin_delete_scraped_profile(request, profile_id):
    """Delete a scraped profile (admin view)."""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"success": False, "message": "Permission denied."}, status=403)

    try:
        profile = ScrapedProfile.objects.filter(id=profile_id).first()
        if not profile:
            return JsonResponse({"success": False, "message": "Profile not found."}, status=404)
        profile.delete()
        return JsonResponse({"success": True, "message": "Profile successfully deleted."})
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Database error: {str(e)}"}, status=500)







# ── LinkedIn Lead Activity Analyzer Views ────────────────────────────────────

