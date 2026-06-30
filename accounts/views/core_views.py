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


def favicon(request):
    return HttpResponse(status=204)


