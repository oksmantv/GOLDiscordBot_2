from datetime import datetime, date, timedelta
from typing import List
from models import Event
from .event_repository import event_repository
from config import Config

class EventPopulationService:
    """Service to auto-populate weekly recurring events."""
    
    def __init__(self):
        self.event_types = ["Training", "Mission"]
        
    def get_next_thursday(self, from_date: date) -> date:
        """Get the next Thursday from the given date."""
        days_ahead = 3 - from_date.weekday()  # Thursday is weekday 3
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        return from_date + timedelta(days=days_ahead)
    
    def get_next_sunday(self, from_date: date) -> date:
        """Get the next Sunday from the given date."""
        days_ahead = 6 - from_date.weekday()  # Sunday is weekday 6
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        return from_date + timedelta(days=days_ahead)
    
    def generate_weekly_events(self, start_date: date, weeks_count: int) -> List[Event]:
        """Generate weekly events for the specified number of weeks."""
        events = []
        guild_id = Config.GUILD_ID
        
        # Find the first Thursday and Sunday
        first_thursday = self.get_next_thursday(start_date - timedelta(days=7))
        first_sunday = self.get_next_sunday(start_date - timedelta(days=7))
        
        for week in range(weeks_count):
            week_offset = timedelta(weeks=week)
            
            # Thursday events (Training and Mission)
            thursday_date = first_thursday + week_offset
            events.append(Event(
                guild_id=guild_id,
                date=thursday_date,
                type="Training",
                name="",
                creator_id=0,
                creator_name=""
            ))
            events.append(Event(
                guild_id=guild_id,
                date=thursday_date,
                type="Mission",
                name="",
                creator_id=0,
                creator_name=""
            ))
            
            # Sunday events (Mission only)
            sunday_date = first_sunday + week_offset
            events.append(Event(
                guild_id=guild_id,
                date=sunday_date,
                type="Mission",
                name="",
                creator_id=0,
                creator_name=""
            ))
        
        return events
    
    async def populate_events_for_date_range(self, start_date: date, end_date: date) -> dict:
        """Populate events for a specific date range. Returns a summary dict."""
        days_diff = (end_date - start_date).days
        weeks_needed = (days_diff // 7) + 2  # Add extra weeks to ensure coverage

        events_to_create = self.generate_weekly_events(start_date, weeks_needed)
        filtered_events = [
            event for event in events_to_create
            if start_date <= event.date <= end_date
        ]

        created_count = 0
        skipped_count = 0
        failed_count = 0
        for event in filtered_events:
            try:
                created, event_id = await event_repository.create_event(event)
                if created:
                    created_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                if "duplicate key" in str(e).lower():
                    skipped_count += 1
                else:
                    failed_count += 1
        return {
            "created": created_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "total": len(filtered_events)
        }
    
    async def populate_8_week_range(self, center_date: date = None) -> dict:
        """Populate events for 8-week range (4 weeks before and after center date). Returns a summary dict."""
        if center_date is None:
            center_date = date.today()

        start_date = center_date - timedelta(weeks=4)
        end_date = center_date + timedelta(weeks=4)

        return await self.populate_events_for_date_range(start_date, end_date)
    
    async def maintain_event_population(self) -> dict:
        """Maintain event population to always have ~8 weeks available.

        Returns a summary dict with keys: created, skipped, failed, total.
        """
        today = date.today()
        
        # Check if we have events 4 weeks ahead
        future_date = today + timedelta(weeks=4)
        existing_events = await event_repository.get_events_by_guild_and_date_range(
            Config.GUILD_ID, 
            future_date, 
            future_date
        )
        
        # If no events exist 4 weeks ahead, populate new range
        if not existing_events:
            return await self.populate_8_week_range(today)

        return {"created": 0, "skipped": 0, "failed": 0, "total": 0}

# Singleton instance
event_population_service = EventPopulationService()