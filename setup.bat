@echo off
REM Setup script for Windows
REM Personal AI Agent Platform initialization

echo.
echo 🚀 Setting up Personal AI Agent Platform...
echo.

REM 1. Create .env
if not exist .env (
    echo 📝 Creating .env file...
    copy .env.example .env
    echo ⚠️  Please edit .env and add your API keys!
) else (
    echo ✅ .env already exists
)

REM 2. Create Python virtual environment
if not exist venv (
    echo 🐍 Creating Python virtual environment...
    python -m venv venv
    call venv\Scripts\activate
    pip install -r requirements.txt
    echo ✅ Virtual environment created
) else (
    echo ✅ Virtual environment already exists
)

REM 3. Start Docker services
echo 🐳 Starting Docker services...
docker-compose up -d postgres redis qdrant

echo.
echo ✅ Setup complete!
echo.
echo 📋 Next steps:
echo 1. Edit .env with your API keys
echo 2. Run: docker-compose up -d
echo 3. Check: http://localhost:8000/health
echo 4. Docs: http://localhost:8000/docs
echo.
