import os
import uuid
import subprocess
import time
import sys
import traceback
import atexit
import signal
from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
from celery.result import AsyncResult
from tasks import celery_app , MODELS_BASE_DIR

# MODELS_BASE_DIR = r"models"

def list_available_models_flask():
    if not os.path.isdir(MODELS_BASE_DIR):
        print(f"[Flask App] Warning: Models directory not found at {MODELS_BASE_DIR}")
        return []
    try: return sorted([f for f in os.listdir(MODELS_BASE_DIR) if f.lower().endswith('.onnx')])
    except OSError as e:
        print(f"[Flask App] Error listing models directory: {e}")
        return []

AVAILABLE_MODELS = list_available_models_flask()
print(f"[Flask] Found {len(AVAILABLE_MODELS)} available Piper models.")

app = Flask(__name__)

# Defining constants and paths
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['AUDIO_FOLDER'] = os.path.join('static', 'audio')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['AUDIO_FOLDER'], exist_ok=True)
REDIS_SERVER_PATH = r"Redis-x64-3.0.504\redis-server.exe"
background_processes = []

def cleanup_background_processes():
    print("--- Flask App Exiting: Attempting to Terminate Background Processes ---")
    for proc, name in background_processes:
        if proc.poll() is None: # Check if process is still running
            print(f"Terminating {name} (PID: {proc.pid})...")
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                    print(f"{name} terminated gracefully.")
                except subprocess.TimeoutExpired:
                    print(f"{name} did not terminate gracefully, killing...")
                    proc.kill()
                    print(f"{name} killed.")
            except Exception as e: print(f"Error terminating {name}: {e}")
        else: print(f"{name} (PID: {proc.pid}) already terminated.")

    print("--- Cleanup Complete ---")

atexit.register(cleanup_background_processes)

def signal_handler(sig, frame):
    print("\nCtrl+C detected!")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# Routes
@app.route('/')
def index(): return render_template('index.html')

@app.route('/models')
def get_models(): return jsonify(AVAILABLE_MODELS)

@app.route('/convert', methods=['POST'])
def start_conversion_job():

    if 'pdf_file' not in request.files: return jsonify({"status": "error", "message": "No file part."}), 400
    file = request.files['pdf_file']
    original_filename = file.filename
    selected_model = request.form.get('selected_model')

    if original_filename == '' or not original_filename.lower().endswith('.pdf'): return jsonify({"status": "error", "message": "Invalid file (must be a PDF)."}), 400
    if not selected_model: return jsonify({"status": "error", "message": "No TTS model selected."}), 400
    if selected_model not in AVAILABLE_MODELS: print(f"[Flask] Warning: Client requested model '{selected_model}' which is not in the known list: {AVAILABLE_MODELS}")

    pdf_path = None

    try:
        secured_filename = secure_filename(original_filename)
        unique_id = str(uuid.uuid4())
        pdf_filename_internal = f"{unique_id}_{secured_filename}"
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_filename_internal)
        file.save(pdf_path)
        print(f"[Flask] Received '{original_filename}'. Saved: {pdf_path}")
        print(f"[Flask] Selected Model: {selected_model}")

        from tasks import task_convert_pdf
        task = task_convert_pdf.delay(pdf_path, original_filename, selected_model)
        print(f"[Flask] Sent task to Celery queue. Task ID: {task.id}")

        return jsonify({"status": "queued", "task_id": task.id, "message": "Conversion task submitted." })

    except Exception as e:
        print(f"[Flask] Error in /convert for '{original_filename}': {e}")
        print(traceback.format_exc())
        
        if pdf_path and os.path.exists(pdf_path):
             try: os.remove(pdf_path)
             except OSError: pass

        return jsonify({"status": "error", "message": f"Server error processing request."}), 500

@app.route('/status/<task_id>')
def get_task_status(task_id):
    task_result = AsyncResult(task_id, app=celery_app)
    response = {'task_id': task_id, 'status': task_result.state, 'info': None, 'message': '' }
    state = task_result.state
    info = task_result.info
    print(f"[Flask] Status check for Task: {task_id}")

    if state == 'PENDING': response['message'] = 'Waiting in queue...'
    elif state == 'PROGRESS':
        response['message'] = 'Processing...'
        response['info'] = info
    elif state == 'SUCCESS':
        result = task_result.result
        response['message'] = result.get('message', 'Completed.') if isinstance(result, dict) else 'Completed.'
        response['info'] = result
        
        if isinstance(result, dict):
            audio_filename = result.get('audio_filename')
            
            if audio_filename: 
                response['audio_url'] = f"/static/audio/{audio_filename}"
                response['download_url'] = f"/download/{audio_filename}"
            else:
                response['status'] = 'FAILURE'
                response['message'] = 'Success reported but result data missing.'
                print(f"[Flask] Task {task_id} SUCCESS but result data incomplete: {result}")

        else:
             response['status'] = 'FAILURE'
             response['message'] = 'Unexpected result format from task.'
             print(f"[Flask] Task {task_id} SUCCESS but unexpected result type: {type(result)} - {result}")

    elif state == 'FAILURE':
        response['message'] = 'Task failed.'
        error_details = 'Unknown error.'
        if isinstance(info, Exception): error_details = str(info)
        elif isinstance(info, dict) and 'exc_message' in info: error_details = str(info.get('exc_message', 'Unknown failure'))
        elif isinstance(info, dict): error_details = info.get('error_message', str(info))
        elif info: error_details = str(info)

        response['error_details'] = error_details

    else: response['message'] = f'State: {state}'

    print(f"[Flask] Task {task_id} -> Status: {response['status']} Message: {response['message']}")
    return jsonify(response)


