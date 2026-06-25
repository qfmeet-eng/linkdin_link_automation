"""
LinkedIn Lead Activity Analyzer Service.

Uses existing _get_driver, _linkedin_login from linkedin_scraper.py.
Extracts activity data from the last 30 days for each profile.
"""

import os
import re
import json
import time
from datetime import datetime, timedelta
from django.conf import settings
from .linkedin_scraper import _get_driver, _linkedin_login, _get_gemini_api_keys


# ── Activity Scoring ────────────────────────────────────────────────────────

def compute_activity_score(posts: int, comments: int, reposts: int) -> str:
    total = posts + comments + reposts
    if total >= 5:
        return "Active"
    elif total >= 1:
        return "Moderately Active"
    return "Inactive"


# ── Extract Profile URLs from Search Results ────────────────────────────────

def extract_profile_urls_from_search(search_url: str, max_pages: int = 5, max_profiles: int = 50) -> list:
    """
    Visit a LinkedIn search result page and extract all /in/ profile URLs across multiple pages.
    Returns a list of unique profile URLs.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    driver = None
    profile_urls = []
    seen = set()
    try:
        driver = _get_driver()
        login_ok = _linkedin_login(driver)
        if not login_ok:
            return []

        for page_num in range(1, max_pages + 1):
            if len(profile_urls) >= max_profiles:
                break
                
            if page_num == 1:
                current_url = search_url
            else:
                if "&page=" in search_url:
                    current_url = re.sub(r"&page=\d+", f"&page={page_num}", search_url)
                else:
                    connector = "&" if "?" in search_url else "?"
                    current_url = search_url + f"{connector}page={page_num}"
            
            print(f"[LeadAnalyzer] Scraping search page {page_num}: {current_url}")
            driver.get(current_url)
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/in/']"))
                )
            except TimeoutException:
                pass

            time.sleep(3)

            # Scroll to load more results
            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.5)

            # Extract all /in/ links
            anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/in/']")
            new_links_found = False
            for a in anchors:
                href = a.get_attribute("href") or ""
                # Normalize: keep only /in/username part
                m = re.search(r"(https://www\.linkedin\.com/in/[^/?&#]+)", href)
                if m:
                    clean_url = m.group(1).rstrip("/") + "/"
                    if clean_url not in seen:
                        seen.add(clean_url)
                        profile_urls.append(clean_url)
                        new_links_found = True
                        
            if not new_links_found:
                print(f"[LeadAnalyzer] No new profiles found on page {page_num}, stopping pagination.")
                break

    except Exception as e:
        print(f"[LeadAnalyzer] extract_profile_urls error: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return profile_urls[:max_profiles]


# ── Scrape Activity Data from a Single Profile ──────────────────────────────

def scrape_profile_activity(profile_url: str) -> dict:
    """
    Visit a LinkedIn profile and extract activity signals.
    Uses profile page + Gemini to determine activity status.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException

    url = profile_url.strip().rstrip("/") + "/"

    driver = None
    try:
        driver = _get_driver()
        login_ok = _linkedin_login(driver)
        if not login_ok:
            return {"error": "LinkedIn login failed", "profile_url": url}

        # ── Visit profile page ──────────────────────────────
        driver.get(url)
        try:
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.TAG_NAME, "main"))
            )
        except TimeoutException:
            pass
        time.sleep(2)

        # Scroll down to load more content
        for _ in range(4):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

        page_text = driver.find_element(By.TAG_NAME, "body").text

        def safe(selector):
            try:
                return driver.find_element(By.CSS_SELECTOR, selector).text.strip()
            except NoSuchElementException:
                return ""

        name     = safe("h1.text-heading-xlarge") or safe("h1")
        headline = safe(".text-body-medium.break-words")
        location = safe(".text-body-small.inline.t-black--light.break-words")

        # ── Try recent activity page ────────────────────────
        activity_url = url + "recent-activity/all/"
        activity_text = ""
        try:
            driver.get(activity_url)
            time.sleep(3)
            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
            act_body = driver.find_element(By.TAG_NAME, "body").text
            # Only use if it looks like real content (not login wall)
            if len(act_body) > 200 and "Sign in" not in act_body[:300]:
                activity_text = act_body
                print(f"[LeadActivity] Got {len(activity_text)} chars from activity page")
        except Exception as ae:
            print(f"[LeadActivity] Activity page failed: {ae}")

        # ── Use Gemini to determine activity ───────────────
        combined_text = (activity_text or page_text)[:6000]
        posts_count, comments_count, reposts_count, last_activity = _gemini_activity_analysis(
            name, headline, combined_text
        )

        return {
            "profile_url":    url,
            "name":           name,
            "headline":       headline,
            "location":       location,
            "last_activity":  last_activity,
            "posts_count":    posts_count,
            "comments_count": comments_count,
            "reposts_count":  reposts_count,
            "error":          None,
        }

    except Exception as e:
        return {"profile_url": url, "error": str(e)}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _gemini_activity_analysis(name: str, headline: str, page_text: str) -> tuple:
    """
    Use Gemini to extract activity counts from page text.
    Returns (posts, comments, reposts, last_activity_date)
    """
    import google.generativeai as genai
    import json as _json

    api_keys = _get_gemini_api_keys()
    if not api_keys or not page_text.strip():
        # Fallback: count keywords in text
        text_lower = page_text.lower()
        posts    = min(len(re.findall(r'\b(posted|published|shared a post|wrote)\b', text_lower)), 20)
        comments = min(len(re.findall(r'\b(commented|replied|response)\b', text_lower)), 20)
        reposts  = min(len(re.findall(r'\b(repost|reshared|reposted)\b', text_lower)), 20)
        return posts, comments, reposts, ""

    prompt = f"""
You are analyzing a LinkedIn profile page text to determine the user's activity level.

Profile: {name}
Headline: {headline}

Page text (may include recent activity feed):
{page_text[:4000]}

Based on this text, estimate:
1. How many posts has this person made in the last 30 days? (0 if none visible)
2. How many comments? (0 if none visible)  
3. How many reposts/reshares? (0 if none visible)
4. When was their last visible activity? (date string or empty)

Return ONLY this JSON, no explanation:
{{"posts": 0, "comments": 0, "reposts": 0, "last_activity": ""}}

Important:
- If the page shows recent posts/articles/updates from this person, count them
- If only profile info is visible (no activity feed), return 0s
- Be generous: if you see ANY signs of posting/commenting, count them
"""

    for api_key in api_keys:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(prompt)
            raw = response.text.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw).strip()
            data = _json.loads(raw)
            return (
                int(data.get("posts", 0)),
                int(data.get("comments", 0)),
                int(data.get("reposts", 0)),
                str(data.get("last_activity", "")),
            )
        except Exception as e:
            print(f"[GeminiActivity] Key failed: {e}")
            continue

    # Fallback to regex
    text_lower = page_text.lower()
    posts    = min(len(re.findall(r'\b(posted|published|shared a post)\b', text_lower)), 10)
    comments = min(len(re.findall(r'\b(commented|replied)\b', text_lower)), 10)
    reposts  = min(len(re.findall(r'\b(repost|reshared)\b', text_lower)), 10)
    return posts, comments, reposts, ""


