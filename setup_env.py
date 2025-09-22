#!/usr/bin/env python3
"""
Setup script to create .env file with SSL configuration to fix handshake failures.
Run this script to create a .env file with SSL verification disabled.
"""

import os

def create_env_file():
    """Create .env file with SSL verification disabled."""
    env_content = """# ICICI Breeze Trading Platform - Environment Variables
# SSL Configuration - Disabled to fix handshake failures
SSL_VERIFY=false

# Application settings
APP_NAME=ICICI Breeze Trading Platform
ENVIRONMENT=development

# Breeze API credentials (replace with your actual values)
BREEZE_API_KEY=your_breeze_api_key_here
BREEZE_API_SECRET=your_breeze_api_secret_here
BREEZE_SESSION_TOKEN=your_session_token_here

# Database (optional - leave empty if not using PostgreSQL)
POSTGRES_DSN=

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Market holidays
HOLIDAYS_CSV_PATH=src/HolidaycalenderData.csv
MARKET_HOLIDAYS=2024-01-26,2024-03-25,2024-08-15

# Application behavior
INSTRUMENTS_FIRST_RUN_ON_LOGIN=true

# Frontend URLs
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_API_BASE_WS=ws://127.0.0.1:8000
"""
    
    with open('.env', 'w') as f:
        f.write(env_content)
    
    print("✅ Created .env file with SSL verification disabled")
    print("📝 Please update the Breeze API credentials in the .env file")
    print("🔧 You can now start the server with: uvicorn backend.app:app --reload")

if __name__ == "__main__":
    create_env_file()
