document.addEventListener('DOMContentLoaded', function() {
    const body = document.body;
    const themeToggleButton = document.getElementById('theme-toggle');
    const uploadSection = document.getElementById('upload-section');
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('pdf-file');
    const progressSection = document.getElementById('progress-section');
    const progressBar = document.getElementById('progress-bar');
    const progressStatusText = document.getElementById('progress-status-text');
    const progressDetailsText = document.getElementById('progress-details');
    const processingNote = document.getElementById('processing-note');
    const resultSection = document.getElementById('result-section');
    const conversionDetailsDiv = document.getElementById('conversion-details');
    const audioPlayer = document.getElementById('audio-player');
    const downloadBtn = document.getElementById('download-btn');
    const newConversionBtn = document.getElementById('new-conversion-btn');
    const errorMessageDiv = document.getElementById('error-message');
    const modelSelect = document.getElementById('model-select');

    let currentTaskId = null;
    let statusIntervalId = null;
    const POLLING_INTERVAL_MS = 3000;

    setupEventListeners();    
    initializeTheme();      
    fetchAndPopulateModels();

    function setupEventListeners() {
        if (themeToggleButton) {
            themeToggleButton.addEventListener('click', toggleTheme);
        } else { console.warn("Theme toggle button not found."); }

        if (uploadArea) {
            setupDragAndDrop();
             if (fileInput) {
                 setupFileInput();
             } else { console.warn("File input element not found."); }
        } else { console.warn("Upload area element not found."); }

        if (newConversionBtn) {
            newConversionBtn.addEventListener('click', resetUI);
        } else { console.warn("New conversion button not found (expected later)."); }
    }

    async function fetchAndPopulateModels() {
        if (!modelSelect) {
            console.error("Model select dropdown element not found in the DOM.");
            showError("UI Error: Cannot load models, element missing.");
            return;
        }
        try {
            modelSelect.disabled = true;
            modelSelect.innerHTML = '<option value="" disabled selected>Loading models...</option>';
            const response = await fetch('/models');

            if (!response.ok) {
                throw new Error(`Server error ${response.status}: ${response.statusText}`);
            }

            const models = await response.json();
            modelSelect.innerHTML = '';

            if (models && models.length > 0) {
                models.forEach((modelFilename, index) => {
                    const option = document.createElement('option');
                    option.value = modelFilename;
                    option.textContent = modelFilename.replace('.onnx', '');
                    if (!modelSelect.querySelector('option[selected]') && modelFilename.toLowerCase().includes('ryan-high')) {
                        option.selected = true;
                    }
                    modelSelect.appendChild(option);
                });

                 if (!modelSelect.value && modelSelect.options.length > 0) {
                     modelSelect.options[0].selected = true;
                }
                
                modelSelect.disabled = false;

            } else {
                const option = document.createElement('option');
                option.textContent = 'No voice models found.';
                option.disabled = true;
                option.selected = true;
                modelSelect.appendChild(option);
                modelSelect.disabled = true;
                showError("No TTS voice models found in 'models'.");
            }
        } catch (error) {
            console.error('Error fetching or populating models:', error);
            modelSelect.innerHTML = '<option disabled selected>Error loading models</option>';
            modelSelect.disabled = true;
            showError(`Failed to load voice models: ${error.message}`);
        }
    }

    function initializeTheme() {
        applyTheme(localStorage.getItem('theme') || 'light');
    }

    function applyTheme(theme) {
        if (!body) return;
        body.classList.remove('theme-light', 'theme-dark', 'light-mode', 'dark-mode');
        body.classList.add(`theme-${theme}`);
        body.classList.add(`${theme}-mode`);
        localStorage.setItem('theme', theme);

        if (themeToggleButton) {
             const icon = themeToggleButton.querySelector('i');
             if (icon) {
                 if (theme === 'dark') {
                     icon.classList.remove('fa-sun');
                     icon.classList.add('fa-moon');
                 } else {
                     icon.classList.remove('fa-moon');
                     icon.classList.add('fa-sun');
                 }
             }
        }
    }

    function toggleTheme() {
        if (!body) return;
        const currentTheme = body.classList.contains('theme-dark') ? 'dark' : 'light';
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        applyTheme(newTheme);
    }

    function setupDragAndDrop() {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(evt => {
            uploadArea.addEventListener(evt, preventDefaults, false)
        });
        ['dragenter', 'dragover'].forEach(evt => {
            uploadArea.addEventListener(evt, highlight, false)
        });
        ['dragleave', 'drop'].forEach(evt => {
            uploadArea.addEventListener(evt, unhighlight, false)
        });
        uploadArea.addEventListener('drop', handleDrop, false);
    }

    function preventDefaults(e) { e.preventDefault(); e.stopPropagation(); }
    function highlight(e) { uploadArea.classList.add('highlight'); }
    function unhighlight(e) { uploadArea.classList.remove('highlight'); }

    function handleDrop(e) {
        if (!e.dataTransfer || !e.dataTransfer.files) return;
        const file = e.dataTransfer.files[0];
        if (file) {
            if (fileInput) {
                fileInput.files = e.dataTransfer.files; 
            }
            validateAndStartUpload(file);
        }
    }

    function setupFileInput() {
        uploadArea.addEventListener('click', (e) => {
            fileInput.click();
        });

        fileInput.addEventListener('change', handleFileSelect);
    }

    function handleFileSelect(e) {
        const inputElement = e.target;
        if (inputElement.files && inputElement.files.length > 0) {
            validateAndStartUpload(inputElement.files[0]);
        }
    }

    function validateAndStartUpload(file) {
        clearError();

        if (!file) { showError('Internal error: No file provided for validation.'); console.error("validateAndStartUpload called without a file object."); return; }
        if (file.type !== 'application/pdf') { showError('Invalid file type. Please upload a PDF.'); fileInput.value = ''; return; }

        if (!modelSelect) {
            showError("UI Error: Model selection element not found.");
            console.error("Cannot validate model, select element missing.");
            fileInput.value = '';
            return;
        }
        if (!modelSelect.value || modelSelect.disabled || modelSelect.value === "") {
             showError('Please select a voice model.');
             return;
        }

        console.log(`Validation passed for ${file.name}, starting job...`);
        startJob(file);
    }

    function startJob(file) {
        resetUIForProcessing(file.name);

        const formData = new FormData();
        formData.append('pdf_file', file);
        formData.append('selected_model', modelSelect.value);

        console.log(`Submitting /convert for Task: ${file.name} with Model: ${modelSelect.value}`);

        fetch('/convert', { method: 'POST', body: formData })
        .then(handleFetchResponse)
        .then(data => {
            if (data.status === 'queued' && data.task_id) {
                currentTaskId = data.task_id;
                updateUIBasedOnStatus({task_id: currentTaskId, status: 'PENDING', message: 'Task submitted, waiting in queue...', info: { percent: 1, status: 'Queued' }});
                processingNote.textContent = 'Audio generation can take time...';
                processingNote.style.display = 'block';
                startPollingStatus(currentTaskId);
            } else {
                throw new Error(data.message || 'Failed to queue task (invalid response).');
            }
        })
        .catch(error => {
            console.error('Error starting conversion job:', error);
             let displayError = "Failed to start conversion job.";
             if (error.response && error.response.status) {
                 displayError += ` (Status: ${error.response.status})`;
             }
             if (error.data && error.data.message) {
                 displayError = error.data.message;
             } else if (error.message) {
                 displayError = error.message;
             }

            resetUI();
            showError(displayError);
        });
    }

    function startPollingStatus(taskId) {
        stopPolling();
        console.log(`Starting polling for Task ID: ${taskId}`);
        statusIntervalId = setInterval(() => checkStatus(taskId), POLLING_INTERVAL_MS);
    }

    async function checkStatus(taskId) {
        if (!currentTaskId || taskId !== currentTaskId) {
             stopPolling();
             return;
        }
        console.log(`Polling status for task: ${taskId}...`);
        try {
            const response = await fetch(`/status/${taskId}`);

            if (response.status === 404) {
                 console.warn(`Task ${taskId} not found by server (404). Assuming completed or expired.`);
                resetUI();
                stopPolling();
                 return;
            }
            if (!response.ok) {
                 throw new Error(`Status check failed: ${response.status} ${response.statusText}`);
            }

            const data = await response.json();
            updateUIBasedOnStatus(data);

            if (['SUCCESS', 'FAILURE', 'REVOKED'].includes(data.status)) {
                console.log(`Task ${taskId} reached final state: ${data.status}. Stopping polling.`);
                stopPolling();
            }
        } catch (error) {
            console.error('Error polling status:', error);
             showError(`Network error during status check: ${error.message}. Stopping updates.`);
             stopPolling();
        }
    }

    function stopPolling() {
        if (statusIntervalId) {
            clearInterval(statusIntervalId);
            statusIntervalId = null;
            console.log("Polling stopped.");
        }
    }

    async function handleFetchResponse(response) {
        if (!response.ok) {
            let errorMsg = `Request failed: ${response.status} ${response.statusText}`;
            let errorData = null;
            try {
                errorData = await response.json();
                errorMsg = errorData.message || JSON.stringify(errorData);
            } catch (jsonError) {}
            const error = new Error(errorMsg);
            error.response = response; 
            error.data = errorData;   
            throw error;
        }
        if (response.status === 204) return null;
        return response.json();
    }

    function updateUIBasedOnStatus(data) {
        if (!data || !data.task_id) {
            console.warn("updateUIBasedOnStatus received invalid data:", data);
            return;
        }
        if (data.task_id !== currentTaskId && currentTaskId !== null) {
            console.log(`Ignoring status update for old task ${data.task_id}`);
            return;
        }

        let celeryState = data.status;
        let progressPercent = 0;
        let statusMessage = '';
        let detailMessage = '';
        let isProcessing = false;

        if (!progressBar) { console.error("Progress bar element missing!"); return; }

        switch (celeryState) {
            case 'SUCCESS':
                progressBar.style.width = '100%';
                progressBar.classList.remove('indeterminate', 'processing');
                showResult(data);
                break;

            case 'FAILURE':
                progressBar.style.width = '0%';
                progressBar.classList.remove('indeterminate', 'processing');
                showError(data.error_details || data.message || 'Task failed for an unknown reason.');
                if(progressSection) progressSection.style.display = 'none';
                break;

            case 'PROGRESS':
                isProcessing = true;
                let meta = data.info || {};
                progressPercent = (typeof meta.percent === 'number' && meta.percent >= 0 && meta.percent <= 100) ? meta.percent : 50;
                statusMessage = 'Processing...';
                detailMessage = meta.status || 'Working on conversion...';
                progressBar.classList.add('processing');
                progressBar.classList.remove('indeterminate');
                break;

            case 'PENDING':
                isProcessing = true;
                progressPercent = 1;
                statusMessage = 'Waiting in Queue...';
                detailMessage = 'Job waiting for an available worker.';
                progressBar.classList.add('indeterminate');
                progressBar.classList.remove('processing');
                break;

            case 'STARTED':
                isProcessing = true;
                progressPercent = 5;
                statusMessage = 'Task Started...';
                detailMessage = 'Worker has picked up the job.';
                progressBar.classList.add('indeterminate', 'processing');
                break;

             case 'RETRY':
                isProcessing = true;
                progressPercent = 10;
                statusMessage = 'Task Retrying...';
                detailMessage = `An issue occurred, retrying task (Attempt: ${data.info?.retries || 'N/A'}).`;
                progressBar.classList.add('indeterminate', 'processing');
                break;

            default:
                console.warn(`Task ${data.task_id} in unexpected state: ${celeryState}`);
                isProcessing = false;
                statusMessage = `Status: ${celeryState}`;
                detailMessage = `Task is in an unknown state: ${celeryState}.`;
                progressPercent = 0;
                progressBar.classList.remove('indeterminate', 'processing');
                if (progressSection) progressSection.style.display = 'block';
                if (uploadSection) uploadSection.style.display = 'none';
                if (resultSection) resultSection.style.display = 'none';
                if (progressStatusText) progressStatusText.textContent = statusMessage;
                progressBar.style.width = `${progressPercent}%`;
                if (progressDetailsText) progressDetailsText.textContent = detailMessage;
                if (processingNote) processingNote.style.display = 'none';

                return;
        }

         if (isProcessing || ['PENDING', 'STARTED', 'RETRY'].includes(celeryState)) {
             if (progressSection) progressSection.style.display = 'block';
             if (uploadSection) uploadSection.style.display = 'none';
             if (resultSection) resultSection.style.display = 'none';

             if (progressStatusText) progressStatusText.textContent = statusMessage;
             progressBar.style.width = `${progressPercent}%`;
             if (progressDetailsText) progressDetailsText.textContent = detailMessage;
             if (processingNote) processingNote.style.display = (celeryState === 'PROGRESS' || celeryState === 'STARTED' || celeryState === 'RETRY') ? 'block' : 'none';
        }
    }

    function showResult(data) {
        if (!uploadSection || !progressSection || !resultSection || !audioPlayer || !downloadBtn || !conversionDetailsDiv ) {
             console.error("Cannot display results, required UI elements are missing.");
             return;
        }

        uploadSection.style.display = 'none';
        progressSection.style.display = 'none';
        resultSection.style.display = 'block';

        const resultInfo = data.info || {};

        if (data.audio_url && data.download_url) {
            audioPlayer.src = data.audio_url;
            downloadBtn.href = data.download_url;
             let downloadNameBase = "audiobook";
             if (resultInfo.original_filename) {
                 downloadNameBase = secureFilenameForJS(resultInfo.original_filename.replace(/\.[^/.]+$/, ""));
             } else {
                 downloadNameBase = `audio_${data.task_id.substring(0,8)}`;
             }
             downloadBtn.download = `${downloadNameBase}.mp3`;

        } else {
            console.error("Success reported, but audio URLs are missing:", data);
            showError("Conversion completed, but audio file links are missing. Please check server logs.");
            resultSection.style.display = 'none';
            uploadSection.style.display = 'block';
            return;
        }

        conversionDetailsDiv.innerHTML = '';
        let detailsHtml = '';
        if (resultInfo.original_filename) detailsHtml += `<p><i class="fas fa-file-pdf"></i> Source: ${escapeHTML(resultInfo.original_filename)}</p>`;
        if (resultInfo.selected_model) detailsHtml += `<p><i class="fas fa-robot"></i> Voice: ${escapeHTML(resultInfo.selected_model.replace('.onnx',''))}</p>`;
        if (resultInfo.num_chunks_processed) detailsHtml += `<p><i class="fas fa-puzzle-piece"></i> Chunks: ${resultInfo.num_chunks_processed}</p>`;
        if (resultInfo.duration_seconds) detailsHtml += `<p><i class="fas fa-stopwatch"></i> Time: ${resultInfo.duration_seconds} s</p>`;
        if (resultInfo.audio_filesize_bytes) detailsHtml += `<p><i class="fas fa-database"></i> Size: ${(resultInfo.audio_filesize_bytes / (1024*1024)).toFixed(2)} MB</p>`;
        conversionDetailsDiv.innerHTML = detailsHtml || '<p>Conversion complete.</p>';
    }

    function resetUI() {
        console.log("Resetting UI to initial state.");
        stopPolling();
        currentTaskId = null;

        if (uploadSection) uploadSection.style.display = 'block';
        if (progressSection) progressSection.style.display = 'none';
        if (resultSection) resultSection.style.display = 'none';

        clearError();

        if (fileInput) fileInput.value = '';
        if (modelSelect && modelSelect.options.length > 0 && !modelSelect.options[0].disabled) {
             modelSelect.disabled = false;
         } else if (modelSelect) {
            modelSelect.disabled = true;
         }

        if (progressBar) {
            progressBar.style.width = '0%';
            progressBar.classList.remove('indeterminate', 'processing');
        }
        if (processingNote) processingNote.style.display = 'none';

        if (audioPlayer) {
            audioPlayer.pause();
            audioPlayer.removeAttribute('src');
        }
        if (downloadBtn) downloadBtn.removeAttribute('href');
        if (conversionDetailsDiv) conversionDetailsDiv.innerHTML = '';
    }

    function resetUIForProcessing(filename = 'your file') {
          console.log(`Resetting UI for processing: ${filename}`); 
          stopPolling(); 
          currentTaskId = null; 
          clearError(); 
   
          if (uploadSection) uploadSection.style.display = 'none';
          if (resultSection) resultSection.style.display = 'none';
          if (progressSection) progressSection.style.display = 'block'; 

          if(progressBar) {
             progressBar.style.width = '0%';
             progressBar.classList.remove('indeterminate', 'processing');
          }
          if(progressStatusText) progressStatusText.textContent = `Preparing "${escapeHTML(filename)}"...`;
          if(progressDetailsText) progressDetailsText.textContent = 'Submitting job...'; 
          if(processingNote) processingNote.style.display = 'none';           
          if(conversionDetailsDiv) conversionDetailsDiv.innerHTML = '';
     }

    function clearError() {
        if (errorMessageDiv) {
            errorMessageDiv.textContent = '';
            errorMessageDiv.style.display = 'none';
        }
     }

    function showError(message) {
        console.error("Displaying Error to User:", message); 
        if (!errorMessageDiv || !uploadSection) {
            console.error("Cannot show error, required UI elements missing.");
            alert("Error: " + message); 
            return;
        }
        errorMessageDiv.textContent = `Error: ${message}`;
        errorMessageDiv.style.display = 'block';
        
        if (progressSection) progressSection.style.display = 'none';
        if (resultSection) resultSection.style.display = 'none';
        if (uploadSection) uploadSection.style.display = 'block'; 

        stopPolling(); 
    }
 
    function escapeHTML(str) {
        if (!str) return '';
        return str.replace(/&/g, '&').replace(/</g, '<').replace(/>/g, '>').replace(/"/g, '"').replace(/'/g, '');
    }

    function secureFilenameForJS(filename) {
         
         if (!filename) return 'download';
        return filename.replace(/[^a-z0-9_\-\.]/gi, '_').replace(/_{2,}/g, '_');
    }

});