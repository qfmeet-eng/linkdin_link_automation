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

from .models import LoginActivity, UserProfile, UserDetails, ScrapedProfile, LinkedInConfig
from django.utils import timezone

PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")
USER_EXISTS_MESSAGE = "User is already exist."
DATABASE_NOT_READY_MESSAGE = "Database tables missing che. Pehla python manage.py migrate run karo."


def chatbot_register_page(request):
    return render(request, "accounts/chatbot.html")


def chatbot_login_page(request):
    return render(request, "accounts/login.html")


def chatbot_forgot_password_page(request):
    return render(request, "accounts/forgot_password.html")


def favicon(request):
    return HttpResponse(status=204)


def parse_json_body(request):
    try:
        return json.loads(request.body.decode("utf-8")), None
    except (JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse(
            {"success": False, "message": "Request data valid JSON nathi."},
            status=400,
        )


def database_not_ready_response():
    return JsonResponse(
        {
            "success": False,
            "message": DATABASE_NOT_READY_MESSAGE,
            "errors": {"database": DATABASE_NOT_READY_MESSAGE},
        },
        status=500,
    )


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def create_login_activity(request, email, user=None, success=True, failure_reason=""):
    return LoginActivity.objects.create(
        user=user,
        email=email,
        success=success,
        failure_reason=failure_reason,
        ip_address=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000],
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

    # Grab LinkedIn picture URL if registration matches the LinkedIn session email
    linkedin_data = request.session.get("linkedin_user_data")
    picture_url = None
    if linkedin_data and linkedin_data.get("email", "").lower() == email:
        picture_url = linkedin_data.get("picture")

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=name,
            )
            UserProfile.objects.create(user=user, phone=phone)
            user_details = UserDetails.objects.create(
                user=user,
                name=name,
                email=email,
                phone=phone,
                profile_picture_url=picture_url,
            )
            
            # Log the user in directly after signup
            login(request, user)
            
            # Create login activity
            create_login_activity(
                request,
                email=user.email,
                user=user,
                success=True,
            )
            
            # Update last login info
            user_details.last_login = timezone.now()
            user_details.ip_address = get_client_ip(request)
            user_details.user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]
            user_details.save()
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
            "message": "Registration complete thai gayu. Tamari details save thai gai che.",
            "redirect_url": "/home/",
        },
        status=201,
    )


