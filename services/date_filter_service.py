from datetime import datetime, date, timedelta
from typing import List, Optional
import re
from models import Event
from services import event_repository
from config import Config

class DateFilterService:
    """Service to filter events based on date ranges and handle manual date input."""
    
    def __init__(self):
        # Regex pattern for DD-MM-YY format
        self.date_pattern = re.compile(r'^(\d{1,2})-(\d{1,2})-(\d{2})$')
    
    def parse_manual_date(self, date_string: str) -> Optional[date]:
        """Parse manual date input in DD-MM-YY format."""
        match = self.date_pattern.match(date_string.strip())
        if not match:
            return None
        
        try:
            day, month, year = match.groups()
            # Convert 2-digit year to 4-digit (assume 20xx for years 00-50, 19xx for 51-99)
            year_int = int(year)
            if year_int <= 50:
                full_year = 2000 + year_int
            else:
                full_year = 1900 + year_int
            
            return date(full_year, int(month), int(day))
        except ValueError:
            return None
    
    def get_8_week_range(self, center_date: date = None) -> tuple[date, date]:
        """Get 8-week date range (4 weeks before and after center date)."""
        if center_date is None:
            center_date = date.today()
        
        start_date = center_date - timedelta(weeks=4)
        end_date = center_date + timedelta(weeks=4)
        
        return start_date, end_date
    
    async def get_available_events(self, manual_date: str = None, search: str = None) -> List[Event]:
        """Get available events for selection in dropdown. Supports wide search if search is provided."""
        guild_id = Config.GUILD_ID

        # If manual_date is provided and valid, only search that date
        if manual_date:
            parsed_date = self.parse_manual_date(manual_date)
            if parsed_date:
                events = await event_repository.get_events_by_guild_and_date_range(
                    guild_id, parsed_date, parsed_date
                )
                return events
            else:
                return []

        # If search string is provided, search ±1 year for matching events
        if search and search.strip():
            today = date.today()
            start_date = today - timedelta(weeks=52)
            end_date = today + timedelta(weeks=52)
            events = await event_repository.get_events_by_guild_and_date_range(
                guild_id, start_date, end_date
            )
            # Filter events by partial date or name match
            filtered = []
            search_lower = search.lower()
            for event in events:
                formatted = self.format_event_for_dropdown(event).lower()
                if search_lower in formatted:
                    filtered.append(event)
            return filtered

        # Default: 8-week range
        start_date, end_date = self.get_8_week_range()
        events = await event_repository.get_events_by_guild_and_date_range(
            guild_id, start_date, end_date
        )
        return events
    
    def format_event_for_dropdown(self, event: Event) -> str:
        """Format event for dropdown display."""
        # Format: "Thursday Training - 24/10/25" or "Sunday Mission - 27/10/25"
        day_name = event.date.strftime('%A')
        date_str = event.date.strftime('%d/%m/%y')
        
        if event.name.strip():
            return f"{day_name} {event.type} - {date_str} ({event.name[:20]}{'...' if len(event.name) > 20 else ''})"
        else:
            return f"{day_name} {event.type} - {date_str}"
    
    def format_event_for_display(self, event: Event) -> str:
        """Format event for general display."""
        day_name = event.date.strftime('%A')
        date_str = event.date.strftime('%d/%m/%Y')
        
        if event.name.strip():
            creator_info = f" (by {event.creator_name})" if event.creator_name else ""
            return f"**{day_name} {event.type}** - {date_str}\n{event.name}{creator_info}"
        else:
            return f"**{day_name} {event.type}** - {date_str}\n*No details set*"
    
    async def find_event_by_formatted_string(self, formatted_string: str, events: List[Event]) -> Optional[Event]:
        """Find an event by its formatted dropdown string."""
        for event in events:
            if self.format_event_for_dropdown(event) == formatted_string:
                return event
        return None
    
    def is_date_in_past(self, check_date: date, days_threshold: int = 0) -> bool:
        """Check if a date is in the past beyond threshold."""
        today = date.today()
        threshold_date = today - timedelta(days=days_threshold)
        return check_date < threshold_date
    
    def validate_manual_date_input(self, date_input: str) -> tuple[bool, str]:
        """Validate manual date input and return success status with message."""
        if not date_input:
            return True, "No manual date provided"
        
        parsed_date = self.parse_manual_date(date_input)
        if not parsed_date:
            return False, "Invalid date format. Please use DD-MM-YY (e.g., 25-10-24)"
        
        # Check if date is too far in the past (more than 1 year)
        if self.is_date_in_past(parsed_date, days_threshold=365):
            return False, "Date is too far in the past (more than 1 year)"
        
        # Check if date is too far in the future (more than 1 year)
        future_limit = date.today() + timedelta(days=365)
        if parsed_date > future_limit:
            return False, "Date is too far in the future (more than 1 year)"
        
        return True, f"Date parsed successfully: {parsed_date.strftime('%d/%m/%Y')}"

# Singleton instance  
date_filter_service = DateFilterService()