# ── Gemini Lead Qualification Summary ──────────────────────────────────────

def generate_lead_summary(activity_data: dict) -> str:
    """
    Use Gemini to generate a lead qualification summary based on activity data.
    """
    import google.generativeai as genai

    api_keys = _get_gemini_api_keys()
    if not api_keys:
        return "Gemini API key not configured."

    prompt = f"""
You are a B2B sales intelligence assistant.
Based on the following LinkedIn activity data, write a concise lead qualification summary (3-5 sentences).

Profile: {activity_data.get('name', 'Unknown')}
Headline: {activity_data.get('headline', '')}
Location: {activity_data.get('location', '')}
Activity Score: {activity_data.get('activity_score', 'Inactive')}
Posts (last 30 days): {activity_data.get('posts_count', 0)}
Comments (last 30 days): {activity_data.get('comments_count', 0)}
Reposts (last 30 days): {activity_data.get('reposts_count', 0)}
Last Activity: {activity_data.get('last_activity', 'Unknown')}

Write:
1. Engagement assessment
2. Lead quality rating
3. Recommended outreach approach

Keep it professional and actionable. Plain text only.
"""

    last_error = ""
    for idx, api_key in enumerate(api_keys):
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            last_error = str(e)
            print(f"[Gemini Lead] Key {idx+1} failed: {last_error}")

    return f"Summary generation failed: {last_error}"


