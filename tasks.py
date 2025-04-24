import os
import tempfile
import subprocess
import time
from celery import Celery
from PyPDF2 import PdfReader
import celery_config

# Defining constants and paths
PIPER_PATH = r"piper\piper.exe"
MODELS_BASE_DIR = r"models"
FFMPEG_PATH = 'ffmpeg'
UPLOAD_FOLDER = 'uploads'
AUDIO_FOLDER = os.path.join('static', 'audio')

def get_available_model_filenames():
    if not os.path.isdir(MODELS_BASE_DIR):
        print(f"[Worker] Warning: Models directory not found at {MODELS_BASE_DIR}")
        return []
    try: return [f for f in os.listdir(MODELS_BASE_DIR) if f.lower().endswith('.onnx')]
    except OSError as e:
        print(f"[Worker] Error listing models directory: {e}")
        return []

# Initialize Celery
celery_app = Celery('tasks', broker=celery_config.broker_url, backend=celery_config.result_backend)
celery_app.config_from_object(celery_config)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

def extract_text_from_pdf(pdf_path):
    text = ""
    
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PdfReader(file)
            page_count = len(pdf_reader.pages)
            print(f"[Worker] Extracting text from {page_count} pages in {os.path.basename(pdf_path)}...")

            for i, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                if page_text:
                    # Cleaning
                    page_text = ' '.join(page_text.split()) + "\n"
                    text += page_text

        if not text.strip():
            raise ValueError("No text found in PDF (image-based or empty?).")
        print(f"[Worker] Extracted {len(text)} characters.")

        return text
    
    except Exception as e:
        print(f"[Worker] Error reading PDF: {e}")
        raise ValueError(f"Could not read or process PDF '{os.path.basename(pdf_path)}': {e}")

