"""
Date and Time Formatting Utilities for DRIMS
Provides standardized date/time formatting with Eastern Standard Time (EST/GMT-5) support
"""
from datetime import datetime, timezone, timedelta


# Eastern Standard Time (EST) is UTC-5
EST = timezone(timedelta(hours=-5))


def utc_to_est(dt):
    """
    Convert UTC datetime to Eastern Standard Time (EST/GMT-5)
    
    Args:
        dt: datetime object in UTC (naive or aware)
        
    Returns:
        datetime object in EST timezone
    """
    if dt is None:
        return None
    
    # If datetime is naive, assume it's UTC (which is our storage standard)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    # Convert to EST
    return dt.astimezone(EST)


def format_date(dt):
    """
    Format date as YYYY-MM-DD
    
    Args:
        dt: datetime or date object
        
    Returns:
        str: Formatted date (e.g., "2025-11-10")
    """
    if dt is None:
        return ""
    
    # Convert to EST first if it's a datetime
    if isinstance(dt, datetime):
        dt = utc_to_est(dt)
    
    return dt.strftime("%Y-%m-%d")


def format_datetime(dt):
    """
    Format datetime as YYYY-MM-DD HH:MM EST
    
    Args:
        dt: datetime object (assumes UTC if naive)
        
    Returns:
        str: Formatted datetime with EST indicator (e.g., "2025-11-10 14:35 EST")
    """
    if dt is None:
        return ""
    
    # Convert to EST
    est_dt = utc_to_est(dt)
    
    return est_dt.strftime("%Y-%m-%d %H:%M EST")


def format_datetime_full(dt):
    """
    Format datetime with seconds as YYYY-MM-DD HH:MM:SS EST
    
    Args:
        dt: datetime object (assumes UTC if naive)
        
    Returns:
        str: Formatted datetime with seconds (e.g., "2025-11-10 14:35:42 EST")
    """
    if dt is None:
        return ""
    
    # Convert to EST
    est_dt = utc_to_est(dt)
    
    return est_dt.strftime("%Y-%m-%d %H:%M:%S EST")


def format_time(dt):
    """
    Format time only as HH:MM EST
    
    Args:
        dt: datetime object (assumes UTC if naive)
        
    Returns:
        str: Formatted time (e.g., "14:35 EST")
    """
    if dt is None:
        return ""
    
    # Convert to EST
    est_dt = utc_to_est(dt)
    
    return est_dt.strftime("%H:%M EST")


def format_datetime_iso_est(dt):
    """
    Format datetime as ISO 8601 string in EST for JavaScript consumption
    
    Args:
        dt: datetime object (assumes UTC if naive)
        
    Returns:
        str: ISO formatted datetime in EST (e.g., "2025-11-10T14:35:42-05:00")
    """
    if dt is None:
        return ""
    
    # Convert to EST
    est_dt = utc_to_est(dt)
    
    return est_dt.isoformat()


def format_relative_time(dt):
    """
    Format datetime as relative time (e.g., "5 mins ago", "2 hours ago")
    Falls back to absolute date for older timestamps
    
    Args:
        dt: datetime object (assumes UTC if naive)
        
    Returns:
        str: Relative time description
    """
    if dt is None:
        return ""
    
    # Convert both to EST for comparison
    est_dt = utc_to_est(dt)
    now_est = datetime.now(EST)
    
    diff = now_est - est_dt
    diff_seconds = diff.total_seconds()
    diff_minutes = diff_seconds / 60
    diff_hours = diff_minutes / 60
    diff_days = diff_hours / 24
    
    if diff_minutes < 1:
        return "Just now"
    elif diff_minutes < 60:
        mins = int(diff_minutes)
        return f"{mins} min{'s' if mins > 1 else ''} ago"
    elif diff_hours < 24:
        hours = int(diff_hours)
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff_days < 7:
        days = int(diff_days)
        return f"{days} day{'s' if days > 1 else ''} ago"
    else:
        # For older dates, show absolute date with EST indicator
        return f"{format_date(est_dt)} EST"
