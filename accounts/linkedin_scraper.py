"""
LinkedIn profile scraper using Selenium (with login) + Gemini AI.
"""

import os
import time
import json
import re
from django.conf import settings


def _get_driver():
    """Create and return a headless Chrome WebDriver using undetected-chromedriver."""
    import undetected_chromedriver as uc

    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    )
    driver = uc.Chrome(options=options, version_main=137, use_subprocess=True)
    return driver


def _linkedin_login(driver):
    """
    Inject li_at session cookie to authenticate with LinkedIn.
    Returns True if successful, False otherwise.
    """
    from selenium.webdriver.common.by import By

    li_at = os.environ.get("LINKEDIN_LI_AT", "").strip()
    if not li_at:
        return False

    try:
        # Step 1: Visit LinkedIn without any cookies first
        driver.get("https://www.linkedin.com/robots.txt")
        time.sleep(2)

        # Step 2: Delete all existing cookies
        driver.delete_all_cookies()
        time.sleep(1)

        # Step 3: Set li_at cookie
        driver.add_cookie({
            "name": "li_at",
            "value": li_at,
            "domain": ".linkedin.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        })
        time.sleep(1)

        # Step 4: Now visit the feed page
        driver.get("https://www.linkedin.com/feed/")
        time.sleep(4)

        current_url = driver.current_url
        print(f"[LinkedIn DEBUG] After login URL: {current_url}")

        # If still on login page or redirected to login, cookie is invalid
        if "login" in current_url or "authwall" in current_url:
            print("[LinkedIn DEBUG] Cookie invalid - redirected to login")
            return False

        if "feed" in current_url or "mynetwork" in current_url or "linkedin.com/in/" in current_url:
            print("[LinkedIn DEBUG] Login successful!")
            return True

        # Check page content
        body_text = driver.find_element(By.TAG_NAME, "body").text[:200]
        print(f"[LinkedIn DEBUG] Body preview: {body_text}")

        if "Sign in" in body_text or "Join now" in body_text:
            return False

        return True

    except Exception as e:
        print(f"[LinkedIn DEBUG] Login exception: {e}")
        return False


def _clean_text(text: str) -> str:
    """Remove extra whitespace from text."""
    return re.sub(r"\s+", " ", text or "").strip()


def scrape_linkedin_profile(profile_url: str) -> dict:
    """
    Login to LinkedIn and scrape a profile page.
    Returns a dict with raw scraped data or an error key.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException

    url = profile_url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    driver = None
    try:
        driver = _get_driver()

        # ── Login ──────────────────────────────────────────
        login_ok = _linkedin_login(driver)
        if not login_ok:
            return {
                "url": url,
                "error": "LinkedIn login failed. .env ma LINKEDIN_LI_AT cookie set karo.",
                "page_text": "",
            }

        # ── Load profile ───────────────────────────────────
        driver.get(url)
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "main"))
            )
        except TimeoutException:
            pass

        time.sleep(3)

        # Scroll down to load lazy sections
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        page_text = driver.find_element(By.TAG_NAME, "body").text

        # ── Extract fields ─────────────────────────────────
        def safe_text(*selectors):
            for sel in selectors:
                try:
                    return _clean_text(driver.find_element(By.CSS_SELECTOR, sel).text)
                except NoSuchElementException:
                    continue
            return ""

        name = safe_text(
            "h1.text-heading-xlarge",
            "h1",
            ".pv-text-details__left-panel h1",
        )

        headline = safe_text(
            ".text-body-medium.break-words",
            ".pv-text-details__left-panel .text-body-medium",
        )

        location = safe_text(
            ".text-body-small.inline.t-black--light.break-words",
            ".pv-text-details__left-panel span.text-body-small",
        )

        def safe_section(*selectors):
            for sel in selectors:
                try:
                    return _clean_text(driver.find_element(By.CSS_SELECTOR, sel).text)
                except NoSuchElementException:
                    continue
            return ""

        about = safe_section(
            "#about ~ .pvs-list__outer-container",
            "section[data-section='summary'] .pv-shared-text-with-see-more",
        )

        experience_text = safe_section(
            "#experience ~ .pvs-list__outer-container",
            "section[data-section='experience']",
        )

        education_text = safe_section(
            "#education ~ .pvs-list__outer-container",
            "section[data-section='education']",
        )

        skills_text = safe_section(
            "#skills ~ .pvs-list__outer-container",
            "section[data-section='skills']",
        )

        return {
            "url": url,
            "name": name,
            "headline": headline,
            "location": location,
            "about": about,
            "experience_raw": experience_text,
            "education_raw": education_text,
            "skills_raw": skills_text,
            "page_text": page_text[:12000],
            "error": None,
        }

    except Exception as exc:
        return {"url": url, "error": str(exc), "page_text": ""}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def parse_with_gemini(scraped: dict) -> dict:
    """
    Send scraped raw text to Gemini and get structured JSON back.
    """
    import google.generativeai as genai

    api_key = os.environ.get("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", "")
    if not api_key:
        return {"error": "GEMINI_API_KEY set nathi. .env file check karo."}

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")

    page_text = scraped.get("page_text", "")

    # If no structured fields extracted, use full page text
    name     = scraped.get("name", "") or ""
    headline = scraped.get("headline", "") or ""
    location = scraped.get("location", "") or ""
    about    = scraped.get("about", "") or ""
    exp_raw  = scraped.get("experience_raw", "") or ""
    edu_raw  = scraped.get("education_raw", "") or ""
    skills_raw = scraped.get("skills_raw", "") or ""

    prompt = f"""
You are a LinkedIn profile data extractor.
Below is the raw text content scraped from a LinkedIn profile page.
Extract ALL available information and return ONLY a valid JSON object.

Required JSON structure:
{{
  "name": "Full name",
  "headline": "Job title or professional headline",
  "location": "City, Country",
  "about": "About/Summary text",
  "experience": [
    {{
      "title": "Job title",
      "company": "Company name",
      "duration": "Date range",
      "description": "Role description if available"
    }}
  ],
  "education": [
    {{
      "degree": "Degree or course name",
      "school": "University or school name",
      "year": "Year or duration"
    }}
  ],
  "skills": ["skill1", "skill2"]
}}

Rules:
- Return ONLY the JSON object, nothing else
- No markdown, no code blocks, no explanation
- Use empty string "" for missing text fields
- Use empty array [] for missing list fields
- Extract as much data as possible from the text

--- STRUCTURED FIELDS (may be empty if selectors failed) ---
Name: {name}
Headline: {headline}
Location: {location}
About: {about}
Experience: {exp_raw[:2000]}
Education: {edu_raw[:1000]}
Skills: {skills_raw[:500]}

--- FULL PAGE TEXT (use this as primary source if above fields are empty) ---
{page_text[:6000]}
"""

    try:
        response = model.generate_content(prompt)
        raw_text = response.text.strip()

        # Strip markdown code fences if present
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)
        raw_text = raw_text.strip()

        data = json.loads(raw_text)
        data["url"] = scraped.get("url", "")
        return data

    except json.JSONDecodeError:
        # Return raw text for debugging
        return {
            "error": f"Gemini valid JSON nathi aapyo.",
            "raw": response.text[:300] if "response" in dir() else ""
        }
    except Exception as e:
        return {"error": f"Gemini API error: {str(e)}"}


def get_linkedin_profile_data(profile_url: str) -> dict:
    """
    Main entry: login to LinkedIn, scrape profile, parse via Gemini.
    """
    import logging
    logger = logging.getLogger(__name__)

    scraped = scrape_linkedin_profile(profile_url)

    if scraped.get("error"):
        return {"error": scraped["error"]}

    page_text = scraped.get("page_text", "").strip()

    # Log first 500 chars to Django console for debugging
    logger.warning(f"[LinkedIn] page_text preview: {page_text[:500]}")
    print(f"[LinkedIn DEBUG] page_text length: {len(page_text)}")
    print(f"[LinkedIn DEBUG] name: {scraped.get('name')}")
    print(f"[LinkedIn DEBUG] headline: {scraped.get('headline')}")
    print(f"[LinkedIn DEBUG] page_text[:300]: {page_text[:300]}")

    if not page_text:
        return {
            "error": "Profile page empty mili. LinkedIn login fail thayo hoi shake che."
        }

    return parse_with_gemini(scraped)
