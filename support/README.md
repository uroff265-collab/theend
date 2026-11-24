# TheEnd Support + Agent (Windows)

Free local control panel and launcher for the TheEnd Agent. It uses Python's standard library for the Support console; the game agent needs the project's OCR dependencies and Tesseract.

## Start
1. Download the repository ZIP from the main branch: https://github.com/uroff265-collab/theend/archive/refs/heads/main.zip
2. Extract the ZIP to a normal folder (not inside OneDrive/Temp).
3. Open `START_THEEND_SUPPORT.bat`.
4. In Support choose:
   - `1` — show task/evidence status
   - `2` — run local audit
   - `3` — see the next missing proof
   - `4` — open GitHub checks
   - `5` — start TheEnd Agent in a separate console window

The Agent launcher `START_THEEND.bat` checks and updates the agent files, installs Python OCR packages, verifies Tesseract and ADB, then expects LDPlayer connected at `127.0.0.1:5555`. Keep LDPlayer open and ADB port 5555 enabled.

## Honest scope
Support checks the repository's task list and evidence, runs local audits, and starts the local Agent. It does not control ChatGPT, does not act as a remote human operator, and cannot mark resource collection complete without game evidence. The cloud Android workflow is a separate experiment; a booted emulator alone is not a persistent browser session or proof of gameplay automation.

No ChatGPT API key is required. Do not put passwords or private tokens into repository files.
