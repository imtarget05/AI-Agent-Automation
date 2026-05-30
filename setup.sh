#!/bin/bash
# Setup script for Personal AI Agent Platform

set -e

echo "🚀 Setting up Personal AI Agent Platform..."

# 1. Create .env from template
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cp .env.example .env
    echo "⚠️  Please edit .env and add your API keys!"
else
    echo "✅ .env already exists"
fi

# 2. Create Python virtual environment
if [ ! -d venv ]; then
    echo "🐍 Creating Python virtual environment..."
    python3.12 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi

# 3. Initialize databases
echo "🗄️  Initializing databases..."
docker-compose up -d postgres redis qdrant
sleep 5  # Wait for services to start

# 4. Run migrations (when using SQLAlchemy)
# alembic upgrade head

echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Edit .env with your API keys:"
echo "   - OPENAI_API_KEY=sk-..."
echo "   - ANTHROPIC_API_KEY=sk-ant-..."
echo "   - FB_PAGE_TOKEN=..."
echo "   - ZALO_OA_TOKEN=..."
echo ""
echo "2. Start services:"
echo "   docker-compose up -d"
echo ""
echo "3. Check health:"
echo "   curl http://localhost:8000/health"
echo ""
echo "4. Access API docs:"
echo "   http://localhost:8000/docs"
