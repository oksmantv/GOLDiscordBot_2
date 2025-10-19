
from dataclasses import dataclass
import datetime
from typing import Optional

@dataclass
class Event:
    """Event model representing a schedule entry."""
    id: Optional[int] = None
    guild_id: int = 0
    date: Optional[datetime.date] = None
    type: str = ""  # "Training" or "Mission"
    name: str = ""
    creator_id: int = 0
    creator_name: str = ""
    
    @classmethod
    def from_db_row(cls, row):
        """Create Event instance from database row."""
        return cls(
            id=row[0],
            guild_id=row[1], 
            date=row[2],
            type=row[3],
            name=row[4],
            creator_id=row[5],
            creator_name=row[6]
        )
    
    def to_tuple(self):
        """Convert to tuple for database insertion (excluding id)."""
        return (
            self.guild_id,
            self.date,
            self.type,
            self.name,
            self.creator_id,
            self.creator_name
        )