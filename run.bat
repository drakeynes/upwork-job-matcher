@echo off
echo Starting Upwork Job Scraper Pipeline...

:: 1. Scrape Jobs
echo [Step 1] Scraping Jobs...
python execution/upwork_apify_scraper.py ^
  --search-queries "workflow automation,api integration,ai automation,process automation,internal ops,system integration" ^
  --limit 50 ^
  --days 3 ^
  --verified-payment ^
  --min-spent 1000 ^
  --experience entry,intermediate ^
  -o .tmp/upwork_jobs.json

if %ERRORLEVEL% NEQ 0 (
    echo Scraping failed! Exiting.
    exit /b %ERRORLEVEL%
)

:: 2. Generate Proposals
echo [Step 2] Generating Proposals...
echo (Ensure you have updated config/bio.txt with your details)
python execution/upwork_proposal_generator.py ^
  --input .tmp/upwork_jobs.json ^
  --workers 5 ^
  -o .tmp/upwork_proposals.json

echo Pipeline Complete! Check Google Drive and Sheets.
