#!/usr/bin/env python3
"""
Entry point for GOL Discord Bot.
This file serves as the main entry point for hosting platforms like fps.ms.
"""

import asyncio
import sys
import os
from bot import main

if __name__ == "__main__":
    try:
        # Run the bot
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)