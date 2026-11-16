#!/bin/bash

# ADA PDF Accessibility Dashboard - Docker Startup Script
# Similar to ddev experience

set -e

echo "🌪️  Starting ADA PDF Accessibility Dashboard..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose is not installed. Please install docker-compose first."
    exit 1
fi

# Create necessary directories
mkdir -p output
mkdir -p logs

# Build and start containers
echo "🔨 Building Docker images..."
docker-compose build

echo "🚀 Starting containers..."
docker-compose up -d

# Wait for database to be ready
echo "⏳ Waiting for database to be ready..."
sleep 10

# Check if containers are running
echo "🔍 Checking container status..."
docker-compose ps

# Show URLs
echo ""
echo "✅ ADA PDF Accessibility Dashboard is running!"
echo ""
echo "🌐 Frontend: http://localhost:3030"
echo "🔧 Backend API: http://localhost:8000"
echo "📊 API Docs: http://localhost:8000/docs"
echo "🗄️  Database: localhost:5432"
echo "🔴 Redis: localhost:6379"
echo ""
echo "📋 Useful commands:"
echo "   View logs: docker-compose logs -f"
echo "   Stop app: docker-compose down"
echo "   Restart: docker-compose restart"
echo "   Access backend: docker-compose exec backend bash"
echo "   Access database: docker-compose exec db psql -U ada_pdf_user -d ada_pdf"
echo ""
echo "🎯 Happy accessibility testing!"
