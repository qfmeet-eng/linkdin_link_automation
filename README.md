# Django Registration Chatbot

Aa project Django chatbot registration flow mate che. Page open thata chatbot sidhu naam nathi puchtu. User pehlo message kare pachi chatbot naam, mobile number, email, password ane confirm password puche che. Last step par details MySQL database ma save thay che. Password Django auth system thi hash thay che.

## Setup

1. Python packages install karo:

```bash
pip install -r requirements.txt
```

2. MySQL ma database banao:

```sql
CREATE DATABASE linkdin_automation CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

3. `.env.example` copy kari ne `.env` banao ane MySQL password + SMTP details set karo:

```bash
copy .env.example .env
```

4. Migration run karo:

```bash
python manage.py makemigrations
python manage.py migrate
```

Aa project custom user model use kare che, etle nava/fresh database par migration run karvu best che.

MySQL ready na hoy ane temporary local test karvu hoy to:

```bash
$env:DJANGO_USE_SQLITE="True"
python manage.py migrate
```

5. Server start karo:

```bash
python manage.py runserver
```

Browser ma open karo:

```text
http://127.0.0.1:8000/
```

## Admin User

```bash
python manage.py createsuperuser
```

Admin panel:

```text
http://127.0.0.1:8000/admin/
```

## API

Chatbot frontend aa endpoint par data POST kare che:

```text
POST /api/register/
```

Payload:

```json
{
  "name": "Dhruv Patel",
  "phone": "9876543210",
  "email": "dhruv@example.com",
  "password": "StrongPass123!",
  "confirm_password": "StrongPass123!"
}
```

Duplicate phone athva email aave to response:

```json
{
  "success": false,
  "message": "User is already exist."
}
```

Forgot password endpoint:

```text
POST /api/forgot-password/
```

Payload:

```json
{
  "email": "dhruv@example.com"
}
```

## Forgot Password SMTP

Chatbot ma user `forgot password` lakhse to registered email puchse. Email exist hoy to SMTP thi reset link send thase.

`.env` ma SMTP values set karo:

```text
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_app_password
DEFAULT_FROM_EMAIL=your_email@gmail.com
APP_BASE_URL=http://127.0.0.1:8000
```

Gmail mate normal password nahi, app password use karvo.
