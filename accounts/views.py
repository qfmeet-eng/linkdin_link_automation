import json
import re
from json import JSONDecodeError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_POST

from .models import UserProfile


PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")
USER_EXISTS_MESSAGE = "User is already exist."


def chatbot_register_page(request):
    return render(request, "accounts/chatbot.html")


def parse_json_body(request):
    try:
        return json.loads(request.body.decode("utf-8")), None
    except (JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse(
            {"success": False, "message": "Request data valid JSON nathi."},
            status=400,
        )


@require_POST
def register_chatbot_user(request):
    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip().replace(" ", "")
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    confirm_password = str(data.get("confirm_password", ""))

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
    elif password != confirm_password:
        errors["confirm_password"] = "Password ane confirm password same nathi."

    User = get_user_model()

    email_exists = email and (
        User.objects.filter(email__iexact=email).exists()
        or User.objects.filter(username__iexact=email).exists()
    )
    phone_exists = phone and UserProfile.objects.filter(phone=phone).exists()

    if email_exists:
        errors["email"] = USER_EXISTS_MESSAGE

    if phone_exists:
        errors["phone"] = USER_EXISTS_MESSAGE

    if password and password == confirm_password:
        try:
            user_candidate = User(username=email, email=email, first_name=name)
            validate_password(password, user=user_candidate)
        except ValidationError as exc:
            errors["password"] = " ".join(exc.messages)

    if errors:
        return JsonResponse(
            {
                "success": False,
                "message": USER_EXISTS_MESSAGE
                if email_exists or phone_exists
                else next(iter(errors.values())),
                "errors": errors,
            },
            status=409 if email_exists or phone_exists else 400,
        )

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=name,
            )
            UserProfile.objects.create(user=user, phone=phone)
    except IntegrityError:
        return JsonResponse(
            {
                "success": False,
                "message": USER_EXISTS_MESSAGE,
                "errors": {"user": USER_EXISTS_MESSAGE},
            },
            status=409,
        )

    return JsonResponse(
        {
            "success": True,
            "message": "Registration complete thai gayu. Tamari details save thai gai che.",
        },
        status=201,
    )


@require_POST
def forgot_password_user(request):
    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    email = str(data.get("email", "")).strip().lower()
    if not email:
        return JsonResponse(
            {"success": False, "message": "Email required che."},
            status=400,
        )

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse(
            {"success": False, "message": "Email address valid nathi."},
            status=400,
        )

    User = get_user_model()
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        return JsonResponse(
            {"success": False, "message": "Aa email par user exist nathi."},
            status=404,
        )

    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_path = reverse(
        "password_reset_confirm",
        kwargs={"uidb64": uidb64, "token": token},
    )
    reset_url = (
        f"{settings.APP_BASE_URL.rstrip('/')}{reset_path}"
        if settings.APP_BASE_URL
        else request.build_absolute_uri(reset_path)
    )

    subject = "Password reset link"
    message = (
        f"Hello {user.first_name or user.username},\n\n"
        "Tamaru password reset karva niche ni link open karo:\n"
        f"{reset_url}\n\n"
        "Jo tame aa request na kari hoy to aa email ignore karo."
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        return JsonResponse(
            {
                "success": False,
                "message": "SMTP email send nathi thai. Email settings check karo.",
            },
            status=500,
        )

    return JsonResponse(
        {
            "success": True,
            "message": "Password reset link tamara email par mokli didhi che.",
        }
    )
