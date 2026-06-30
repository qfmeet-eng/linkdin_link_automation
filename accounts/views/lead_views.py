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
from rest_framework.decorators import api_view
from rest_framework.response import Response
import json
from django.http import JsonResponse
from accounts.lead_analyzer import (
    search_profiles_by_keyword,
    analyze_lead,
)
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")
USER_EXISTS_MESSAGE = "User is already exist."
DATABASE_NOT_READY_MESSAGE = "Database tables missing che. Pehla python manage.py migrate run karo."



def parse_json_body(request):
    try:
        data = json.loads(request.body or "{}")
        return data, None
    except json.JSONDecodeError:
        return None, JsonResponse(
            {
                "success": False,
                "message": "Invalid JSON body."
            },
            status=400
        )



def lead_dashboard_view(request):
    if not request.user.is_authenticated:
        return redirect("chatbot_login")

    try:
        leads = LeadActivity.objects.filter(user=request.user).order_by("-created_at")
        active_count   = leads.filter(activity_score="Active").count()
        moderate_count = leads.filter(activity_score="Moderately Active").count()
        inactive_count = leads.filter(activity_score="Inactive").count()
        total_leads    = leads.count()
    except Exception:
        leads = []
        active_count = moderate_count = inactive_count = total_leads = 0

    return render(request, "accounts/lead_dashboard.html", {
        "leads":          leads,
        "active_count":   active_count,
        "moderate_count": moderate_count,
        "inactive_count": inactive_count,
        "total_leads":    total_leads,
    })

@csrf_exempt
@require_POST
def api_start_lead_analysis(request):
    """
    POST /api/leads/analyze/
    Accepts a LinkedIn search result URL, spawns a background thread to process it,
    and returns immediately so the UI can poll for results.
    """
    # if not request.user.is_authenticated:
    #     return JsonResponse({"success": False, "message": "Login required."}, status=401)

    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    search_url = str(data.get("search_url", "")).strip()
    single_url = str(data.get("url", "")).strip()

    if not search_url and not single_url:
        return JsonResponse(
            {"success": False, "message": "LinkedIn search_url or url required."},
            status=400,
        )

    user_id = request.user.id if request.user.is_authenticated else 1

    if single_url:
        if "linkedin.com" not in single_url.lower():
            return JsonResponse({"success": False, "message": "Invalid LinkedIn URL."}, status=400)
        from accounts.lead_analyzer import analyze_lead
        from django.contrib.auth import get_user_model
        user_obj = request.user if request.user.is_authenticated else get_user_model().objects.first()
        try:
            result = analyze_lead(single_url, search_url="API Single Lead", user=user_obj)
            if "error" in result:
                return JsonResponse({"success": False, "message": result["error"]}, status=500)
            return JsonResponse({"success": True, "analyzed": 1, "message": "Profile analyzed successfully."})
        except Exception as e:
            return JsonResponse({"success": False, "message": str(e)}, status=500)

    if "linkedin.com" not in search_url.lower():
        return JsonResponse(
            {"success": False, "message": "Please provide a valid LinkedIn URL (linkedin.com/search/...)."},
            status=400,
        )

    # Run analysis synchronously so we can return actual results
    from accounts.lead_analyzer import run_lead_analysis_thread

    try:
        analyzed = run_lead_analysis_thread(search_url, user_id)
        return JsonResponse({
            "success": True,
            "analyzed": analyzed,
            "message": f"{analyzed} profile(s) analyzed successfully.",
        })
    except Exception as e:
        return JsonResponse({
            "success": False,
            "message": f"Analysis failed: {str(e)}",
        }, status=500)

