#!/usr/bin/env python3
"""
Clear all data from the accessibility crawler database and JSON output files
"""

import os
import sys
import glob
sys.path.append("src")

from sqlalchemy import create_engine, text
from database import DATABASE_URL, Base

def clear_database():
    """Clear all data from the database"""
    print(f"Connecting to database: {DATABASE_URL}")
    
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        # Get all table names
        result = conn.execute(text("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
        """))
        tables = [row[0] for row in result]
        
        print(f"Found tables: {tables}")
        
        # Disable foreign key constraints temporarily
        conn.execute(text("SET session_replication_role = replica;"))
        
        # Truncate all tables in correct order (child tables first)
        if 'accessibility_issues' in tables:
            conn.execute(text("TRUNCATE TABLE accessibility_issues CASCADE;"))
            print("Cleared accessibility_issues")
        
        if 'accessibility_reports' in tables:
            conn.execute(text("TRUNCATE TABLE accessibility_reports CASCADE;"))
            print("Cleared accessibility_reports")
        
        if 'pages' in tables:
            conn.execute(text("TRUNCATE TABLE pages CASCADE;"))
            print("Cleared pages")
        
        if 'crawl_sessions' in tables:
            conn.execute(text("TRUNCATE TABLE crawl_sessions CASCADE;"))
            print("Cleared crawl_sessions")
        
        if 'sites' in tables:
            conn.execute(text("TRUNCATE TABLE sites CASCADE;"))
            print("Cleared sites")
        
        # Re-enable foreign key constraints
        conn.execute(text("SET session_replication_role = DEFAULT;"))
        
        conn.commit()
        print("✅ Database cleared successfully!")

def clear_json_files():
    """Clear all JSON output files"""
    output_dir = "output"
    if not os.path.exists(output_dir):
        print("No output directory found")
        return
    
    # Clear crawled pages JSON files
    json_files = glob.glob(os.path.join(output_dir, "crawled_pages_*.json"))
    for file in json_files:
        os.remove(file)
        print(f"Deleted {file}")
    
    # Clear accessibility report files
    accessibility_files = glob.glob(os.path.join(output_dir, "accessibility_*.json"))
    for file in accessibility_files:
        os.remove(file)
        print(f"Deleted {file}")
    
    # Clear any latest files
    latest_files = glob.glob(os.path.join(output_dir, "latest_*.json"))
    for file in latest_files:
        os.remove(file)
        print(f"Deleted {file}")
    
    # Clear CSV files
    csv_files = glob.glob(os.path.join(output_dir, "*.csv"))
    for file in csv_files:
        os.remove(file)
        print(f"Deleted {file}")
    
    print("✅ JSON output files cleared successfully!")

if __name__ == "__main__":
    try:
        print("🧹 Clearing database...")
        clear_database()
        
        print("\n🧹 Clearing JSON output files...")
        clear_json_files()
        
        print("\n🎉 All data cleared successfully!")
        
    except Exception as e:
        print(f"❌ Error clearing data: {e}")
        sys.exit(1)
