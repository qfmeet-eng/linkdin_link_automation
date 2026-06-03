"""
LinkedIn OAuth 2.0 helper functions.
Uses /userinfo endpoint to fetch: name, email, profile picture.
"""

import os
import secrets
import requests


LINKEDIN_AUTH_URL     = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL    = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

SCOPE = "openid profile email"


def get_client_id():
    return os.environ.get("LINKEDIN_CLIENT_ID", "")


def get_client_secret():
    return os.environ.get("LINKEDIN_CLIENT_SECRET", "")


def get_redirect_uri():
    return os.environ.get(
        "LINKEDIN_REDIRECT_URI",
        "http://127.0.0.1:8000/auth/linkedin/callback/"
    )


def build_authorization_url(state: str) -> str:
    """
    Build LinkedIn OAuth authorization URL.
    User ane redirect karva mate use karo.
    """
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id":     get_client_id(),
        "redirect_uri":  get_redirect_uri(),
        "state":         state,
        "scope":         SCOPE,
    }
    return f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    """
    Authorization code ne access token ma exchange karo.
    Returns: {"access_token": "...", "expires_in": 5183944, ...}
    Or on error: {"error": "..."}
    """
    data = {
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  get_redirect_uri(),
        "client_id":     get_client_id(),
        "client_secret": get_client_secret(),
    }

    try:
        resp = requests.post(
            LINKEDIN_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        result = resp.json()
        if "access_token" not in result:
            return {"error": result.get("error_description", str(result))}
        return result
    except Exception as e:
        return {"error": str(e)}


def fetch_userinfo(access_token: str) -> dict:
    """
    /userinfo endpoint thi user data fetch karo.
    Returns: {
        "sub": "...",            # LinkedIn user ID
        "name": "Dhruv Chavda",
        "given_name": "Dhruv",
        "family_name": "Chavda",
        "picture": "https://...",
        "email": "dhruv@example.com",
        "email_verified": true,
        "locale": {"country": "IN", "language": "en"}
    }
    Or on error: {"error": "..."}
    """
    try:
        resp = requests.get(
            LINKEDIN_USERINFO_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type":  "application/json",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"LinkedIn API error {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def get_linkedin_user_data(code: str) -> dict:
    """
    Full flow: code → token → userinfo
    Returns structured user data or {"error": "..."}
    """
    # Step 1: code → token
    token_data = exchange_code_for_token(code)
    if "error" in token_data:
        return {"error": f"Token error: {token_data['error']}"}

    access_token = token_data["access_token"]

    # Step 2: token → userinfo
    userinfo = fetch_userinfo(access_token)
    if "error" in userinfo:
        return {"error": f"Userinfo error: {userinfo['error']}"}

    # Step 3: Normalize fields
    return {
        "linkedin_id": userinfo.get("sub", ""),
        "name":        userinfo.get("name", ""),
        "first_name":  userinfo.get("given_name", ""),
        "last_name":   userinfo.get("family_name", ""),
        "email":       userinfo.get("email", ""),
        "picture":     userinfo.get("picture", ""),
        "locale":      userinfo.get("locale", {}),
    }
