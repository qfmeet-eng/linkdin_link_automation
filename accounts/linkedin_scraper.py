"""
LinkedIn profile scraper using Selenium (with login) + Gemini AI.
"""

import os
import time
import json
import re
from django.conf import settings


def _get_driver(download_dir=None):
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
    if download_dir:
        prefs = {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True
        }
        options.add_experimental_option("prefs", prefs)

    driver = uc.Chrome(options=options, version_main=137, use_subprocess=True)
    return driver



def _get_linkedin_cookie():
    try:
        from accounts.models import LinkedInConfig
        config = LinkedInConfig.objects.first()
        if config and config.li_at_cookie.strip():
            return config.li_at_cookie.strip()
    except Exception as e:
        print(f"[LinkedIn Scraper] Error reading cookie from DB: {e}")
    return os.environ.get("LINKEDIN_LI_AT", "").strip()


def _linkedin_login(driver):
    """
    Inject li_at session cookie to authenticate with LinkedIn.
    Returns True if successful, False otherwise.
    """
    from selenium.webdriver.common.by import By

    li_at = _get_linkedin_cookie()
    if not li_at:
        return False

    try:
        # Step 1: Visit LinkedIn homepage first to let it set default cookies (bcookie, bscookie, etc.)
        driver.get("https://www.linkedin.com")
        time.sleep(3)

        # Step 2: Add/Overwrite only the li_at cookie
        driver.add_cookie({
            "name": "li_at",
            "value": li_at,
            "domain": ".linkedin.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        })
        time.sleep(1)

        # Step 3: Load feed page to establish session
        driver.get("https://www.linkedin.com/feed/")
        time.sleep(4)

        current_url = driver.current_url
        print(f"[LinkedIn DEBUG] After login URL: {current_url}")

        body_text = ""
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            pass

        # Step 4: Handle redirect loops or blank error pages
        if "redirected you too many times" in body_text or "ERR_TOO_MANY_REDIRECTS" in body_text or not body_text.strip():
            print("[LinkedIn DEBUG] Redirect loop detected. Retrying with clean session...")
            driver.delete_all_cookies()
            time.sleep(1)
            driver.get("https://www.linkedin.com/robots.txt")
            time.sleep(2)
            driver.add_cookie({
                "name": "li_at",
                "value": li_at,
                "domain": ".linkedin.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            })
            time.sleep(2)
            driver.get("https://www.linkedin.com/feed/")
            time.sleep(4)
            current_url = driver.current_url
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                body_text = ""

        # Check if redirected to login or captcha walls
        if "login" in current_url or "authwall" in current_url or "Sign in" in body_text or "Join now" in body_text:
            print("[LinkedIn DEBUG] Cookie invalid - redirected to login/authwall")
            return False

        print("[LinkedIn DEBUG] Login successful!")
        return True

    except Exception as e:
        print(f"[LinkedIn DEBUG] Login exception: {e}")
        return False


def _clean_text(text: str) -> str:
    """Remove extra whitespace from text."""
    return re.sub(r"\s+", " ", text or "").strip()


def scrape_linkedin_profile(profile_url: str) -> dict:
    """
    Login to LinkedIn, scrape profile page, click More -> Save to PDF,
    download PDF, extract text using PyMuPDF, and fall back to HTML scraping if it fails.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    import glob

    url = profile_url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    # Configure temporary downloads folder
    download_dir = os.path.abspath(os.path.join(settings.BASE_DIR, "tmp_downloads"))
    os.makedirs(download_dir, exist_ok=True)

    # Clean existing PDFs to avoid reading old profiles
    for filename in os.listdir(download_dir):
        if filename.endswith(".pdf") or filename.endswith(".crdownload"):
            try:
                os.remove(os.path.join(download_dir, filename))
            except Exception:
                pass

    driver = None
    pdf_downloaded = False
    raw_pdf_text = ""

    try:
        driver = _get_driver(download_dir)

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

        # ── Click More -> Save to PDF ──────────────────────
        try:
            print("[LinkedIn Scraper] Attempting PDF download automation...")
            more_button = None
            more_xpaths = [
                "//button[contains(@class, 'artdeco-dropdown__trigger')][contains(., 'More')]",
                "//button[contains(., 'More')]",
                "//span[text()='More']/parent::button",
                "//button[contains(@aria-label, 'More actions')]"
            ]
            for xpath in more_xpaths:
                try:
                    more_button = driver.find_element(By.XPATH, xpath)
                    if more_button.is_displayed():
                        print(f"[LinkedIn Scraper] Found More button with XPath: {xpath}")
                        break
                except NoSuchElementException:
                    continue

            if more_button:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", more_button)
                time.sleep(1)
                more_button.click()
                print("[LinkedIn Scraper] Clicked More button")
                time.sleep(2)

                pdf_button = None
                pdf_xpaths = [
                    "//span[contains(text(), 'Save to PDF')]",
                    "//div[contains(., 'Save to PDF')]",
                    "//*[contains(text(), 'Save to PDF')]"
                ]
                for xpath in pdf_xpaths:
                    try:
                        pdf_button = driver.find_element(By.XPATH, xpath)
                        if pdf_button.is_displayed():
                            print(f"[LinkedIn Scraper] Found Save to PDF button with XPath: {xpath}")
                            break
                    except NoSuchElementException:
                        continue

                if pdf_button:
                    pdf_button.click()
                    print("[LinkedIn Scraper] Clicked Save to PDF button")
                    
                    # Wait for download to finish
                    download_success = False
                    for attempt in range(15):
                        time.sleep(1)
                        pdf_files = glob.glob(os.path.join(download_dir, "*.pdf"))
                        crdownload_files = glob.glob(os.path.join(download_dir, "*.crdownload"))
                        
                        if pdf_files and not crdownload_files:
                            latest_file = max(pdf_files, key=os.path.getmtime)
                            if os.path.getsize(latest_file) > 1000:
                                print(f"[LinkedIn Scraper] PDF download complete: {latest_file}")
                                
                                import fitz  # PyMuPDF
                                doc = fitz.open(latest_file)
                                temp_text = ""
                                for page in doc:
                                    temp_text += page.get_text()
                                doc.close()
                                
                                if temp_text.strip():
                                    raw_pdf_text = temp_text
                                    pdf_downloaded = True
                                    download_success = True
                                    print(f"[LinkedIn Scraper] Successfully extracted {len(raw_pdf_text)} characters from PDF.")
                                
                                try:
                                    os.remove(latest_file)
                                except Exception as e:
                                    print(f"[LinkedIn Scraper] Error deleting file: {e}")
                                break
                    if not download_success:
                        print("[LinkedIn Scraper] PDF download timed out or was incomplete.")
                else:
                    print("[LinkedIn Scraper] Save to PDF button not found in dropdown.")
            else:
                print("[LinkedIn Scraper] More button not found.")
        except Exception as pdf_exc:
            print(f"[LinkedIn Scraper] PDF automation failed: {pdf_exc}")

        # ── Extract HTML fields (as fallback / secondary source) ─────
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
            "raw_pdf_text": raw_pdf_text,
            "pdf_downloaded": pdf_downloaded,
            "error": None,
        }

    except Exception as exc:
        return {"url": url, "error": str(exc), "page_text": "", "raw_pdf_text": "", "pdf_downloaded": False}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _get_gemini_api_keys() -> list:
    keys = []
    def clean_key(val):
        if not val:
            return ""
        return val.strip().strip(",").strip('"').strip("'").strip()

    # 1. Try GEMINI_API_KEYS (comma separated list)
    keys_str = os.environ.get("GEMINI_API_KEYS", "") or getattr(settings, "GEMINI_API_KEYS", "")
    if keys_str:
        for rk in keys_str.split(","):
            cleaned = clean_key(rk)
            if cleaned:
                keys.append(cleaned)
    
    # 2. Try individual keys: GEMINI_API_KEY, GEMINI_API_KEY_2, etc.
    if not keys:
        for suffix in ["", "_2", "_3", "_4", "_5"]:
            k = os.environ.get(f"GEMINI_API_KEY{suffix}") or getattr(settings, f"GEMINI_API_KEY{suffix}", "")
            cleaned = clean_key(k)
            if cleaned:
                keys.append(cleaned)
                
    return keys


def parse_with_gemini(scraped: dict) -> dict:
    """
    Send scraped raw text to Gemini and get structured JSON back.
    Falls back to alternative API keys if rate limits or quota is exceeded.
    """
    import google.generativeai as genai

    api_keys = _get_gemini_api_keys()
    if not api_keys:
        return {"error": "GEMINI_API_KEY set nathi. .env file check karo."}

    page_text = scraped.get("page_text", "")
    raw_pdf_text = scraped.get("raw_pdf_text", "")

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
Below is the raw text content scraped from a LinkedIn profile.
Extract ALL available information and return ONLY a valid JSON object.

Required JSON structure:
{{
  "name": "Full name",
  "email": "Email address if found in the profile text",
  "phone": "Phone/mobile number if found in the profile text",
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

--- EXTRACTED PDF TEXT (Use this as primary source if present, as it has complete resume data) ---
{raw_pdf_text}

--- STRUCTURED HTML FIELDS (Secondary source) ---
Name: {name}
Headline: {headline}
Location: {location}
About: {about}
Experience: {exp_raw[:2000]}
Education: {edu_raw[:1000]}
Skills: {skills_raw[:500]}

--- FULL PAGE TEXT ---
{page_text[:6000]}
"""

    last_error = ""
    for idx, api_key in enumerate(api_keys):
        try:
            print(f"[Gemini] Trying API Key {idx + 1} of {len(api_keys)}...")
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")

            response = model.generate_content(prompt)
            raw_text = response.text.strip()

            # Strip markdown code fences if present
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)
            raw_text = raw_text.strip()

            data = json.loads(raw_text)
            data["url"] = scraped.get("url", "")
            # Preserve raw PDF text in output dict so view can save it
            data["raw_pdf_text"] = raw_pdf_text
            return data

        except json.JSONDecodeError:
            # If the response returned successfully but was invalid JSON, no need to retry other keys
            return {
                "error": "Gemini valid JSON nathi aapyo.",
                "raw": response.text[:300] if "response" in dir() else ""
            }
        except Exception as e:
            last_error = str(e)
            print(f"[Gemini] API Key {idx + 1} failed with error: {last_error}")
            # Loop will continue to next key

    return {"error": f"Badhi j Gemini API keys failed or quota exceeded. Last error: {last_error}"}


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
    raw_pdf_text = scraped.get("raw_pdf_text", "").strip()

    # Log first 500 chars to Django console for debugging
    logger.warning(f"[LinkedIn] page_text preview: {page_text[:500]}")
    print(f"[LinkedIn DEBUG] page_text length: {len(page_text)}")
    print(f"[LinkedIn DEBUG] PDF extracted length: {len(raw_pdf_text)}")
    print(f"[LinkedIn DEBUG] name: {scraped.get('name')}")
    print(f"[LinkedIn DEBUG] headline: {scraped.get('headline')}")

    # If both are empty, the scraping failed
    if not page_text and not raw_pdf_text:
        return {
            "error": "Profile page empty mili. LinkedIn login fail thayo hoi shake che."
        }

    return parse_with_gemini(scraped)

