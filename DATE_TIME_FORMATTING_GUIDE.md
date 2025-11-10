# Date and Time Formatting Guide for DRIMS

This guide shows how to use the standardized date/time formatting system in DRIMS.

## Overview

All dates and times are displayed in **Eastern Standard Time (EST / GMT-5)** using the **YYYY-MM-DD** format for dates.

## Backend (Python)

### Available Utility Functions

From `date_utils.py`:

```python
from date_utils import (
    format_date,             # YYYY-MM-DD
    format_datetime,         # YYYY-MM-DD HH:MM EST
    format_datetime_full,    # YYYY-MM-DD HH:MM:SS EST
    format_time,             # HH:MM EST
    format_datetime_iso_est, # ISO format in EST for JavaScript
    format_relative_time     # "5 mins ago", "2 hours ago"
)
```

### Usage Examples

```python
# In routes or views
created_date = format_date(needs_list.created_at)
# Result: "2025-11-10"

submitted_time = format_datetime(needs_list.submitted_at)
# Result: "2025-11-10 14:35 EST"

full_timestamp = format_datetime_full(transaction.created_at)
# Result: "2025-11-10 14:35:42 EST"
```

### JSON API Responses

```python
# For JavaScript consumption
return jsonify({
    "created_at": format_datetime_full(obj.created_at),
    "created_at_iso": format_datetime_iso_est(obj.created_at)
})
```

## Frontend (Jinja2 Templates)

### Available Template Filters

All utility functions are available as Jinja2 filters:

```jinja2
{{ needs_list.submitted_at|format_date }}
{{ needs_list.submitted_at|format_datetime }}
{{ needs_list.submitted_at|format_datetime_full }}
{{ needs_list.submitted_at|format_time }}
{{ needs_list.submitted_at|format_relative_time }}
```

### Usage Examples

#### Dates Only
```jinja2
<!-- Approval date -->
<p>Approved on: {{ needs_list.approved_at|format_date }}</p>
<!-- Result: Approved on: 2025-11-10 -->
```

#### Date with Time
```jinja2
<!-- Submission timestamp -->
<p>Submitted: {{ needs_list.submitted_at|format_datetime }}</p>
<!-- Result: Submitted: 2025-11-10 14:35 EST -->
```

#### Full Timestamp (with seconds)
```jinja2
<!-- Transaction log -->
<td>{{ transaction.created_at|format_datetime_full }}</td>
<!-- Result: 2025-11-10 14:35:42 EST -->
```

#### Relative Time
```jinja2
<!-- Recent activity -->
<small class="text-muted">{{ notification.created_at|format_relative_time }}</small>
<!-- Result: 5 mins ago OR 2025-11-10 EST (if older than 7 days) -->
```

### Tables and Lists

```jinja2
<table>
  <thead>
    <tr>
      <th>Item</th>
      <th>Date</th>
      <th>Time</th>
    </tr>
  </thead>
  <tbody>
    {% for item in items %}
    <tr>
      <td>{{ item.name }}</td>
      <td>{{ item.created_at|format_date }}</td>
      <td>{{ item.created_at|format_time }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
```

## JavaScript Frontend

### Updated formatRelativeTime Function

JavaScript now receives ISO timestamps in EST timezone from the backend:

```javascript
// The backend sends: "2025-11-10T14:35:42-05:00"
// JavaScript automatically handles this correctly

function formatRelativeTime(isoString) {
  const date = new Date(isoString); // Handles timezone automatically
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins} min${diffMins > 1 ? 's' : ''} ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
  if (diffDays < 7) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
  
  // For older dates, format as YYYY-MM-DD
  return date.toLocaleDateString('en-CA'); // en-CA gives YYYY-MM-DD format
}
```

### Displaying Timestamps in EST

```javascript
// Backend provides ISO timestamp in EST
const timestamp = "2025-11-10T14:35:42-05:00";

// Option 1: Show relative time
const relative = formatRelativeTime(timestamp);
// Result: "5 mins ago"

// Option 2: Show absolute date
const date = new Date(timestamp);
const formatted = date.toLocaleDateString('en-CA'); // YYYY-MM-DD
// Result: "2025-11-10"

// Option 3: Show date and time
const dateTime = date.toLocaleString('en-CA', { 
  timeZone: 'America/New_York',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit'
}) + ' EST';
// Result: "2025-11-10 14:35 EST"
```

## Common Patterns

### Timeline Views
```jinja2
<div class="timeline">
  {% for event in timeline_events %}
  <div class="timeline-item">
    <span class="timeline-date">{{ event.timestamp|format_date }}</span>
    <span class="timeline-time">{{ event.timestamp|format_time }}</span>
    <p>{{ event.description }}</p>
  </div>
  {% endfor %}
</div>
```

### Notification Panels
```jinja2
<div class="notification">
  <h6>{{ notification.title }}</h6>
  <p>{{ notification.message }}</p>
  <small class="text-muted">
    <i class="bi bi-clock"></i>
    {{ notification.created_at|format_relative_time }}
  </small>
</div>
```

### Audit Logs
```jinja2
<table class="table">
  <thead>
    <tr>
      <th>Action</th>
      <th>User</th>
      <th>Timestamp (EST)</th>
    </tr>
  </thead>
  <tbody>
    {% for log in audit_logs %}
    <tr>
      <td>{{ log.action }}</td>
      <td>{{ log.user_name }}</td>
      <td>{{ log.created_at|format_datetime_full }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
```

## Migration Checklist

To update a template to use standardized formatting:

1. ✅ Replace `{{ obj.created_at }}` with `{{ obj.created_at|format_datetime }}`
2. ✅ Replace `{{ obj.created_at.strftime(...) }}` with appropriate filter
3. ✅ Add " EST" indicator is now automatic (built into filters)
4. ✅ For relative times, use `format_relative_time` filter
5. ✅ For date-only displays, use `format_date` filter
6. ✅ For JavaScript timestamps, ensure backend sends ISO format via `format_datetime_iso_est()`

## Quick Reference

| Display Need | Template Filter | Example Output |
|-------------|----------------|----------------|
| Date only | `format_date` | 2025-11-10 |
| Date + Time | `format_datetime` | 2025-11-10 14:35 EST |
| Date + Time + Seconds | `format_datetime_full` | 2025-11-10 14:35:42 EST |
| Time only | `format_time` | 14:35 EST |
| Relative time | `format_relative_time` | 5 mins ago OR 2025-11-10 EST |
| For JavaScript | `format_datetime_iso_est` | 2025-11-10T14:35:42-05:00 |

## Implementation Status

✅ **Backend**: Date formatting utilities created in `date_utils.py`
✅ **Flask App**: Jinja2 filters registered in `app.py`
✅ **API Responses**: Notification API updated to use EST formatting
✅ **Lock Management API**: Updated to use EST timestamps
✅ **JavaScript**: formatRelativeTime function updated to use YYYY-MM-DD EST format
✅ **Timezone Indicators**: All date/time displays include "EST" suffix

⏳ **Templates**: Ready for migration to use new filters (see Migration Checklist above)
  - Infrastructure complete and tested
  - All 6 Jinja2 filters available system-wide
  - Documented patterns for common use cases

## Notes

- All dates stored in database remain in UTC for consistency
- Conversion to EST happens only at display time
- Eastern Standard Time is UTC-5 (does not account for daylight saving)
- For production, consider using Eastern Time (ET) which accounts for DST