@require_POST
def login_chatbot_user(request):
    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    username_or_email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    errors = {}

    if not username_or_email:
        errors["email"] = "Username athva email required che."

    if not password:
        errors["password"] = "Password required che."

    if errors:
        return JsonResponse(
            {
                "success": False,
                "message": next(iter(errors.values())),
                "errors": errors,
            },
            status=400,
        )

    User = get_user_model()

    try:
        user = User.objects.filter(
            Q(email__iexact=username_or_email) | Q(username__iexact=username_or_email),
            is_active=True
        ).first()
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()

    if user:
        authenticated_user = authenticate(
            request,
            username=user.username,
            password=password,
        )
    else:
        authenticated_user = None

    try:
        if authenticated_user is None:
            create_login_activity(
                request,
                email=username_or_email,
                user=user,
                success=False,
                failure_reason="Invalid credentials",
            )
            return JsonResponse(
                {
                    "success": False,
                    "message": "Username/Email athva password khoto che.",
                    "errors": {"login": "Invalid credentials"},
                },
                status=401,
            )

        login(request, authenticated_user)
        create_login_activity(
            request,
            email=authenticated_user.email,
            user=authenticated_user,
            success=True,
        )

        phone_number = ""
        if hasattr(authenticated_user, 'profile'):
            phone_number = authenticated_user.profile.phone
        elif UserProfile.objects.filter(user=authenticated_user).exists():
            phone_number = UserProfile.objects.filter(user=authenticated_user).first().phone

        user_details, created = UserDetails.objects.get_or_create(
            user=authenticated_user,
            defaults={
                "name": authenticated_user.first_name or authenticated_user.username,
                "email": authenticated_user.email,
                "phone": phone_number,
            }
        )
        user_details.last_login = timezone.now()
        user_details.ip_address = get_client_ip(request)
        user_details.user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]
        user_details.save()
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()

    return JsonResponse(
        {
            "success": True,
            "message": "Login successful. Tamari login entry database ma save thai gai che.",
            "redirect_url": "/home/",
            "user": {
                "id": authenticated_user.id,
                "name": authenticated_user.first_name,
                "email": authenticated_user.email,
            },
        }
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
    try:
        user = User.objects.filter(email__iexact=email, is_active=True).first()
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()
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

    context = {
        "name": user.first_name or user.username,
        "reset_url": reset_url,
    }
    html_message = render_to_string("accounts/email_reset_password.html", context)

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
            html_message=html_message,
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


def home_view(request):
    user = request.user
    user_detail = None
    if user.is_authenticated:
        try:
            user_detail = UserDetails.objects.get(user=user)
        except UserDetails.DoesNotExist:
            user_detail = None
    return render(request, "accounts/home.html", {
        "user": user,
        "user_detail": user_detail,
    })


def chatbot_logout(request):
    logout(request)
    return redirect("chatbot_register")



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
def scrape_linkedin_view(request):
    """Accept a LinkedIn profile URL and return structured profile data via Gemini."""
    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    url = str(data.get("url", "")).strip()
    if not url:
        return JsonResponse(
            {"success": False, "message": "LinkedIn profile URL required che."},
            status=400,
        )

    if "linkedin.com" not in url.lower():
        return JsonResponse(
            {"success": False, "message": "Valid LinkedIn profile URL aapo (linkedin.com/in/...)."},
            status=400,
        )

    from .linkedin_scraper import get_linkedin_profile_data

    result = get_linkedin_profile_data(url)

    if result.get("error"):
        return JsonResponse(
            {"success": False, "message": result["error"]},
            status=500,
        )

    return JsonResponse({"success": True, "profile": result})



# ── LinkedIn OAuth 2.0 Views ──────────────────────────────────────────────────

def linkedin_oauth_start(request):
    """
    Step 1: User ne LinkedIn authorization page par redirect karo.
    GET /auth/linkedin/
    """
    from .linkedin_oauth import build_authorization_url

    # CSRF protection mate random state generate karo
    state = secrets.token_urlsafe(16)
    request.session["linkedin_oauth_state"] = state

    auth_url = build_authorization_url(state)
    return redirect(auth_url)


def linkedin_oauth_callback(request):
    """
    Step 2: LinkedIn callback — code exchange karo, userinfo fetch karo.
    GET /auth/linkedin/callback/?code=...&state=...
    """
    from .linkedin_oauth import get_linkedin_user_data

    # State verify karo
    returned_state = request.GET.get("state", "")
    saved_state    = request.session.pop("linkedin_oauth_state", "")
    if returned_state != saved_state:
        return JsonResponse(
            {"success": False, "message": "Invalid OAuth state. Please try again."},
            status=400,
        )

    # Error check (user ne denied karyun hoy)
    error = request.GET.get("error")
    if error:
        error_desc = request.GET.get("error_description", error)
        return redirect(f"/?linkedin_error={error_desc}")

    code = request.GET.get("code", "")
    if not code:
        return redirect("/?linkedin_error=No code received")

    # Code thi user data fetch karo
    user_data = get_linkedin_user_data(code)

    if "error" in user_data:
        return redirect(f"/?linkedin_error={user_data['error']}")

    # Check if a user with this email is already registered in our DB
    email = user_data.get("email", "").strip().lower()
    User = get_user_model()
    existing_user = User.objects.filter(email__iexact=email).first()

    if existing_user:
        # User is already registered! Log them in directly.
        login(request, existing_user)
        create_login_activity(
            request,
            email=existing_user.email,
            user=existing_user,
            success=True,
        )

        phone_number = ""
        if hasattr(existing_user, 'profile'):
            phone_number = existing_user.profile.phone
        elif UserProfile.objects.filter(user=existing_user).exists():
            phone_number = UserProfile.objects.filter(user=existing_user).first().phone

        user_details, created = UserDetails.objects.get_or_create(
            user=existing_user,
            defaults={
                "name": existing_user.first_name or existing_user.username,
                "email": existing_user.email,
                "phone": phone_number,
                "profile_picture_url": user_data.get("picture"),
            }
        )
        if not created and user_data.get("picture"):
            user_details.profile_picture_url = user_data.get("picture")
        user_details.last_login = timezone.now()
        user_details.ip_address = get_client_ip(request)
        user_details.user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]
        user_details.save()

        # Redirect directly to home
        return redirect("/home/")

    # Session ma store karo — chatbot page read karso
    request.session["linkedin_user_data"] = user_data
    return redirect("/?linkedin_auth=success")


