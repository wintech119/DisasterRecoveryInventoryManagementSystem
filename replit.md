# GOJ Relief Inventory System

## Overview

This is a disaster relief inventory management system built for the Government of Jamaica (GOJ). The application tracks relief supplies across multiple locations (shelters, depots, parishes), manages donations from donors, and records distributions to beneficiaries. The system provides real-time stock monitoring, low-stock alerts, and comprehensive transaction tracking to ensure effective disaster response operations.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
**Technology**: Flask (Python web framework)
**Rationale**: Flask provides a lightweight, flexible foundation for building web applications quickly. It's well-suited for this relief inventory system because it allows rapid development while maintaining simplicity. The framework's minimal overhead makes it ideal for deployment in resource-constrained environments that might be common during disaster response scenarios.

### Data Model
**Solution**: SQLAlchemy ORM with relational database design
**Database**: SQLite (development) with PostgreSQL support (production via DATABASE_URL environment variable)

The data model consists of six core entities:
- **Items**: Relief supplies with auto-generated SKU (format: ITM-XXXXXX), category, unit of measurement, minimum quantity thresholds, and description field
- **Locations**: Physical sites (depots, shelters, parishes) where inventory is stored
- **Donors**: Organizations or individuals providing donations
- **Beneficiaries**: Recipients of relief supplies (households, individuals, shelters)
- **Distributors**: Personnel who perform distributions (name, contact, organization)
- **Transactions**: Double-entry-style records tracking all intake ("IN") and distribution ("OUT") movements

**Design Decision**: The Transaction model uses a type field ("IN"/"OUT") rather than separate Donation/Distribution tables. This simplifies querying stock levels by summing transactions and provides a single audit trail. Stock quantities are calculated dynamically from transactions rather than stored denormalized, ensuring data consistency.

**Item SKU System**: Items use auto-generated SKUs as primary keys instead of numeric IDs. SKUs are generated using cryptographically secure random tokens (format: ITM-XXXXXX) with collision detection to ensure uniqueness. This provides human-readable identifiers suitable for relief operations.

**Distributor Tracking**: Distribution transactions (OUT) can be linked to a distributor who performed the distribution. This enables accountability tracking and helps organizations monitor which personnel are handling relief supply distributions.

### Frontend Architecture
**Technology**: Server-side rendered HTML templates with Bootstrap 5
**Rationale**: Traditional server-side rendering eliminates the complexity of a separate frontend build process and JavaScript framework. This approach prioritizes:
- Quick deployment without build steps
- Minimal client-side dependencies (works on low-bandwidth connections)
- Accessibility for relief workers with varying technical expertise
- No API maintenance overhead

Bootstrap provides responsive, mobile-friendly layouts essential for field workers using tablets or phones in emergency situations.

### Stock Calculation Strategy
**Approach**: Dynamic aggregation from transactions
Stock levels are computed on-demand by summing transactions:
- IN transactions add to stock
- OUT transactions subtract from stock
- Filtered by location and item

**Pros**: 
- Guaranteed data consistency (no sync issues)
- Complete audit trail preserved
- No complex update logic required

**Cons**: 
- Query performance may degrade with very large transaction volumes
- More complex aggregation queries

**Alternatives Considered**: Storing current stock as a denormalized field on a separate Inventory table would improve read performance but introduces consistency risks and requires more complex transaction handling.

### Dashboard Features
The dashboard provides at-a-glance visibility into the relief inventory system:

**Key Performance Indicators (KPIs)**:
- Total unique items in the catalog
- Total units in stock across all locations
- Count of items below minimum stock threshold

**Inventory by Category**: Displays aggregated inventory statistics grouped by item category (Food, Water, Hygiene, Medical, etc.), showing:
- Number of unique items per category
- Total units in stock per category
- Sorted alphabetically for quick reference

**Stock by Location**: Shows total inventory units at each depot/shelter with quick access to location-specific inventory details.

**Low Stock Alerts**: Real-time monitoring of items below minimum quantity thresholds, broken down by location to enable targeted restocking.

**Recent Transactions**: Displays the 10 most recent intake and distribution activities, including distributor information for distributions to track accountability.

### Authentication
**Status**: Not implemented
**Rationale**: The current implementation assumes deployment in a trusted environment or behind external authentication (e.g., VPN, reverse proxy with auth). This simplifies initial deployment during emergency response when rapid setup is critical.

**Future Consideration**: Role-based access control would be beneficial for production deployments to distinguish between warehouse managers, field workers, and administrators.

### Data Import/Export
**Technology**: Pandas library for CSV handling
**Rationale**: Relief operations often require bulk data entry and reporting. CSV import/export enables:
- Rapid initial setup of item catalogs
- Integration with spreadsheet-based workflows common in relief organizations
- Data backup and transfer between systems
- Offline data preparation

### Session Management
**Implementation**: Flask's built-in session handling with secret key
**Security**: Secret key loaded from environment variable (SECRET_KEY) with fallback to development default

## External Dependencies

### Core Framework Dependencies
- **Flask 3.0.3**: Web application framework
- **Flask-SQLAlchemy 3.1.1**: ORM integration for Flask
- **SQLAlchemy 2.0.32**: Database abstraction and ORM

### Database Drivers
- **psycopg2-binary**: PostgreSQL adapter for production deployments
- **SQLite**: Built-in Python database for development (no separate installation required)

### Data Processing
- **Pandas 2.2.2**: CSV import/export and data manipulation

### Configuration Management
- **python-dotenv 1.0.1**: Environment variable management for configuration

### Frontend Dependencies (CDN-delivered)
- **Bootstrap 5.3.3**: CSS framework for responsive UI (loaded from CDN, no local installation)

### Database Configuration
The application supports multiple database backends via the DATABASE_URL environment variable:
- Development: SQLite file-based database (db.sqlite3)
- Production: PostgreSQL via connection string

No external APIs or third-party services are currently integrated. The system is designed to operate independently, which is critical for disaster scenarios where internet connectivity may be unreliable.