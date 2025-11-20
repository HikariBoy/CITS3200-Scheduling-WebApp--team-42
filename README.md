# ScheduleME 📅

A modern web application for managing university course schedules, facilitator assignments, and administrative workflows.

## ✨ Features

- 👥 Role-based access control (Admin, Unit Coordinators, Facilitators)
- 🧠 Smart scheduling with conflict detection
- 📊 Facilitator availability and skills management
- 📧 Email notifications via AWS SES
- 📁 CSV import/export for bulk operations
- 🔄 Real-time session tracking and swap requests
- 📱 Responsive design for desktop and mobile

## 🛠️ Tech Stack

- **Backend:** Python Flask
- **Database:** SQLite
- **Frontend:** HTML5, CSS3, JavaScript
- **Email:** AWS SES
- **Deployment:** AWS EC2

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- pip and virtual environment

### Installation

```bash
git clone https://github.com/HikariBoy/CITS3200-Scheduling-WebApp--team-42.git
cd CITS3200-Scheduling-WebApp--team-42

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

## ⚙️ Configuration

Create a `.env` file in the project root:

```
# AWS SES Email
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
SES_REGION=ap-southeast-1
SES_SENDER_EMAIL=noreply@yourdomain.com

# App Settings
SECRET_KEY=your_secret_key
BASE_URL=http://localhost:5000
PORT=5000
```

For AWS SES setup, see `docs/EMAIL_SETUP.md`

## ▶️ Running the Application

```bash
# Development
python3 application.py

# Production (with Gunicorn)
gunicorn -w 4 -b 0.0.0.0:7321 application:app
```

Access the app at `http://localhost:5000`

## 📁 Project Structure

```
├── templates/          # HTML templates
├── static/            # CSS, JavaScript, images
├── migrations/        # Database migrations
├── scripts/           # Utility scripts
├── archive/           # Archived test and debug files
├── docs/              # Documentation
├── models.py          # Database models
├── application.py     # Main Flask app
├── admin_routes.py    # Admin endpoints
├── unitcoordinator_routes.py  # UC endpoints
├── facilitator_routes.py       # Facilitator endpoints
├── email_service.py   # Email handling
└── requirements.txt   # Python dependencies
```

## 📚 Documentation

See the `docs/` folder for detailed guides on:
- System architecture and role hierarchy
- Facilitator management and skills
- Scheduling algorithm and optimization
- CSV import/export workflows

## 💬 Support

For issues or questions, please create an issue on GitHub.

---

**Built by Team 42 for CITS3200** ✨
