import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Configuration class for bot settings."""
    
    # Discord Configuration
    DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    GUILD_ID = int(os.getenv('GUILD_ID', 0))
    
    # Database Configuration
    NEONDB_CONNECTION_STRING = os.getenv('NEONDB_CONNECTION_STRING')
    
    # Bot Configuration
    BOT_PREFIX = os.getenv('BOT_PREFIX', '!')
    DEBUG_MODE = os.getenv('DEBUG_MODE', 'False').lower() == 'true'
    BOT_VERSION = os.getenv('BOT_VERSION', 'v1.0.0')
    
    @classmethod
    def validate_config(cls):
        """Validate that all required configuration is present."""
        required_vars = [
            ('DISCORD_BOT_TOKEN', cls.DISCORD_BOT_TOKEN),
            ('GUILD_ID', cls.GUILD_ID),
            ('NEONDB_CONNECTION_STRING', cls.NEONDB_CONNECTION_STRING)
        ]
        
        missing_vars = [var_name for var_name, var_value in required_vars if not var_value]
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        return True