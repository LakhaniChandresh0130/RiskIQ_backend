#!/usr/bin/env python3
"""
Environment validation script for RiskIQ backend.
Run this before starting the server to ensure all required environment variables are set.
"""

import os
import sys
from urllib.parse import urlparse

def validate_url(url, name, scheme='https'):
    """Validate URL format."""
    if not url:
        return False, f"{name} is not set"
    if not url.startswith(scheme):
        return False, f"{name} must start with '{scheme}://'"
    try:
        result = urlparse(url)
        if not result.netloc:
            return False, f"{name} has invalid format"
        return True, "OK"
    except Exception as e:
        return False, f"{name} parsing error: {str(e)}"

def validate_required_vars():
    """Validate required environment variables."""
    required = {
        'DATABASE_URL': ('postgresql://', 'Database connection string'),
        'SUPABASE_URL': ('https://', 'Supabase project URL'),
        'SUPABASE_JWT_SECRET': (None, 'Supabase JWT secret'),
    }

    print("\n=== Required Environment Variables ===\n")
    all_valid = True

    for var, (scheme, description) in required.items():
        value = os.getenv(var)
        print(f"Checking {var}... ", end='')

        if not value:
            print("[X] MISSING")
            print(f"  Description: {description}")
            all_valid = False
            continue

        if scheme:
            valid, msg = validate_url(value, var, scheme)
            if valid:
                print("[OK]")
            else:
                print(f"[X] {msg}")
                all_valid = False
        else:
            print("[OK]")

    return all_valid

def validate_optional_vars():
    """Validate optional environment variables."""
    optional = {
        'GROQ_API_KEY': (None, 'Groq API key for AI features'),
        'GROQ_MODEL': (None, 'AI model name (default: llama-3.3-70b-versatile)'),
        'CORS_ORIGINS': (None, 'Comma-separated list of allowed frontend URLs'),
        'SCHEDULER': (None, 'Set to 1 on one instance for scheduled tasks'),
        'KITE_API_KEY': (None, 'Zerodha Kite API key'),
        'KITE_API_SECRET': (None, 'Zerodha Kite API secret'),
    }

    print("\n=== Optional Environment Variables ===\n")

    for var, (scheme, description) in optional.items():
        value = os.getenv(var)
        print(f"Checking {var}... ", end='')

        if not value:
            print("[ ] NOT SET (optional)")
            print(f"  Description: {description}")
            continue

        if scheme:
            valid, msg = validate_url(value, var, scheme)
            if valid:
                print("[OK]")
            else:
                print(f"[!] {msg}")
        else:
            print("[SET]")

def validate_database_connection():
    """Test database connection."""
    print("\n=== Database Connection Test ===\n")

    try:
        from db import DB
        db = DB()
        if db.test_connection():
            print("[OK] Database connection successful")
            return True
        else:
            print("[X] Database connection failed")
            return False
    except Exception as e:
        print(f"[X] Database connection error: {str(e)}")
        return False

def main():
    """Main validation function."""
    print("=" * 60)
    print("RiskIQ Environment Validation")
    print("=" * 60)

    # Load environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("\n[OK] Loaded .env file")
    except ImportError:
        print("\n[!] python-dotenv not installed, using system environment")

    # Validate required variables
    required_valid = validate_required_vars()

    # Validate optional variables
    validate_optional_vars()

    # Test database connection
    db_valid = validate_database_connection()

    # Summary
    print("\n" + "=" * 60)
    print("Validation Summary")
    print("=" * 60)

    if required_valid and db_valid:
        print("[OK] All required validations passed")
        print("\nYou can start the server with:")
        print("  uvicorn main:app --host 0.0.0.0 --port 8000")
        return 0
    else:
        print("[X] Validation failed")
        if not required_valid:
            print("  - Some required environment variables are missing or invalid")
        if not db_valid:
            print("  - Database connection failed")
        print("\nPlease fix the issues above before starting the server.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
