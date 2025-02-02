// Create a namespace for our application
const app = (function() {
    console.log('Client.js loaded at:', new Date().toISOString());

    let pc = null;
    let videoStream = null;
    let reconnectTimer = null;
    let connectionId = null;
    const RECONNECT_DELAY = 1000; // 1 second delay before reconnecting

    // Initialize the application
    function init() {
        console.log('Initializing application...');
        
        // Enable start button only when a video is selected
        document.getElementById('videoSelect').addEventListener('change', function() {
            document.getElementById('start').disabled = !this.value;
        });

        // Add click handlers for start/stop buttons
        document.getElementById('start').addEventListener('click', app.start);
        document.getElementById('stop').addEventListener('click', app.stop);

        // Handle video file upload
        const uploadForm = document.getElementById('uploadForm');
        if (!uploadForm) {
            console.error('Upload form not found!');
            return;
        }

        uploadForm.addEventListener('submit', handleUpload);

        // Handle TTS form submission
        const ttsForm = document.getElementById('tts-form');
        if (ttsForm) {
            const ttsSubmit = document.getElementById('tts-submit');
            if (ttsSubmit) {
                ttsSubmit.addEventListener('click', handleTTS);
            }
        }

        // Handle video ended event
        const videoElement = document.getElementById('video');
        videoElement.addEventListener('ended', () => {
            console.log('Video stream ended, attempting to reconnect...');
            reconnect();
        });
    }

    // Handle file upload
    async function handleUpload(e) {
        e.preventDefault();  // Prevent form from submitting normally
        console.log('Upload form submitted');
        
        const submitButton = this.querySelector('button[type="submit"]');
        const fileInput = document.getElementById('videoFile');
        const file = fileInput.files[0];
        
        if (!file) {
            showError('Please select a file to upload');
            return;
        }
        
        console.log('Selected file:', file.name, 'Size:', file.size, 'Type:', file.type);

        // Disable submit button during upload
        submitButton.disabled = true;
        submitButton.textContent = 'Uploading...';

        try {
            console.log('Preparing upload request...');
            const formData = new FormData();
            formData.append('file', file);

            console.log('Sending upload request...');
            const response = await fetch('/upload', {
                method: 'POST',
                body: formData,
                // Don't set Content-Type header, let the browser set it with the boundary
                headers: {
                    'Accept': 'application/json'
                }
            });

            console.log('Upload response status:', response.status);
            const contentType = response.headers.get('content-type');
            let result;
            
            if (contentType && contentType.includes('application/json')) {
                result = await response.json();
                console.log('Upload response:', result);
            } else {
                const text = await response.text();
                console.log('Upload response text:', text);
                throw new Error('Expected JSON response from server');
            }

            if (!response.ok) {
                throw new Error(result.detail || 'Upload failed');
            }

            // Refresh the video select dropdown
            const videoSelect = document.getElementById('videoSelect');
            const option = document.createElement('option');
            option.value = result.filename;
            option.textContent = result.filename;
            videoSelect.appendChild(option);
            videoSelect.value = result.filename;
            
            // Enable start button
            document.getElementById('start').disabled = false;
            
            // Reset form
            fileInput.value = '';
            showError('Upload successful!', 'success');
        } catch (error) {
            console.error('Upload error:', error);
            showError('Failed to upload video: ' + error.message);
        } finally {
            // Re-enable submit button
            submitButton.disabled = false;
            submitButton.textContent = 'Upload';
        }
    }

    // Handle TTS form submission
    async function handleTTS(e) {
        e.preventDefault();
        console.log('TTS form submitted');

        const text = document.getElementById('tts-input').value.trim();
        if (!text) {
            showError('Please enter text to convert to speech');
            return;
        }

        try {
            console.log('Sending TTS request:', text);
            const response = await fetch('/tts', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    text: text
                })
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            const result = await response.json();
            console.log('TTS response:', result);
            document.getElementById('tts-input').value = '';

        } catch (e) {
            console.error('TTS error:', e);
            showError(e.toString());
        }
    }

    function showError(message, type = 'error') {
        console.log('Showing message:', message, 'Type:', type);
        const errorDiv = document.getElementById('errorMessage');
        if (!errorDiv) {
            console.error('Error message div not found!');
            return;
        }
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
        errorDiv.style.color = type === 'error' ? '#f44336' : '#4CAF50';
        setTimeout(() => {
            errorDiv.style.display = 'none';
        }, 5000);
    }

    function clearReconnectTimer() {
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
    }

    async function reconnect() {
        clearReconnectTimer();
        
        // Only reconnect if we're still supposed to be playing
        if (document.getElementById('stop').style.display === 'inline-block') {
            console.log('Reconnecting stream...');
            await stop(false); // Stop without updating UI
            reconnectTimer = setTimeout(() => start(), RECONNECT_DELAY);
        }
    }

    async function start() {
        console.log('Starting WebRTC connection...');
        
        if (pc) {
            console.warn('WebRTC connection already exists');
            return;
        }

        try {
            const videoSelect = document.getElementById('videoSelect');
            const selectedVideo = videoSelect.value;
            
            if (!selectedVideo) {
                showError('Please select a video file first');
                return;
            }

            console.log('Selected video:', selectedVideo);

            // Create peer connection
            const config = {
                sdpSemantics: 'unified-plan',
                iceServers: [{urls: ['stun:stun.l.google.com:19302']}]
            };

            console.log('Creating RTCPeerConnection with config:', config);
            pc = new RTCPeerConnection(config);

            // Handle tracks
            pc.addEventListener('track', (evt) => {
                console.log('Received track:', evt.track.kind);
                if (evt.track.kind === 'video') {
                    const videoElement = document.getElementById('video');
                    videoElement.srcObject = evt.streams[0];
                    videoStream = evt.streams[0];
                } else if (evt.track.kind === 'audio') {
                    const audioElement = document.getElementById('audio');
                    audioElement.srcObject = evt.streams[0];
                }
            });

            // Add transceivers before creating offer
            console.log('Adding transceivers...');
            pc.addTransceiver('video', { direction: 'recvonly' });
            pc.addTransceiver('audio', { direction: 'recvonly' });

            // Create and set local description
            console.log('Creating offer...');
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);

            // Wait for ICE gathering to complete
            await new Promise((resolve) => {
                if (pc.iceGatheringState === 'complete') {
                    resolve();
                } else {
                    const checkState = () => {
                        if (pc.iceGatheringState === 'complete') {
                            pc.removeEventListener('icegatheringstatechange', checkState);
                            resolve();
                        }
                    };
                    pc.addEventListener('icegatheringstatechange', checkState);
                }
            });

            // Send offer to server
            console.log('Sending offer to server...');
            const response = await fetch('/offer', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    sdp: pc.localDescription.sdp,
                    type: pc.localDescription.type,
                    video_file: selectedVideo
                })
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            const answer = await response.json();
            console.log('Received answer from server');

            // Set remote description
            await pc.setRemoteDescription(answer);
            console.log('Set remote description, connection established');

            // Update UI
            document.getElementById('start').style.display = 'none';
            document.getElementById('stop').style.display = 'inline-block';
            document.getElementById('videoSelect').disabled = true;
            document.getElementById('uploadForm').style.display = 'none';

            // Setup connection state change handler
            pc.addEventListener('connectionstatechange', () => {
                console.log('Connection state:', pc.connectionState);
                if (pc.connectionState === 'failed') {
                    console.log('Connection failed, attempting to reconnect...');
                    stop(false);
                    reconnect();
                }
            });

        } catch (e) {
            console.error('Error during connection setup:', e);
            showError(e.toString());
            if (pc) {
                pc.close();
                pc = null;
            }
        }
    }

    async function stop(updateUI = true) {
        console.log('Stopping connection');
        clearReconnectTimer();
        
        // Reset connection ID
        connectionId = null;
        
        // Stop video
        if (videoStream) {
            videoStream.getTracks().forEach(track => track.stop());
            videoStream = null;
        }
        
        // Close peer connection
        if (pc) {
            pc.close();
            pc = null;
        }
        
        // Update UI
        document.getElementById('video').srcObject = null;
        if (updateUI) {
            document.getElementById('stop').style.display = 'none';
            document.getElementById('start').style.display = 'inline-block';
        }
    }

    // Initialize when DOM is loaded
    document.addEventListener('DOMContentLoaded', init);

    // Return public methods
    return {
        start,
        stop
    };
})();

// Handle page unload
window.onbeforeunload = function() {
    if (app.pc) {
        app.stop();
    }
};
