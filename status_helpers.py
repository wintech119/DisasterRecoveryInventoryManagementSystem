"""
Status helper module for Needs List workflow
Centralizes status determination logic to ensure consistency across UI displays
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class LineItemStatus:
    """
    Represents the display status for a needs list line item
    
    Attributes:
        label: Display text for the status (e.g., "Fully Allocated", "In Transit")
        badge_class: Bootstrap badge CSS class (e.g., "bg-success", "bg-warning")
        detail_text: Optional additional context (e.g., "Awaiting review", "50% fulfilled")
        progress_pct: Optional progress percentage for visualization (0-100)
    """
    label: str
    badge_class: str
    detail_text: Optional[str] = None
    progress_pct: Optional[int] = None


def get_line_item_status(needs_list, item_metrics):
    """
    Determine the display status for a line item based on workflow state and metrics
    
    Single source of truth for item status across all workflow phases
    
    Args:
        needs_list: NeedsList object with status field
        item_metrics: dict with keys:
            - requested_qty: int - quantity requested
            - allocated_qty: int - quantity allocated from fulfillment
            - dispatched_qty: int - quantity dispatched (same as allocated in current impl)
            - received_qty: int - quantity received (tracked at needs list level, not per-item)
    
    Returns:
        LineItemStatus object with label, badge_class, detail_text, progress_pct
    """
    status = needs_list.status
    requested = item_metrics.get('requested_qty', 0)
    allocated = item_metrics.get('allocated_qty', 0)
    
    # Guard against division by zero
    if requested == 0:
        return LineItemStatus(
            label="No Quantity",
            badge_class="bg-secondary",
            detail_text="Requested quantity is zero"
        )
    
    # Calculate allocation/fulfillment percentage
    allocation_pct = int((allocated / requested * 100)) if requested > 0 else 0
    
    # --- WORKFLOW STATE MAPPING ---
    
    # Draft: Initial creation phase
    if status == 'Draft':
        return LineItemStatus(
            label="Draft",
            badge_class="bg-secondary",
            detail_text="Awaiting submission"
        )
    
    # Submitted: Awaiting logistics review
    if status == 'Submitted':
        return LineItemStatus(
            label="Submitted",
            badge_class="bg-primary",
            detail_text="Awaiting logistics review"
        )
    
    # Fulfilment Prepared / Awaiting Approval: Allocation phase
    if status in ['Fulfilment Prepared', 'Awaiting Approval']:
        if allocated == 0:
            return LineItemStatus(
                label="Not Allocated",
                badge_class="bg-secondary",
                detail_text="No stock allocated",
                progress_pct=0
            )
        elif allocated < requested:
            return LineItemStatus(
                label="Partially Allocated",
                badge_class="bg-warning text-dark",
                detail_text=f"{allocation_pct}% allocated",
                progress_pct=allocation_pct
            )
        else:  # allocated >= requested
            return LineItemStatus(
                label="Fully Allocated",
                badge_class="bg-success",
                detail_text="100% allocated",
                progress_pct=100
            )
    
    # Approved: Manager has approved the fulfilment plan
    if status == 'Approved':
        if allocated == 0:
            return LineItemStatus(
                label="Approved - Not Allocated",
                badge_class="bg-secondary",
                detail_text="Awaiting dispatch"
            )
        elif allocated < requested:
            return LineItemStatus(
                label="Approved - Partial",
                badge_class="bg-warning text-dark",
                detail_text=f"{allocation_pct}% approved"
            )
        else:
            return LineItemStatus(
                label="Approved - Ready",
                badge_class="bg-success",
                detail_text="Ready for dispatch"
            )
    
    # Dispatched: Items in transit
    if status == 'Dispatched':
        if allocated == 0:
            return LineItemStatus(
                label="Not Dispatched",
                badge_class="bg-danger",
                detail_text="No items sent"
            )
        elif allocated < requested:
            return LineItemStatus(
                label="Partially Dispatched",
                badge_class="bg-warning text-dark",
                detail_text=f"{allocation_pct}% dispatched"
            )
        else:
            return LineItemStatus(
                label="Dispatched",
                badge_class="bg-info",
                detail_text="In transit to agency"
            )
    
    # Received: Items confirmed received by agency
    if status == 'Received':
        if allocated == 0:
            return LineItemStatus(
                label="Not Dispatched",
                badge_class="bg-danger",
                detail_text="No items received"
            )
        elif allocated < requested:
            return LineItemStatus(
                label="Partial Delivery",
                badge_class="bg-warning text-dark",
                detail_text=f"{allocation_pct}% received"
            )
        else:
            return LineItemStatus(
                label="Received",
                badge_class="bg-success",
                detail_text="Full quantity received"
            )
    
    # Completed: Workflow finished
    if status == 'Completed':
        return LineItemStatus(
            label="Completed",
            badge_class="bg-success",
            detail_text="Workflow complete"
        )
    
    # Rejected: Manager rejected the fulfilment
    if status == 'Rejected':
        return LineItemStatus(
            label="Rejected",
            badge_class="bg-danger",
            detail_text="Fulfilment rejected"
        )
    
    # Fallback for any unknown status (should not occur in normal operation)
    return LineItemStatus(
        label=status,
        badge_class="bg-secondary",
        detail_text="Unknown workflow state"
    )


def get_needs_list_status_display(needs_list):
    """
    Get consistent status display for the needs list header badge
    
    Args:
        needs_list: NeedsList object
        
    Returns:
        dict with 'label' and 'badge_class' keys
    """
    status = needs_list.status
    
    status_map = {
        'Draft': {'label': 'Draft', 'badge_class': 'bg-secondary'},
        'Submitted': {'label': 'Submitted', 'badge_class': 'bg-primary'},
        'Fulfilment Prepared': {'label': 'Fulfilment Prepared', 'badge_class': 'bg-warning text-dark'},
        'Awaiting Approval': {'label': 'Awaiting Approval', 'badge_class': 'bg-warning text-dark'},
        'Approved': {'label': 'Approved', 'badge_class': 'bg-success'},
        'Dispatched': {'label': 'Dispatched', 'badge_class': 'bg-info'},
        'Received': {'label': 'Received', 'badge_class': 'bg-primary'},
        'Completed': {'label': 'Completed', 'badge_class': 'bg-success'},
        'Rejected': {'label': 'Rejected', 'badge_class': 'bg-danger'},
    }
    
    return status_map.get(status, {'label': status, 'badge_class': 'bg-secondary'})
