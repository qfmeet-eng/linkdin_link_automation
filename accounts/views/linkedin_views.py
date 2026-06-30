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


def linkedin_oauth_start(request):
    """
    Step 1: User ne LinkedIn authorization page par redirect karo.
    GET /auth/linkedin/
    """
    from accounts.linkedin_oauth import build_authorization_url

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
    from accounts.linkedin_oauth import get_linkedin_user_data

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

    from accounts.linkedin_scraper import get_linkedin_profile_data

    result = get_linkedin_profile_data(url)

    if result.get("error"):
        return JsonResponse(
            {"success": False, "message": result["error"]},
            status=500,
        )

    return JsonResponse({"success": True, "profile": result})



# ── LinkedIn OAuth 2.0 Views ──────────────────────────────────────────────────

def linkedin_assistant_view(request):
    """Render the LinkedIn Assistant chatbot interface (requires login)."""
    if not request.user.is_authenticated:
        return redirect("chatbot_login")
    return render(request, "accounts/linkedin_assistant.html")


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

    from accounts.linkedin_scraper import get_linkedin_profile_data

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