@app.route('/download/<filename>')
def download_file(filename):
    safe_filename = secure_filename(filename)

    if safe_filename != filename or not safe_filename.endswith('.mp3'): return jsonify({"status": "error", "message": "Invalid filename."}), 400
    file_path = os.path.join(app.config['AUDIO_FOLDER'], safe_filename)
    if os.path.exists(file_path):
        task_id = filename.split('.')[0]
        download_name_hint = "audiobook"
        orig_fn=None
        print(f"[Flask] Serving download: {file_path}")

        try:
            task_result = AsyncResult(task_id, app=celery_app)
            if task_result.state == 'SUCCESS' and isinstance(task_result.result, dict):
                 orig_fn = task_result.result.get('original_filename')
                 if orig_fn: download_name_hint = os.path.splitext(secure_filename(orig_fn))[0]
        except Exception: pass

        download_name = f"{download_name_hint}.mp3"
        return send_file(file_path, as_attachment=True, download_name=download_name)
    
    else:
        task_id = filename.split('.')[0]
        task_result = AsyncResult(task_id, app=celery_app)
        state = task_result.state
        print(f"[Flask] Download 404 for: {safe_filename}. Task state: {state}")
        message = "Audio file not found."

        if state == 'SUCCESS': message += " Conversion completed but file not found."
        if state == 'FAILURE': message += " Conversion failed."
        elif state in ['PENDING', 'PROGRESS', 'STARTED', 'RETRY']: message += " Conversion is processing or queued."

        return jsonify({"status": "error", "message": message}), 404

if __name__ == '__main__':
    print("--- PDF to Audio Converter ---")

    # Redis Server
    redis_log_file = 'logs/redis-server.log'
    os.makedirs(os.path.dirname(redis_log_file), exist_ok=True)
    print(f"Attempting to start Redis server ({REDIS_SERVER_PATH})...")
    print(f"Output will be redirected to: {redis_log_file}")

    try:
        if not os.path.exists(REDIS_SERVER_PATH): raise FileNotFoundError(f"Redis server not found at: {REDIS_SERVER_PATH}")

        with open(redis_log_file, 'wb') as rlog:
            creationflags = subprocess.CREATE_NO_WINDOW
            redis_proc = subprocess.Popen([REDIS_SERVER_PATH], stdout=rlog, stderr=subprocess.STDOUT, creationflags=creationflags )
        print(f"Redis server process started (PID: {redis_proc.pid}). Waiting briefly...")

        background_processes.append((redis_proc, "Redis Server"))
        time.sleep(5)
        
        if redis_proc.poll() is not None: raise RuntimeError(f"Redis server failed to stay running. Check {redis_log_file}")

    except Exception as e:
        print(f"[ERROR] Failed to start Redis server: {e}")
        print("Please start Redis manually and restart this application.")
        sys.exit(1)

    # --- Celery
    celery_log_file = 'logs/celery-worker.log'
    os.makedirs(os.path.dirname(celery_log_file), exist_ok=True)
    print(f"Attempting to start Celery worker...")
    print(f"Output will be redirected to: {celery_log_file}")

    try:
        celery_command = [sys.executable, "-m", "celery", "-A", "tasks", "worker", "--loglevel=info", "-P", "threads" ]
        print(f"Worker command: {' '.join(celery_command)}")
        with open(celery_log_file, 'wb') as clog:
             creationflags = subprocess.CREATE_NO_WINDOW
             celery_proc = subprocess.Popen(celery_command, stdout=clog, stderr=subprocess.STDOUT, creationflags=creationflags )
        print(f"Celery worker process started (PID: {celery_proc.pid}). Waiting briefly...")

        background_processes.append((celery_proc, "Celery Worker"))
        time.sleep(5)
        
        if celery_proc.poll() is not None: raise RuntimeError(f"Celery worker failed to stay running. Check {celery_log_file}")

    except Exception as e:
        print(f"[ERROR] Failed to start Celery worker: {e}")
        print("Attempting to clean up Redis...")
        cleanup_background_processes()
        sys.exit(1)

    # Flask App
    print("-----------------------------------")
    print("Starting Flask application...")
    print("!!! Background process cleanup on exit is best-effort on Windows !!!")
    print(f"--- Found Models: {len(AVAILABLE_MODELS)} ---")
    print("-----------------------------------")
    
    app.run(debug=False, host='127.0.0.1', port=5000, threaded=True)