@csrf_exempt
@require_POST
def api_search_linkedin_profiles(request):
    """
    POST /api/leads/search/
    Accepts a keyword, searches LinkedIn, returns list of profile URLs + basic info.
    """
    # if not request.user.is_authenticated:
    #     return JsonResponse({"success": False, "message": "Login required."}, status=401)

    data, err = parse_json_body(request)
    if err:
        return err

    keyword = str(data.get("keyword", "")).strip()
    if not keyword:
        return JsonResponse({"success": False, "message": "Keyword required."}, status=400)

    max_results = int(data.get("max_results", 50))

    from accounts.lead_analyzer import search_profiles_by_keyword
    try:
        profiles = search_profiles_by_keyword(keyword, max_results=max_results)
        return JsonResponse({"success": True, "profiles": profiles, "count": len(profiles)})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)

@csrf_exempt
@require_POST
def api_analyze_selected_profiles(request):
    """
    POST /api/leads/analyze-selected/
    Accepts a list of profile URLs, analyzes each, saves LeadActivity.
    Updates session with progress so frontend can poll.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Login required."}, status=401)

    data, err = parse_json_body(request)
    if err:
        return err

    profile_urls = data.get("profile_urls", [])
    keyword      = str(data.get("keyword", "")).strip()

    if not profile_urls:
        return JsonResponse({"success": False, "message": "No profiles selected."}, status=400)

    urls_to_process = profile_urls[:50]
    total = len(urls_to_process)

    # Reset progress in session and delete stop flag in cache
    request.session["analyze_progress"] = {"done": 0, "total": total, "current": ""}
    request.session.save()

    from django.core.cache import cache
    cache_key = f"stop_analysis_{request.user.id}"
    cache.delete(cache_key)

    from accounts.lead_analyzer import analyze_lead
    results = []

    for i, url in enumerate(urls_to_process):
        # Check if stop requested
        if cache.get(cache_key):
            cache.delete(cache_key)
            break

        # Update progress
        name_hint = url.split("/in/")[-1].strip("/").replace("-", " ").title()[:30]
        request.session["analyze_progress"] = {
            "done": i,
            "total": total,
            "current": name_hint,
        }
        request.session.save()

        try:
            from django.contrib.auth import get_user_model
            user_obj = request.user if request.user.is_authenticated else get_user_model().objects.first()
            result = analyze_lead(url, search_url=keyword, user=user_obj)
            if "error" in result:
                results.append({"url": url, "error": result["error"]})
            else:
                lead = result["lead"]
                results.append({
                    "url":            url,
                    "name":           lead.name,
                    "activity_score": lead.activity_score,
                    "posts_count":    lead.posts_count,
                    "comments_count": lead.comments_count,
                    "reposts_count":  lead.reposts_count,
                    "lead_id":        lead.id,
                })
        except Exception as e:
            results.append({"url": url, "error": str(e)})

    # Mark complete
    request.session["analyze_progress"] = {"done": total, "total": total, "current": ""}
    request.session.modified = True

    analyzed = sum(1 for r in results if "error" not in r)
    return JsonResponse({"success": True, "results": results, "analyzed": analyzed})

@csrf_exempt
def api_analyze_progress(request):
    """GET /api/leads/progress/ — returns current analysis progress from session."""
    if not request.user.is_authenticated:
        return JsonResponse({"done": 0, "total": 0, "current": ""})
    progress = request.session.get("analyze_progress", {"done": 0, "total": 0, "current": ""})
    return JsonResponse(progress)

@csrf_exempt
@require_POST
def api_stop_lead_analysis(request):
    """POST /api/leads/stop-analysis/ — signals the running loop to break early."""
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Login required."}, status=401)
    
    from django.core.cache import cache
    cache_key = f"stop_analysis_{request.user.id}"
    cache.set(cache_key, True, 60) # Set flag for 60 seconds
    
    return JsonResponse({"success": True, "message": "Stop signal sent."})

@csrf_exempt
def api_leads_list(request):
    """
    GET /api/leads/
    Returns the authenticated user's LeadActivity records as JSON.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Login required."}, status=401)

    try:
        leads = LeadActivity.objects.filter(user=request.user).order_by("-created_at")
        data = []
        for lead in leads:
            data.append({
                "id": lead.id,
                "name": lead.name or "Unknown",
                "headline": lead.headline or "",
                "location": lead.location or "",
                "profile_url": lead.profile_url,
                "search_url": lead.search_url or "",
                "last_activity_date": lead.last_activity_date or "—",
                "posts_count": lead.posts_count,
                "comments_count": lead.comments_count,
                "reposts_count": lead.reposts_count,
                "activity_score": lead.activity_score,
                "summary": lead.summary or "",
                "created_at": lead.created_at.strftime("%d %b %Y, %H:%M") if lead.created_at else "",
            })
        return JsonResponse({"success": True, "leads": data, "count": len(data)})
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Error: {str(e)}"}, status=500)

