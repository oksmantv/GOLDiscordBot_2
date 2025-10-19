from datetime import datetime, date
from typing import List, Optional
from models import Event
from .database_connection import db_connection

class EventRepository:
    """Repository for Event CRUD operations."""
    
    async def create_event(self, event: Event) -> tuple:
        """Create a new event. Returns (created: bool, event_id: int)."""
        date_value = event.date
        if isinstance(date_value, datetime):
            date_value = date_value.date()
        if not isinstance(date_value, date):
            raise TypeError(f"event.date must be a datetime.date, got {type(date_value)}")
        existing = await self.get_event_by_guild_date_type(event.guild_id, date_value, event.type)
        if existing:
            return (False, existing.id)
        query = """
        INSERT INTO events (guild_id, date, type, name, creator_id, creator_name)
        VALUES ($1, $2::date, $3, $4, $5, $6)
        RETURNING id;
        """
        result = await db_connection.execute_single(
            query, 
            event.guild_id,
            date_value,
            event.type,
            event.name,
            event.creator_id,
            event.creator_name
        )
        return (True, result['id'] if result else None)
    
    async def get_event_by_id(self, event_id: int) -> Optional[Event]:
        """Get an event by its ID."""
        query = "SELECT id, guild_id, date, type, name, creator_id, creator_name FROM events WHERE id = $1"
        
        result = await db_connection.execute_single(query, event_id)
        return Event.from_db_row(result) if result else None
    
    async def get_events_by_guild_and_date_range(self, guild_id: int, start_date: date, end_date: date) -> List[Event]:
        """Get events for a guild within a date range."""
        query = """
        SELECT id, guild_id, date, type, name, creator_id, creator_name 
        FROM events 
        WHERE guild_id = $1 AND date >= $2 AND date <= $3 
        ORDER BY date, type;
        """
        
        results = await db_connection.execute_query(query, guild_id, start_date, end_date)
        return [Event.from_db_row(row) for row in results]
    
    async def get_event_by_guild_date_type(self, guild_id: int, event_date: date, event_type: str) -> Optional[Event]:
        """Get a specific event by guild, date, and type."""
        query = """
        SELECT id, guild_id, date, type, name, creator_id, creator_name 
        FROM events 
        WHERE guild_id = $1 AND date = $2 AND type = $3;
        """
        
        result = await db_connection.execute_single(query, guild_id, event_date, event_type)
        return Event.from_db_row(result) if result else None
    
    async def update_event(self, event_id: int, name: str = None, creator_id: int = None, creator_name: str = None) -> bool:
        """Update an existing event's modifiable fields."""
        update_fields = []
        values = []
        param_count = 1
        
        if name is not None:
            update_fields.append(f"name = ${param_count}")
            values.append(name)
            param_count += 1
            
        if creator_id is not None:
            update_fields.append(f"creator_id = ${param_count}")
            values.append(creator_id)
            param_count += 1
            
        if creator_name is not None:
            update_fields.append(f"creator_name = ${param_count}")
            values.append(creator_name)
            param_count += 1
        
        if not update_fields:
            return False
            
        query = f"""
        UPDATE events 
        SET {', '.join(update_fields)}
        WHERE id = ${param_count}
        """
        values.append(event_id)
        
        result = await db_connection.execute_command(query, *values)
        return result == "UPDATE 1"
    
    async def delete_event(self, event_id: int) -> bool:
        """Delete an event by ID."""
        query = "DELETE FROM events WHERE id = $1"
        result = await db_connection.execute_command(query, event_id)
        return result == "DELETE 1"
    
    async def get_all_events_by_guild(self, guild_id: int) -> List[Event]:
        """Get all events for a guild."""
        query = """
        SELECT id, guild_id, date, type, name, creator_id, creator_name 
        FROM events 
        WHERE guild_id = $1 
        ORDER BY date, type;
        """
        
        results = await db_connection.execute_query(query, guild_id)
        return [Event.from_db_row(row) for row in results]

# Singleton instance
event_repository = EventRepository()