-- Create database schema for accessibility crawler
-- This script runs automatically when the database container starts

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Sites table for tracking different platforms
CREATE TABLE IF NOT EXISTS sites (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    url VARCHAR(500) NOT NULL UNIQUE,
    platform VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_crawled_at TIMESTAMP WITH TIME ZONE
);

-- Pages table for storing crawled page data
CREATE TABLE IF NOT EXISTS pages (
    id SERIAL PRIMARY KEY,
    site_id INTEGER REFERENCES sites(id) ON DELETE CASCADE,
    url VARCHAR(500) NOT NULL,
    title TEXT,
    status_code INTEGER,
    content_type VARCHAR(100),
    content_length BIGINT,
    html_content TEXT,
    crawl_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    platform VARCHAR(100),
    site_name VARCHAR(255),
    source_page VARCHAR(500),
    
    -- Accessibility fields
    issue_count INTEGER DEFAULT 0,
    accessibility_score INTEGER DEFAULT 100,
    wcag_compliant BOOLEAN DEFAULT NULL,
    
    -- PDF-specific fields
    pdf_analysis JSONB DEFAULT NULL,
    
    -- Archive flag (page/PDF has an archive notice message)
    is_archived BOOLEAN DEFAULT FALSE,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Unique constraint on URL per site
    UNIQUE(site_id, url)
);

-- Links table for storing page relationships
CREATE TABLE IF NOT EXISTS page_links (
    id SERIAL PRIMARY KEY,
    from_page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    to_url TEXT NOT NULL,
    link_text TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Images table for storing image data
CREATE TABLE IF NOT EXISTS page_images (
    id SERIAL PRIMARY KEY,
    page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    src VARCHAR(500) NOT NULL,
    alt TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Forms table for storing form data
CREATE TABLE IF NOT EXISTS page_forms (
    id SERIAL PRIMARY KEY,
    page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    form_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Headings table for storing heading structure
CREATE TABLE IF NOT EXISTS page_headings (
    id SERIAL PRIMARY KEY,
    page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    heading_type VARCHAR(10) NOT NULL, -- h1, h2, h3, etc.
    heading_text TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Accessibility issues table
CREATE TABLE IF NOT EXISTS accessibility_issues (
    id SERIAL PRIMARY KEY,
    page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    rule_id VARCHAR(100) NOT NULL,
    rule_title TEXT NOT NULL,
    description TEXT,
    wcag_level VARCHAR(20),
    severity VARCHAR(20),
    element TEXT,
    element_type VARCHAR(50),
    recommendation TEXT,
    line_number INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- PDF analysis history table
CREATE TABLE IF NOT EXISTS pdf_analysis_history (
    id SERIAL PRIMARY KEY,
    pdf_url VARCHAR(500) NOT NULL,
    analysis_result JSONB NOT NULL,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Crawl sessions table for tracking crawl runs
CREATE TABLE IF NOT EXISTS crawl_sessions (
    id SERIAL PRIMARY KEY,
    session_name VARCHAR(255),
    platform VARCHAR(100),
    start_time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    end_time TIMESTAMP WITH TIME ZONE,
    pages_crawled INTEGER DEFAULT 0,
    total_issues INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'running', -- running, completed, failed
    config JSONB DEFAULT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_pages_site_id ON pages(site_id);
CREATE INDEX IF NOT EXISTS idx_pages_url ON pages(url);
CREATE INDEX IF NOT EXISTS idx_pages_content_type ON pages(content_type);
CREATE INDEX IF NOT EXISTS idx_pages_wcag_compliant ON pages(wcag_compliant);
CREATE INDEX IF NOT EXISTS idx_pages_issue_count ON pages(issue_count);
CREATE INDEX IF NOT EXISTS idx_accessibility_issues_page_id ON accessibility_issues(page_id);
CREATE INDEX IF NOT EXISTS idx_pdf_analysis_history_pdf_url ON pdf_analysis_history(pdf_url);
CREATE INDEX IF NOT EXISTS idx_pages_is_archived ON pages(is_archived);
CREATE INDEX IF NOT EXISTS idx_crawl_sessions_platform ON crawl_sessions(platform);
CREATE INDEX IF NOT EXISTS idx_crawl_sessions_status ON crawl_sessions(status);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_sites_updated_at BEFORE UPDATE ON sites
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_pages_updated_at BEFORE UPDATE ON pages
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