# ── Full Pipeline for One Profile ───────────────────────────────────────────

def analyze_lead(profile_url: str, search_url: str = "", user=None) -> dict:
    """
    Full pipeline: scrape activity → score → Gemini summary → save to DB.
    Returns the LeadActivity instance or error dict.
    """
    from .models import LeadActivity

    data = scrape_profile_activity(profile_url)

    if data.get("error"):
        return {"error": data["error"]}

    score   = compute_activity_score(
        data.get("posts_count", 0),
        data.get("comments_count", 0),
        data.get("reposts_count", 0),
    )
    data["activity_score"] = score

    summary = generate_lead_summary(data)

    lead = LeadActivity.objects.create(
        user=user,
        search_url=search_url,
        profile_url=data.get("profile_url", profile_url),
        name=data.get("name", ""),
        headline=data.get("headline", ""),
        location=data.get("location", ""),
        last_activity_date=data.get("last_activity", ""),
        posts_count=data.get("posts_count", 0),
        comments_count=data.get("comments_count", 0),
        reposts_count=data.get("reposts_count", 0),
        activity_score=score,
        summary=summary,
    )

    return {"lead": lead, "data": data}


# ── Background Thread Runner ────────────────────────────────────────────────

def run_lead_analysis_thread(search_url: str, user_id: int):
    """
    Background thread entry point.
    1. Extract all profile URLs from search page.
    2. Analyze each profile and save LeadActivity to DB.
    """
    import django
    from django.contrib.auth import get_user_model

    try:
        User = get_user_model()
        user = User.objects.get(id=user_id)
    except Exception as e:
        print(f"[LeadThread] Could not get user {user_id}: {e}")
        user = None

    print(f"[LeadThread] Starting analysis for: {search_url}")

    # Step 1: Extract profile URLs
    profile_urls = extract_profile_urls_from_search(search_url)
    print(f"[LeadThread] Found {len(profile_urls)} profiles")

    if not profile_urls:
        # If no URLs found from search page, treat search_url itself as a profile URL
        if "/in/" in search_url:
            profile_urls = [search_url]
        else:
            print("[LeadThread] No profiles found and URL is not a profile URL.")
            return 0

    analyzed = 0
    for url in profile_urls[:50]:  # cap at 50 per run
        try:
            result = analyze_lead(url, search_url=search_url, user=user)
            if "error" in result:
                print(f"[LeadThread] Failed {url}: {result['error']}")
            else:
                analyzed += 1
                print(f"[LeadThread] Analyzed {url} → {result['lead'].activity_score}")
        except Exception as e:
            print(f"[LeadThread] Exception for {url}: {e}")

    print(f"[LeadThread] Done. Analyzed {analyzed} profiles.")
    return analyzed


# ── Keyword-based Profile Search ────────────────────────────────────────────

