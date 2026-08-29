# START-ALL SCRIPT
# Opens a new terminal tab for each piece of the system and starts it
# automatically, so you don't have to do this by hand every session.

$root = "C:\Users\dhung\OneDrive\Desktop\infra-automation (1)\infra-automation"

Write-Host "Starting Postgres and Redis (Docker)..."
docker compose up -d
Start-Sleep -Seconds 2

Write-Host "Opening simulator..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\simulator'; python fake_server.py"

Start-Sleep -Seconds 2

Write-Host "Opening orchestrator..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\orchestrator'; python app.py"

Start-Sleep -Seconds 2

Write-Host "Opening worker..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\orchestrator'; python worker.py"

Write-Host ""
Write-Host "All set! Simulator (5001), Orchestrator (5000), Worker, Postgres, and Redis are starting up in separate windows."
Write-Host "Run this same terminal for testing/curl commands."