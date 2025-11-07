# Disaster Relief Inventory Management System (DRIMS)

A comprehensive inventory management system designed to track and manage disaster relief supplies with location-based inventory tracking, role-based access control, and real-time analytics.

## Features

### 🔐 User Authentication & Access Control
- **Six Role-Based Access Levels:**
  - **Administrator**: Full system access including user management
  - **Inventory Manager**: Operations oversight, location/distributor/event management
  - **Warehouse Staff**: Day-to-day inventory operations at assigned locations
  - **Field Personnel**: Mobile distribution in the field
  - **Executive Management**: Strategic oversight with KPI dashboards
  - **Auditor**: Compliance verification with full transaction history

### 📊 Comprehensive Dashboard
- Real-time KPIs (total items, stock levels, active events)
- Operations metrics (donors, beneficiaries, distributors, locations)
- Transaction analytics (all-time and last 30 days)
- Inventory by category summaries
- Stock by location tracking
- Low stock alerts with color-coded urgency
- Expiring items alerts (critical <7 days, warning 8-14 days)
- Activity tracking by disaster event

### 📦 Inventory Management
- Auto-generated SKUs (ITM-XXXXXX format)
- Item categorization (Food, Water, Hygiene, Medical, etc.)
- Unit of measure tracking
- Minimum quantity thresholds for low-stock alerts
- Expiry date tracking for perishable items
- Storage requirement documentation
- Location-based stock tracking

### 🌪️ Disaster Event Management
- Event creation and tracking (hurricanes, earthquakes, floods)
- Mandatory event linkage for all intake operations
- Event status management (Active/Closed)
- Transaction tracking by specific disaster events
- Event-based reporting for accountability

### 📥 Intake & Distribution
- Record incoming supplies with donor tracking
- Process distributions to beneficiaries
- Distributor accountability tracking
- Location-specific stock management
- Automated audit trail with user attribution
- Stock validation before distribution

### 📈 Reporting & Analytics
- Stock reports by location and category
- Transaction history with full audit trail
- CSV import/export for items
- Low stock alerts
- Expiring items tracking
- Distribution and intake analytics

### 🇯🇲 Official GOJ Branding
- Official Jamaican coat of arms
- GOJ Green and Gold color scheme
- Professional government appearance
- Mobile-responsive design

## Technology Stack

- **Backend**: Python 3.11, Flask 3.0.3
- **Authentication**: Flask-Login with secure password hashing
- **Database**: SQLite (development), PostgreSQL (production)
- **ORM**: SQLAlchemy 2.0.32
- **Frontend**: Server-side rendered Jinja2 templates
- **UI Framework**: Bootstrap 5.3.3
- **Icons**: Bootstrap Icons 1.11.3
- **Data Processing**: Pandas 2.2.2

## Quick Start

### Prerequisites
- Python 3.11 or higher
- pip (Python package manager)
- Git

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/drims.git
   cd drims
   ```

2. **Create virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables:**
   ```bash
   # Create .env file
   cat > .env << EOF
   SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
   DATABASE_URL=sqlite:///db.sqlite3
   EOF
   ```

5. **Initialize database:**
   ```bash
   python -c "from app import app, db; app.app_context().push(); db.create_all()"
   ```

6. **Create admin user:**
   ```bash
   flask create-admin
   ```
   Follow the prompts to create your administrator account.

7. **Run the application:**
   ```bash
   python app.py
   ```

8. **Access the system:**
   Open your browser and navigate to `http://localhost:5000`
   Log in with the admin credentials you created.

## User Management

### Create Additional Users

```bash
# Create user with specific role
flask create-user
```

This interactive command will prompt you for:
- Email address
- Full name
- Role selection (1-6)
- Location assignment (for warehouse staff)
- Password

### Default Test Accounts (Development Only)

For testing purposes, the following accounts are available:

| Email | Password | Role |
|-------|----------|------|
| admin@gov.jm | admin123 | Administrator |
| logistics.manager@gov.jm | logmanager123 | Logistics Manager |
| logistics.officer@gov.jm | logofficer123 | Logistics Officer |
| warehouse@gov.jm | warehouse123 | Warehouse Staff |
| field@gov.jm | field123 | Field Personnel |
| executive@gov.jm | exec123 | Executive |
| auditor@gov.jm | audit123 | Auditor |
| distributor@gov.jm | distributor123 | Distributor |

**⚠️ IMPORTANT**: Delete or change these passwords before production deployment!

## Production Deployment

### RHEL/CentOS Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed instructions on deploying to Red Hat Enterprise Linux.

Key steps:
1. Install PostgreSQL and Python 3.11
2. Clone repository to `/opt/drims`
3. Set up virtual environment and install dependencies
4. Configure PostgreSQL database
5. Create systemd service
6. Set up Nginx reverse proxy
7. Configure SSL/TLS
8. Enable firewall rules

### PostgreSQL Configuration

For production, use PostgreSQL instead of SQLite:

```bash
# Set DATABASE_URL in .env
DATABASE_URL=postgresql://drims_user:password@localhost/drims_db
```

### Gunicorn (Production WSGI Server)

```bash
pip install gunicorn
gunicorn --bind 0.0.0.0:5000 --workers 4 app:app
```

## Configuration

### Environment Variables

- `SECRET_KEY`: Flask secret key (generate with `secrets.token_hex(32)`)
- `DATABASE_URL`: Database connection string (default: `sqlite:///db.sqlite3`)
- `FLASK_ENV`: Set to `production` for production deployments

### Database Migration

When updating the database schema:

```bash
# For new installations
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

## Security

- ✅ Secure password hashing (Werkzeug)
- ✅ Session-based authentication (Flask-Login)
- ✅ Role-based access control on all routes
- ✅ Protection against open redirect attacks
- ✅ CSRF protection (Flask built-in)
- ✅ SQL injection prevention (SQLAlchemy ORM)
- ✅ Audit trail with user attribution

### Security Best Practices

1. Always use HTTPS in production
2. Change default SECRET_KEY
3. Use strong database passwords
4. Regular security updates (`pip install --upgrade -r requirements.txt`)
5. Enable firewall on production servers
6. Regular database backups
7. Monitor application logs

## Project Structure

```
drims/
├── app.py                  # Main application file
├── templates/              # HTML templates
│   ├── base.html          # Base template with navigation
│   ├── login.html         # Login page
│   ├── dashboard.html     # Executive dashboard
│   ├── items.html         # Item list/search
│   ├── intake.html        # Intake form
│   ├── distribute.html    # Distribution form
│   └── ...
├── static/                # Static files
│   └── images/
│       └── jamaica_coat_of_arms.png
├── requirements.txt       # Python dependencies
├── .gitignore            # Git ignore rules
├── .env                  # Environment variables (not in git)
├── README.md             # This file
├── DEPLOYMENT.md         # Deployment guide
└── replit.md             # System documentation

```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-feature`)
3. Commit your changes (`git commit -m 'Add new feature'`)
4. Push to the branch (`git push origin feature/new-feature`)
5. Open a Pull Request

## License

This project is developed for the Government of Jamaica.

## Support

For issues, questions, or feature requests, please contact the system administrator or open an issue in the repository.

---

**© 2025 Government of Jamaica. All rights reserved.**