def search_profiles_by_keyword(keyword: str, max_results: int = 50) -> list:
    """
    Search LinkedIn for people using a keyword.
    Uses multiple search URL variations to get more results.
    Returns list of dicts: {url, name, headline, location}
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    from urllib.parse import quote

    driver = None
    profiles = []
    seen_urls = set()

    # Build multiple search URLs to bypass the ~10 result limit
    # LinkedIn shows different results for different network/connection filters
    search_urls = [
        f"https://www.linkedin.com/search/results/people/?keywords={quote(keyword)}&origin=GLOBAL_SEARCH_HEADER",
        f"https://www.linkedin.com/search/results/people/?keywords={quote(keyword)}&page=2",
        f"https://www.linkedin.com/search/results/people/?keywords={quote(keyword)}&page=3",
        f"https://www.linkedin.com/search/results/people/?keywords={quote(keyword)}&page=4",
        f"https://www.linkedin.com/search/results/people/?keywords={quote(keyword)}&page=5",
        f"https://www.linkedin.com/search/results/people/?keywords={quote(keyword)}&page=6",
    ]

    try:
        driver = _get_driver()
        login_ok = _linkedin_login(driver)
        if not login_ok:
            raise Exception("LinkedIn login failed. Check LINKEDIN_LI_AT cookie.")

        for search_url in search_urls:
            if len(profiles) >= max_results:
                break

            print(f"[LeadSearch] Fetching: {search_url}")
            driver.get(search_url)

            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR,
                        ".reusable-search__result-container, .entity-result, "
                        ".search-results-container, main"
                    ))
                )
            except TimeoutException:
                pass
            time.sleep(3)

            # Scroll to load all cards
            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.5)

            # Check for no results
            body_text = driver.find_element(By.TAG_NAME, "body").text
            if "No results found" in body_text or "0 results" in body_text.lower():
                print(f"[LeadSearch] No results on this URL, skipping.")
                continue

            # Extract profile cards
            cards = []
            for sel in [
                ".reusable-search__result-container",
                ".entity-result",
                "li.reusable-search__result-container",
                ".search-result__info",
            ]:
                cards = driver.find_elements(By.CSS_SELECTOR, sel)
                if cards:
                    print(f"[LeadSearch] Found {len(cards)} cards with selector: {sel}")
                    break

            # Fallback: extract all /in/ links directly
            if not cards:
                print(f"[LeadSearch] No cards found, trying anchor fallback")
                anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/in/']")
                new_count = 0
                for a in anchors:
                    href = a.get_attribute("href") or ""
                    m = re.search(r"(https://www\.linkedin\.com/in/[^/?&#]+)", href)
                    if m:
                        url = m.group(1).rstrip("/") + "/"
                        if url not in seen_urls and "/search/" not in url:
                            seen_urls.add(url)
                            name = a.text.strip()
                            if name and len(name) > 2:
                                profiles.append({"url": url, "name": name, "headline": "", "location": ""})
                                new_count += 1
                print(f"[LeadSearch] Anchor fallback got {new_count} new profiles")
                continue

            new_count = 0
            for card in cards:
                try:
                    url = ""
                    for link_sel in ["a.app-aware-link[href*='/in/']", "a[href*='/in/']"]:
                        try:
                            link = card.find_element(By.CSS_SELECTOR, link_sel)
                            href = link.get_attribute("href") or ""
                            m = re.search(r"(https://www\.linkedin\.com/in/[^/?&#]+)", href)
                            if m:
                                url = m.group(1).rstrip("/") + "/"
                                break
                        except NoSuchElementException:
                            pass

                    if not url or url in seen_urls or "/search/" in url:
                        continue
                    seen_urls.add(url)

                    name = ""
                    for name_sel in [
                        ".entity-result__title-text a span[aria-hidden='true']",
                        ".app-aware-link span[aria-hidden='true']",
                        ".entity-result__title-line span",
                    ]:
                        try:
                            name = card.find_element(By.CSS_SELECTOR, name_sel).text.strip()
                            if name:
                                break
                        except NoSuchElementException:
                            pass

                    headline = ""
                    for hl_sel in [".entity-result__primary-subtitle", ".entity-result__summary"]:
                        try:
                            headline = card.find_element(By.CSS_SELECTOR, hl_sel).text.strip()
                            if headline:
                                break
                        except NoSuchElementException:
                            pass

                    location = ""
                    try:
                        location = card.find_element(By.CSS_SELECTOR, ".entity-result__secondary-subtitle").text.strip()
                    except NoSuchElementException:
                        pass

                    profiles.append({
                        "url": url,
                        "name": name or "Unknown",
                        "headline": headline,
                        "location": location,
                    })
                    new_count += 1

                    if len(profiles) >= max_results:
                        break

                except Exception as e:
                    print(f"[LeadSearch] Card parse error: {e}")
                    continue

            print(f"[LeadSearch] Got {new_count} new profiles. Total: {len(profiles)}")
            time.sleep(2)  # polite delay

    except Exception as e:
        print(f"[LeadSearch] Error: {e}")
        raise
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    print(f"[LeadSearch] Final total: {len(profiles)} profiles (returning {min(len(profiles), max_results)})")
    return profiles[:max_results]
