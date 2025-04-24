# PDF to Audiobook Converter

This project converts PDF documents into MP3 audiobooks using text-to-speech. It uses Flask for the web interface, Celery for background task processing, Redis as a message broker, and Piper TTS for voice generation.

## Features

*   Upload PDF files via a web interface.
*   Select different TTS voice models (using Piper).
*   Convert PDF text to MP3 audio in the background.
*   Track conversion progress.
*   Play the generated audio in the browser.
*   Download the final MP3 audiobook.
*   Light/Dark theme toggle.

## Technology Stack

*   Python 3.x
*   Flask (Web Framework)
*   Celery (Background Tasks)
*   Redis (Message Broker / Result Backend)
*   Piper TTS (Text-to-Speech Engine)
*   FFmpeg (Audio Manipulation)
*   PyPDF2 (PDF Text Extraction)
*   HTML / CSS / JavaScript (Frontend)

## Setup and Installation (Local Development)

These instructions are for running the project locally for development or testing.

**1. Prerequisites:**

*   **Python 3:** Make sure Python 3 (preferably 3.9+) is installed.
*   **Git:** Needed to clone the repository.
*   **Redis:** Install Redis server (pip install redis). *Note: The included code currently assumes a specific local Redis executable path for Windows (`Redis-x64-3.0.504`), you may need to adjust `REDIS_SERVER_PATH` in `app.py` or start Redis manually.*
*   **FFmpeg:** Install FFmpeg. Download from [ffmpeg.org](https://ffmpeg.org/download.html) or use a package manager. Ensure the `ffmpeg` command is available in your system's PATH.
*   **Piper TTS:**
    *   Download the appropriate Piper TTS executable for your operating system from the [Piper releases page](https://github.com/rhasspy/piper/releases).
    *   Create a `piper` directory in the root of this project.
    *   Place the downloaded `piper` executable inside the `piper` directory.
    *   Create a directory `models` in the root.
    *   Download the desired `.onnx` voice models (and their `.onnx.json` files) from [Hugging Face](https://huggingface.co/rhasspy/piper-voices/tree/main) or other sources.
    *   Place the `.onnx` and `.onnx.json` model files inside the `models` directory.
    *   *Verify the `PIPER_PATH` and `MODELS_BASE_DIR` variables in `tasks.py` point correctly to your executable and models folder.*

**2. Clone the Repository:**

```bash
git clone <your-github-repo-url>
cd <repository-folder-name>