@csrf_exempt
def api_lead_detail(request, lead_id):
    """
    GET /api/leads/<id>/
    Returns full details of one LeadActivity.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Login required."}, status=401)

    try:
        lead = LeadActivity.objects.filter(id=lead_id, user=request.user).first()
        if not lead:
            return JsonResponse({"success": False, "message": "Lead not found."}, status=404)
        return JsonResponse({
            "success": True,
            "lead": {
                "id": lead.id,
                "name": lead.name or "Unknown",
                "headline": lead.headline or "",
                "location": lead.location or "",
                "profile_url": lead.profile_url,
                "search_url": lead.search_url or "",
                "last_activity_date": lead.last_activity_date or "—",
                "posts_count": lead.posts_count,
                "comments_count": lead.comments_count,
                "reposts_count": lead.reposts_count,
                "activity_score": lead.activity_score,
                "summary": lead.summary or "",
                "created_at": lead.created_at.strftime("%d %b %Y, %H:%M") if lead.created_at else "",
            }
        })
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Error: {str(e)}"}, status=500)

@csrf_exempt
@require_POST
def api_delete_lead(request, lead_id):
    """
    POST /api/leads/<id>/delete/
    Deletes a LeadActivity record belonging to the authenticated user.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Login required."}, status=401)

    try:
        lead = LeadActivity.objects.filter(id=lead_id, user=request.user).first()
        if not lead:
            return JsonResponse({"success": False, "message": "Lead not found."}, status=404)
        lead.delete()
        return JsonResponse({"success": True, "message": "Lead deleted successfully."})
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Error: {str(e)}"}, status=500)

@csrf_exempt
@require_POST
def api_bulk_delete_leads(request):
    """
    POST /api/leads/bulk-delete/
    Deletes multiple LeadActivity records belonging to the authenticated user.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "message": "Login required."}, status=401)

    data, error_response = parse_json_body(request)
    if error_response:
        return error_response

    lead_ids = data.get("lead_ids", [])
    if not lead_ids:
        return JsonResponse({"success": False, "message": "No lead IDs provided."}, status=400)

    try:
        deleted_count, _ = LeadActivity.objects.filter(id__in=lead_ids, user=request.user).delete()
        return JsonResponse({
            "success": True,
            "message": f"Successfully deleted {deleted_count} lead(s)."
        })
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Error: {str(e)}"}, status=500)

@csrf_exempt
@api_view(["POST"])
def run_complete_workflow(request):

    keyword = request.data.get("keyword")
    max_results = int(request.data.get("max_results", 50))

    profiles = search_profiles_by_keyword(keyword, max_results)

    results = []

    for profile in profiles:

        result = analyze_lead(
            profile["url"],
            search_url=keyword,
            user=request.user
        )

        if "lead" in result:
            results.append(result["lead"])

        return Response({
        "success": True,
        "keyword": keyword,
        "total_profiles": len(profiles),
        "active_profiles": len(results),
        "profiles": [
            {
                "name": lead.name,
                "profile_url": lead.profile_url,
                "activity_score": lead.activity_score,
                "posts": lead.posts_count,
                "comments": lead.comments_count,
                "reposts": lead.reposts_count,
            }
            for lead in results
        ]
    })