def create_text_chunks(text, chunk_size=2500):
    chunks = []
    current_pos = 0
    text_len = len(text)

    while current_pos < text_len:
        end_pos = min(current_pos + chunk_size, text_len)
        sentence_end = text.rfind('.', current_pos, end_pos + 1)
        if sentence_end > current_pos + (chunk_size // 2):
            end_pos = sentence_end + 1
        elif end_pos < text_len:
             space_pos = text.rfind(' ', current_pos, end_pos)
             if space_pos > current_pos + (chunk_size // 3):
                  end_pos = space_pos + 1

        chunks.append(text[current_pos:end_pos].strip())
        current_pos = end_pos

    return [chunk for chunk in chunks if chunk]

@celery_app.task(bind=True)
def task_convert_pdf(self, pdf_path, original_filename, selected_model_filename):
    task_id = self.request.id
    print(f"[Task {task_id}] Starting chunked conversion for '{original_filename}'")
    print(f"[Task {task_id}] Using model: {selected_model_filename}")

    self.update_state(state='PROGRESS', meta={'status': 'Starting...', 'percent': 1})
    temp_files_to_clean = []
    audio_path = None
    start_time = time.time()
    chunk_wav_files = []

    full_model_path = os.path.join(MODELS_BASE_DIR, selected_model_filename)
    if not os.path.exists(full_model_path):
        error_msg = f"Selected model file not found by worker: {selected_model_filename} (looked for {full_model_path})"
        print(f"[Task {task_id}] *** FATAL ERROR: {error_msg} ***")

        self.update_state(state='FAILURE', meta={'error_message': error_msg, 'status': 'Failed'})
        raise FileNotFoundError(error_msg)
    try:
        self.update_state(state='PROGRESS', meta={'status': 'Extracting text...', 'percent': 5})
        full_text = extract_text_from_pdf(pdf_path)

        CHUNK_SIZE = 2500
        text_chunks = create_text_chunks(full_text, CHUNK_SIZE)
        num_chunks = len(text_chunks)
        print(f"[Task {task_id}] Text split into {num_chunks} chunks (approx size {CHUNK_SIZE}).")

        if num_chunks == 0: raise ValueError("No text chunks generated after splitting.")
        self.update_state(state='PROGRESS', meta={'status': f'Split into {num_chunks} chunks.', 'percent': 10})

        initial_piper_percent = 15
        piper_percent_range = 70

        for i, chunk in enumerate(text_chunks):
            chunk_num = i + 1
            progress_percent = initial_piper_percent + int((chunk_num / num_chunks) * piper_percent_range)
            self.update_state(state='PROGRESS', meta={'status': f'Processing chunk {chunk_num}/{num_chunks} with Piper...', 'percent': progress_percent})
            chunk_wav_file = tempfile.NamedTemporaryFile(delete=False, suffix=f"_chunk{chunk_num}.wav")
            chunk_wav_path = chunk_wav_file.name
            chunk_wav_file.close()
            temp_files_to_clean.append(chunk_wav_path)
            print(f"[Task {task_id} Chunk {chunk_num}] Target WAV: {chunk_wav_path}")

            piper_command = [ PIPER_PATH, '--model', full_model_path, '--output_file', chunk_wav_path ]
            print(f"[Task {task_id} Chunk {chunk_num}] Running Piper ({len(chunk)} chars)...")

            piper_start = time.time()
            piper_result = subprocess.run(piper_command, input=chunk, capture_output=True, text=True, check=False, encoding='utf-8')
            piper_dur = time.time() - piper_start
            print(f"[Task {task_id} Chunk {chunk_num}] Piper finished in {piper_dur:.2f}s. Code: {piper_result.returncode}")

            if piper_result.returncode != 0:
                 stderr = piper_result.stderr[:500]
                 raise RuntimeError(f"Piper failed on chunk {chunk_num} (Code {piper_result.returncode}). Model: {selected_model_filename}. Error: {stderr}")
            if not os.path.exists(chunk_wav_path) or os.path.getsize(chunk_wav_path) == 0:
                 print(f"[Task {task_id} Chunk {chunk_num}] Warning: Piper created empty/missing WAV for model {selected_model_filename}. Skipping chunk audio.")
                 if chunk_wav_path in temp_files_to_clean: temp_files_to_clean.remove(chunk_wav_path)
                 try: os.remove(chunk_wav_path)
                 except OSError: pass
            else: chunk_wav_files.append(chunk_wav_path)
        
        # Concatenate WAV files
        self.update_state(state='PROGRESS', meta={'status': 'Joining audio chunks...', 'percent': 90})
        if not chunk_wav_files: raise RuntimeError("No valid audio chunks were generated by Piper.")
        concat_list_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode='w', encoding='utf-8')
        concat_list_content = ""

        for wav_file in chunk_wav_files:
             safe_path = wav_file.replace('\\', '/')
             line = f"file '{safe_path}'\n"
             concat_list_file.write(line)
             concat_list_content += line

        concat_list_path = concat_list_file.name
        concat_list_file.close()
        temp_files_to_clean.append(concat_list_path)
        print(f"[Task {task_id}] Created FFmpeg concat list: {concat_list_path}")
        print(f"[Task {task_id}] Concat List File Content:\n---\n{concat_list_content}---")

        combined_wav_file = tempfile.NamedTemporaryFile(delete=False, suffix="_combined.wav")
        combined_wav_path = combined_wav_file.name
        combined_wav_file.close()
        temp_files_to_clean.append(combined_wav_path)
        print(f"[Task {task_id}] Target combined WAV: {combined_wav_path}")

        ffmpeg_concat_command = [ FFMPEG_PATH, '-y', '-f', 'concat', '-safe', '0', '-i', concat_list_path, '-c', 'copy', combined_wav_path ]
        print(f"[Task {task_id}] Running FFmpeg concat...")

        ffmpeg_cat_start = time.time()
        ffmpeg_cat_result = subprocess.run(ffmpeg_concat_command, capture_output=True, text=True, check=False)
        ffmpeg_cat_dur = time.time() - ffmpeg_cat_start
        print(f"[Task {task_id}] FFmpeg concat finished in {ffmpeg_cat_dur:.2f}s. Code: {ffmpeg_cat_result.returncode}")

        if ffmpeg_cat_result.returncode != 0:
            stderr = ffmpeg_cat_result.stderr[:1000]
            print(f"[Task {task_id}] FFmpeg concat Error Output:\n{stderr}")
            raise RuntimeError(f"FFmpeg failed to concatenate WAV chunks (Code {ffmpeg_cat_result.returncode}). Error: {stderr[:200]}...")
        
        if not os.path.exists(combined_wav_path) or os.path.getsize(combined_wav_path) == 0:
             print(f"[Task {task_id}] FFmpeg concat Error Output:\n{ffmpeg_cat_result.stderr}")
             raise RuntimeError("FFmpeg concat produced an empty or missing combined WAV file.")
        
        else: print(f"[Task {task_id}] Combined WAV file OK. Size: {os.path.getsize(combined_wav_path)} bytes")

        # Encode Combined WAV to MP3
        self.update_state(state='PROGRESS', meta={'status': 'Encoding final MP3...', 'percent': 95})
        audio_filename = f"{task_id}.mp3"
        audio_path = os.path.join(AUDIO_FOLDER, audio_filename)
        ffmpeg_encode_command = [ FFMPEG_PATH, '-i', combined_wav_path, '-y', '-vn', '-b:a', '192k', audio_path ]
        print(f"[Task {task_id}] Running FFmpeg encode to MP3...")

        ffmpeg_enc_start = time.time()
        ffmpeg_enc_result = subprocess.run( ffmpeg_encode_command, capture_output=True, text=True, check=False)
        ffmpeg_enc_dur = time.time() - ffmpeg_enc_start
        print(f"[Task {task_id}] FFmpeg encode finished in {ffmpeg_enc_dur:.2f}s. Code: {ffmpeg_enc_result.returncode}")

        if ffmpeg_enc_result.returncode != 0:
            stderr = ffmpeg_enc_result.stderr[:1000]
            print(f"[Task {task_id}] FFmpeg encode Error Output:\n{stderr}")
            if "not found" in stderr.lower() or "no such file" in stderr.lower():
                raise RuntimeError(f"FFmpeg command '{FFMPEG_PATH}' not found.")
            raise RuntimeError(f"FFmpeg failed final MP3 encoding (Code {ffmpeg_enc_result.returncode}). Error: {stderr[:200]}...") 
        else: print(f"[Task {task_id}] Final MP3 file OK: {audio_path}")

        end_time = time.time()
        total_duration = round(end_time - start_time, 2)
        print(f"[Task {task_id}] Chunked Conversion SUCCESSFUL. Total time: {total_duration:.2f}s")

        return {'status': 'success', 'message': 'Conversion successful.', 'audio_filename': audio_filename, 'original_filename': original_filename, 'selected_model': selected_model_filename, 'duration_seconds': total_duration, 'num_chunks_processed': len(chunk_wav_files), 'audio_filesize_bytes': os.path.getsize(audio_path) if audio_path and os.path.exists(audio_path) else 0}

    except Exception as e:
        error_message = str(e)
        self.update_state(state='FAILURE', meta={'error_message': error_message, 'status': 'Failed'})
        print(f"[Task {task_id}] *** Chunked Task Failed! *** Model: {selected_model_filename}. Error: {error_message}")

        if audio_path and os.path.exists(audio_path):
             try: os.remove(audio_path); print(f"[Task {task_id}] Removed potentially failed output MP3.")
             except OSError: pass
        raise e # Re-raise for Celery

    finally:
        cleaned_count = 0
        print(f"[Task {task_id}] Cleaning up {len(temp_files_to_clean)} temporary file(s)...")

        for temp_file in temp_files_to_clean:
             if temp_file and os.path.exists(temp_file):
                  try:
                      os.remove(temp_file)
                      cleaned_count += 1
                  except OSError as e: print(f"[Task {task_id}] Warning: Failed to remove temp file {temp_file}: {e}")
                  
        print(f"[Task {task_id}] Cleanup finished (removed {cleaned_count}).")