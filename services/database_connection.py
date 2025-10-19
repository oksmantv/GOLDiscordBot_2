import asyncpg
import asyncio
from typing import Optional
from config import Config

class DatabaseConnection:
    """Handles PostgreSQL database connection for NeonDB."""
    
    def __init__(self):
        self._connection_pool: Optional[asyncpg.Pool] = None
        
    async def create_pool(self):
        """Create connection pool to NeonDB."""
        if self._connection_pool is None:
            try:
                self._connection_pool = await asyncpg.create_pool(
                    Config.NEONDB_CONNECTION_STRING,
                    min_size=1,
                    max_size=10,
                    command_timeout=60
                )
                print("Successfully connected to NeonDB")
            except Exception as e:
                print(f"Failed to connect to database: {e}")
                raise
    
    async def close_pool(self):
        """Close database connection pool."""
        if self._connection_pool:
            await self._connection_pool.close()
            self._connection_pool = None
            print("Database connection pool closed")
    
    async def get_connection(self):
        """Get a connection from the pool."""
        if self._connection_pool is None:
            await self.create_pool()
        return self._connection_pool
    
    async def execute_query(self, query: str, *args):
        """Execute a query and return results."""
        pool = await self.get_connection()
        async with pool.acquire() as connection:
            return await connection.fetch(query, *args)
    
    async def execute_single(self, query: str, *args):
        """Execute a query and return single result."""
        pool = await self.get_connection()
        async with pool.acquire() as connection:
            return await connection.fetchrow(query, *args)
    
    async def execute_command(self, query: str, *args):
        """Execute a command (INSERT, UPDATE, DELETE)."""
        pool = await self.get_connection()
        async with pool.acquire() as connection:
            return await connection.execute(query, *args)

# Singleton instance
db_connection = DatabaseConnection()