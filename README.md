# LinkedIn Automation - Registration Chatbot

Django-based chatbot application that collects user registration data through a conversational interface and stores it in a database.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Project Structure](#3-project-structure)
4. [Setup & Installation](#4-setup--installation)
5. [Environment Variables (.env)](#5-environment-variables-env)
6. [Database Configuration](#6-database-configuration)
7. [Running the Project](#7-running-the-project)
8. [URL Routes](#8-url-routes)
9. [API Endpoints](#9-api-endpoints)
10. [Database Models](#10-database-models)
11. [User Flow](#11-user-flow)
12. [LinkedIn Scraper](#12-linkedin-scraper)
13. [Email / Password Reset](#13-email--password-reset)
14. [Common Errors & Fixes](#14-common-errors--fixes)

---

## 1. Project Overview

Aa project ek **Registration Chatbot** che jo user thi step-by-step information le che aur database ma save kare che.

**Features:**
- Chatbot-style registration form (Name → Email → Phone → Password)
- Login with session tracking (IP, User Agent)
- Password reset via email (SMTP)
- LinkedIn profile scraper (Selenium + Gemini AI)
- Home page after successful registration/login
- Admin panel to view all users

---

## 2. Tech Stack

| Layer      | Technology              |
|------------|-------------------------|
| Backend    | Django 5.0.14           |
| Database   | SQLite (dev) / MySQL (prod) |
| Auth       | Django AbstractUser     |
| Email      | Gmail SMTP              |
| Scraping   | Selenium + undetected-chromedriver |
| AI         | Google Gemini 2.5 Flash |
| Frontend   | Vanilla HTML/CSS/JS     |

---

## 3. Project Structure

```
linkdin_link_automation/
│
├── chatbot_project/          # Django project settings
│   ├── settings.py           # All configurations
│   ├── urls.py               # Root URL config
│   ├── wsgi.py
│   └── __init__.py           # PyMySQL setup
│
├── accounts/                 # Main app
│   ├── models.py             # User, UserProfile, LoginActivity, UserDetails
│   ├── views.py              # All view functions
│   ├── urls.py               # App URL patterns
│   ├── linkedin_scraper.py   # LinkedIn scraping logic
│   ├── templates/
│   │   └── accounts/
│   │       ├── chatbot.html              # Registration chatbot UI
│   │       ├── home.html                 # Home page after login/register
│   │       ├── user_details.html         # Admin user list
│   │       ├── password_reset_confirm.html
│   │       └── password_reset_complete.html
│   └── migrations/           # Database migrations
│
├── .env                      # Environment variables (secrets)
├── .env.example              # Template for .env
├── requirements.txt          # Python dependencies
├── manage.py
└── README.md
```

---

## 4. Setup & Installation

### Step 1: Clone / Download project

```bash
cd D:\your\project\folder
```

### Step 2: Install Python dependencies

```bash
pip install -r requirements.txt
pip install undetected-chromedriver
```

### Step 3: Create `.env` file

`.env.example` file copy karo ane `.env` naam rakho:

```bash
copy .env.example .env
```

Pachhi `.env` ma apni values nakho (see Section 5).

### Step 4: Run database migrations

```bash
python manage.py migrate
```

### Step 5: Start server

```bash
python manage.py runserver
```

Browser ma open karo: **http://127.0.0.1:8000**

---

## 5. Environment Variables (.env)

`.env` file project root ma hovi joiye. Example:

```env
# Django Settings
DJANGO_SECRET_KEY=change-this-to-random-secret
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Database: SQLite (development) ya MySQL (production)
DJANGO_USE_SQLITE=True
SQLITE_DATABASE=db.sqlite3

# MySQL (production ma use karo)
MYSQL_DATABASE=linkdin_automation
MYSQL_USER=root
MYSQL_PASSWORD=yourpassword
MYSQL_HOST=localhost
MYSQL_PORT=3306

# Gmail SMTP (password reset email mate)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=youremail@gmail.com
EMAIL_HOST_PASSWORD=your_16_char_app_password
DEFAULT_FROM_EMAIL=youremail@gmail.com
APP_BASE_URL=http://127.0.0.1:8000

# Google Gemini AI (LinkedIn scraping mate)
GEMINI_API_KEY=your_gemini_api_key

# LinkedIn session cookie (scraping mate)
LINKEDIN_LI_AT=your_li_at_cookie_value
```

### Gmail App Password kevi rite melvo:

1. Google Account → Security → 2-Step Verification ON karo
2. Security → App Passwords → "Mail" select karo
3. 16-character password generate thashe — ene `EMAIL_HOST_PASSWORD` ma nakho

### Gemini API Key kevi rite melvo:

1. [aistudio.google.com](https://aistudio.google.com) → "Get API Key"
2. Copy kari `.env` ma nakho

### LinkedIn `li_at` Cookie kevi rite melvo:

1. Browser ma LinkedIn login karo
2. F12 → Application tab → Cookies → `https://www.linkedin.com`
3. `li_at` naam ni cookie dhundo → Value copy karo
4. `.env` ma `LINKEDIN_LI_AT=` ma nakho

---

## 6. Database Configuration

### SQLite (Development - Default)

`.env` ma set karo:
```env
DJANGO_USE_SQLITE=True
```

Database file `db.sqlite3` project root ma bani jase.

### MySQL (Production)

`.env` ma set karo:
```env
DJANGO_USE_SQLITE=False
MYSQL_DATABASE=linkdin_automation
MYSQL_USER=root
MYSQL_PASSWORD=yourpassword
MYSQL_HOST=localhost
MYSQL_PORT=3306
```

MySQL ma database banavo:
```sql
CREATE DATABASE linkdin_automation CHARACTER SET utf8mb4;
```

Pachhi migrations run karo:
```bash
python manage.py migrate
```

---

## 7. Running the Project

```bash
# Development server start karo
python manage.py runserver

# Custom port par
python manage.py runserver 8080

# Migrations
python manage.py migrate

# New migrations create karo (models change thaay tyare)
python manage.py makemigrations

# Superuser banavo (admin panel mate)
python manage.py createsuperuser
```

---

## 8. URL Routes

| URL | View | Description |
|-----|------|-------------|
| `/` | `chatbot_register_page` | Registration chatbot |
| `/home/` | `home_view` | Home page after login/register |
| `/user-details/` | `user_details_view` | All users list (admin) |
| `/admin/` | Django Admin | Admin panel |
| `/api/register/` | `register_chatbot_user` | Register API (POST) |
| `/api/login/` | `login_chatbot_user` | Login API (POST) |
| `/api/forgot-password/` | `forgot_password_user` | Forgot password API (POST) |
| `/api/linkedin-scrape/` | `scrape_linkedin_view` | LinkedIn scrape API (POST) |
| `/reset/<uidb64>/<token>/` | Password Reset Confirm | Password reset page |
| `/reset/complete/` | Password Reset Complete | Reset success page |

---

## 9. API Endpoints

### POST `/api/register/`

**Request Body:**
```json
{
  "name": "Dhruv Chavda",
  "email": "dhruv@example.com",
  "phone": "9876543210",
  "password": "MyPass@123",
  "confirm_password": "MyPass@123"
}
```

**Success Response (201):**
```json
{
  "success": true,
  "message": "Registration complete thai gayu.",
  "redirect_url": "/home/"
}
```

**Error Response (400/409):**
```json
{
  "success": false,
  "message": "User is already exist.",
  "errors": {
    "email": "User is already exist."
  }
}
```

---

### POST `/api/login/`

**Request Body:**
```json
{
  "email": "dhruv@example.com",
  "password": "MyPass@123"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Login successful.",
  "redirect_url": "/home/",
  "user": {
    "id": 1,
    "name": "Dhruv",
    "email": "dhruv@example.com"
  }
}
```

---

### POST `/api/forgot-password/`

**Request Body:**
```json
{
  "email": "dhruv@example.com"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Password reset link tamara email par mokli didhi che."
}
```

---

### POST `/api/linkedin-scrape/`

**Request Body:**
```json
{
  "url": "https://www.linkedin.com/in/dhruv-chavda-84709b236/"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "profile": {
    "name": "Dhruv Chavda",
    "headline": "Fresher and currently Study MCA in JG University",
    "location": "Ahmedabad, Gujarat, India",
    "about": "...",
    "experience": [...],
    "education": [...],
    "skills": [...]
  }
}
```

**Error Response (500):**
```json
{
  "success": false,
  "message": "LinkedIn login failed. .env ma LINKEDIN_LI_AT cookie set karo."
}
```

---

## 10. Database Models

### `User` (AbstractUser extend)
| Field    | Type        | Description              |
|----------|-------------|--------------------------|
| email    | EmailField  | Unique, lowercase store  |
| username | CharField   | Email j use thay         |
| password | CharField   | Hashed                   |

### `UserProfile`
| Field      | Type        | Description      |
|------------|-------------|------------------|
| user       | FK → User   | One-to-one       |
| phone      | CharField   | Unique, 10-15 digits |
| created_at | DateTime    | Auto             |

### `LoginActivity`
| Field          | Type        | Description           |
|----------------|-------------|-----------------------|
| user           | FK → User   | Nullable              |
| email          | EmailField  | Login thi email       |
| success        | Boolean     | True/False            |
| failure_reason | CharField   | Failed thi reason     |
| ip_address     | IPField     | Client IP             |
| user_agent     | TextField   | Browser info          |
| login_at       | DateTime    | Auto timestamp        |

### `UserDetails`
| Field      | Type        | Description         |
|------------|-------------|---------------------|
| user       | FK → User   | One-to-one          |
| name       | CharField   | Full name           |
| email      | EmailField  | Unique              |
| phone      | CharField   | 10-15 digits        |
| last_login | DateTime    | Last login time     |
| ip_address | IPField     | Last login IP       |
| user_agent | TextField   | Last browser info   |
| created_at | DateTime    | Account created at  |

---

## 11. User Flow

### Registration Flow
```
Browser: http://127.0.0.1:8000/
    ↓
Chatbot: "Tamaru puru naam aapo."
    ↓
User: naam type kare
    ↓
Chatbot: "Email ID aapo."
    ↓
User: email type kare
    ↓
Chatbot: "Mobile number aapo."
    ↓
User: phone type kare
    ↓
Chatbot: "Password aapo."
    ↓
User: password type kare
    ↓
Chatbot: "Confirm password aapo."
    ↓
User: confirm password type kare
    ↓
POST /api/register/ → DB ma save
    ↓
Redirect: /home/
```

### Login Flow
```
Chatbot ma "login" type karo
    ↓
Email aapo
    ↓
Password aapo
    ↓
POST /api/login/ → session create, LoginActivity save
    ↓
Redirect: /home/
```

### Password Reset Flow
```
Chatbot ma "forgot password" type karo
    ↓
Registered email aapo
    ↓
POST /api/forgot-password/ → Gmail thi reset link moklave
    ↓
Email ma link khole
    ↓
/reset/<uid>/<token>/ → navu password set karo
    ↓
/reset/complete/ → success
```

---

## 12. LinkedIn Scraper

**File:** `accounts/linkedin_scraper.py`

### Kevi rite kaam kare che:

1. `undetected-chromedriver` thi headless Chrome start thay
2. `li_at` cookie inject kari LinkedIn login thay
3. Profile page load thay + scroll down (lazy sections load mate)
4. CSS selectors thi name, headline, location, about, experience, education, skills extract thay
5. Extracted text Gemini AI ne moklave
6. Gemini structured JSON return kare

### Requirements:
- Google Chrome installed hovo joiye (version 137+)
- `LINKEDIN_LI_AT` cookie `.env` ma set hovi joiye
- `GEMINI_API_KEY` set hovi joiye

### `li_at` Cookie Refresh:
LinkedIn cookies expire thaay (few months). Expire thaay tyare:
1. Browser ma LinkedIn login karo
2. F12 → Application → Cookies → `li_at` → Value copy
3. `.env` ma replace karo

### Known Limitations:
- LinkedIn anti-bot detection strong che — occasional failures possible
- Headless browser thi LinkedIn sometimes CAPTCHA dekhaade
- Free tier Gemini ma 20 requests/day limit che

---

## 13. Email / Password Reset

**Gmail SMTP setup:**

1. Gmail account ma 2-Factor Authentication ON karo
2. Google Account → Security → App Passwords
3. App: "Mail", Device: "Windows Computer"
4. 16-character password copy karo
5. `.env` ma:
```env
EMAIL_HOST_USER=yourgmail@gmail.com
EMAIL_HOST_PASSWORD=abcd efgh ijkl mnop  # spaces hatavine nakho
```

**Test karo:**
```bash
python manage.py shell -c "
from django.core.mail import send_mail
send_mail('Test', 'Test message', 'from@gmail.com', ['to@gmail.com'])
print('Email sent!')
"
```

---

## 14. Common Errors & Fixes

### Error: Server hang thay che / startup par atki jay
**Cause:** MySQL connect karva try kare che pan MySQL nathi
**Fix:** `.env` ma add karo:
```env
DJANGO_USE_SQLITE=True
```

---

### Error: `403 CSRF verification failed`
**Cause:** Page reload kari vagar token expire thayo
**Fix:** `Ctrl + Shift + R` (hard refresh)

---

### Error: `[WinError 193] %1 is not a valid Win32 application`
**Cause:** Old ChromeDriver incompatible
**Fix:** `undetected-chromedriver` install karo:
```bash
pip install undetected-chromedriver
```

---

### Error: `Gemini API error: 404 model not found`
**Cause:** Old model name (`gemini-1.5-flash`) deprecated
**Fix:** `linkedin_scraper.py` ma model name change karo:
```python
model = genai.GenerativeModel("gemini-2.5-flash")
```

---

### Error: `429 Quota exceeded`
**Cause:** Gemini free tier limit (20 req/day)
**Fix:** Kal try karo ya paid plan lo

---

### Error: `LinkedIn login failed`
**Cause:** `LINKEDIN_LI_AT` cookie missing ya expired
**Fix:**
1. Browser ma LinkedIn login karo
2. F12 → Application → Cookies → `li_at` copy karo
3. `.env` ma update karo

---

### Error: `Email athva password khoto che`
**Cause:** User database ma exist nathi
**Fix:** Pehla register karo ya sahi email/password use karo

---

### Error: `Database tables missing`
**Cause:** Migrations run nathi thaya
**Fix:**
```bash
python manage.py migrate
```

---

## Quick Start Summary

```bash
# 1. Dependencies install
pip install -r requirements.txt
pip install undetected-chromedriver

# 2. .env file banavo
copy .env.example .env
# .env ma DJANGO_USE_SQLITE=True set karo

# 3. Database setup
python manage.py migrate

# 4. Server start
python manage.py runserver

# 5. Browser ma open karo
# http://127.0.0.1:8000
```
