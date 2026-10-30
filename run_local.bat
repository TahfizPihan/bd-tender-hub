@echo off
REM Runs the collector on THIS computer (Bangladesh internet), then uploads the result to GitHub.
REM Needs once: Python 3.12+ and Git installed, and this folder cloned from your GitHub repo.
cd /d "%~dp0"
git pull --rebase
python -m pip install -q -r requirements.txt
python -m playwright install chromium
python -m scraper.collect
git add docs/tenders.json data/
git commit -m "Update tenders (local run)"
git push
echo Done. Reload your tender page.
pause