def linkedin_userinfo_api(request):
    """
    GET /auth/linkedin/userinfo/
    Session ma thi LinkedIn user data JSON ma return karo — chatbot JS use karashe.
    """
    user_data = request.session.get("linkedin_user_data")
    if not user_data:
        return JsonResponse({"success": False, "message": "LinkedIn data session ma nathi."})
    return JsonResponse({"success": True, "profile": user_data})


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
def api_scrape_linkedin(request):
    """
    Accept a LinkedIn URL, run the automation scraper (with PDF download),
    save the structured data in ScrapedProfile model, and return it.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Log in required che."}, status=401)

    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    url = str(data.get("url", "")).strip()
    if not url:
        return JsonResponse(
            {"success": False, "message": "LinkedIn profile URL required che."},
            status=400,
        )

    if "linkedin.com" not in url.lower():
        return JsonResponse(
            {"success": False, "message": "Valid LinkedIn profile URL aapo (linkedin.com/in/...)."},
            status=400,
        )

    from .linkedin_scraper import get_linkedin_profile_data

    # Call scraper (will run selenium More -> Save to PDF logic)
    result = get_linkedin_profile_data(url)

    if result.get("error"):
        return JsonResponse(
            {"success": False, "message": result["error"]},
            status=500,
        )

    try:
        # Save into ScrapedProfile database model
        profile = ScrapedProfile.objects.create(
            user=request.user,
            url=url,
            name=result.get("name", ""),
            headline=result.get("headline", ""),
            location=result.get("location", ""),
            about=result.get("about", ""),
            experience=result.get("experience", []),
            education=result.get("education", []),
            skills=result.get("skills", []),
            raw_pdf_text=result.get("raw_pdf_text", ""),
        )

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
                "created_at": profile.created_at.strftime("%d %b %Y, %H:%M"),
            }
        })
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Database save error: {str(e)}"}, status=500)


def linkedin_assistant_view(request):
    """Render the LinkedIn Assistant chatbot interface (requires login)."""
    if not request.user.is_authenticated:
        return redirect("chatbot_login")
    return render(request, "accounts/linkedin_assistant.html")


def api_scraped_profiles_list(request):
    """Get list of previously scraped profiles for the current user."""
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Unauthorized"}, status=401)

    try:
        profiles = ScrapedProfile.objects.filter(user=request.user).order_by("-created_at")
        data = []
        for p in profiles:
            data.append({
                "id": p.id,
                "url": p.url,
                "name": p.name or "Unknown",
                "headline": p.headline or "No headline",
                "location": p.location or "",
                "created_at": p.created_at.strftime("%d %b %Y, %H:%M"),
            })
        return JsonResponse({"success": True, "profiles": data})
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()


@require_POST
def api_delete_scraped_profile(request, profile_id):
    """Delete a scraped profile."""
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Unauthorized"}, status=401)

    try:
        profile = ScrapedProfile.objects.filter(id=profile_id, user=request.user).first()
        if not profile:
            return JsonResponse({"success": False, "message": "Profile not found."}, status=404)
        profile.delete()
        return JsonResponse({"success": True, "message": "Profile successfully deleted."})
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()


def api_scraped_profile_detail(request, profile_id):
    """Get full details of a specific scraped profile for the current user."""
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Unauthorized"}, status=401)

    try:
        profile = ScrapedProfile.objects.filter(id=profile_id, user=request.user).first()
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
                "created_at": profile.created_at.strftime("%d %b %Y, %H:%M"),
            }
        })
    except (OperationalError, ProgrammingError):
        return database_not_ready_response()


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


@require_POST
def api_register_linkedin_scrape(request):
    """
    Scrape a LinkedIn profile URL for a new user registration.
    Store the parsed details in request.session['linkedin_reg_data'].
    POST /api/register/linkedin-scrape/
    """
    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    url = str(data.get("url", "")).strip()
    if not url:
        return JsonResponse(
            {"success": False, "message": "LinkedIn profile URL required che."},
            status=400,
        )

    if "linkedin.com" not in url.lower():
        return JsonResponse(
            {"success": False, "message": "Valid LinkedIn profile URL aapo (linkedin.com/in/...)."},
            status=400,
        )

    from .linkedin_scraper import get_linkedin_profile_data

    # Call scraper (will run selenium More -> Save to PDF logic)
    result = get_linkedin_profile_data(url)

    if result.get("error"):
        return JsonResponse(
            {"success": False, "message": result["error"]},
            status=500,
        )

    # Store in session for completing registration in the next step
    request.session["linkedin_reg_data"] = result

    # Return basic details to show in chatbot UI
    return JsonResponse({
        "success": True,
        "profile": {
            "url": url,
            "name": result.get("name", ""),
            "email": result.get("email", ""),
            "phone": result.get("phone", ""),
            "location": result.get("location", ""),
        }
    })


@require_POST
def api_register_linkedin_complete(request):
    """
    Complete registration using the scraped profile details from the session and user-supplied password.
    POST /api/register/linkedin-complete/
    """
    # Get temporary registration data from session
    reg_data = request.session.get("linkedin_reg_data")
    if not reg_data:
        return JsonResponse(
            {"success": False, "message": "LinkedIn profile details session ma nathi. Pehla profile scrape karo."},
            status=400,
        )

    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    # User-supplied details (email/phone can be supplied if missing from scraping)
    email = str(data.get("email", reg_data.get("email", ""))).strip().lower()
    phone = str(data.get("phone", reg_data.get("phone", ""))).strip().replace(" ", "")
    name = str(data.get("name", reg_data.get("name", ""))).strip()
    password = str(data.get("password", ""))
    confirm_password = str(data.get("confirm_password", ""))

    errors = {}

    if not name:
        errors["name"] = "Naam required che."

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
        errors["confirm_password"] = "Password same nathi."

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
                "message": USER_EXISTS_MESSAGE if email_exists or phone_exists else next(iter(errors.values())),
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
            user_details = UserDetails.objects.create(
                user=user,
                name=name,
                email=email,
                phone=phone,
            )
            
            # Save the full scraped profile data in ScrapedProfile model linked to this User!
            ScrapedProfile.objects.create(
                user=user,
                url=reg_data.get("url", ""),
                name=reg_data.get("name", name),
                headline=reg_data.get("headline", ""),
                location=reg_data.get("location", ""),
                about=reg_data.get("about", ""),
                experience=reg_data.get("experience", []),
                education=reg_data.get("education", []),
                skills=reg_data.get("skills", []),
                raw_pdf_text=reg_data.get("raw_pdf_text", ""),
            )
            
            # Log the user in directly
            login(request, user)
            
            # Create login activity
            create_login_activity(
                request,
                email=user.email,
                user=user,
                success=True,
            )
            
            # Update last login info
            user_details.last_login = timezone.now()
            user_details.ip_address = get_client_ip(request)
            user_details.user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]
            user_details.save()
            
            # Clear the session data
            request.session.pop("linkedin_reg_data", None)
            
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
            "message": "Registration complete thai gayu. Tamari details save thai gai che.",
            "redirect_url": "/home/",
        },
        status=201,
    )


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





