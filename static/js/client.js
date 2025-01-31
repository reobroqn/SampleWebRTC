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
        clearReconnectTimer();
        
        if (pc) {
            console.warn('Already connected, stopping previous connection...');
            await stop();
        }

        const videoSelect = document.getElementById('videoSelect');
        if (!videoSelect.value) {
            showError('Please select a video file first');
            return;
        }

        // Create peer connection
        const config = {
            sdpSemantics: 'unified-plan',
            iceServers: [{ urls: ['stun:stun.l.google.com:19302'] }]
        };

        pc = new RTCPeerConnection(config);
        console.log('Created RTCPeerConnection');

        // Handle incoming tracks
        pc.addEventListener('track', (evt) => {
            console.log('Received track:', evt.track.kind);
            if (evt.track.kind === 'video') {
                const videoElement = document.getElementById('video');
                videoElement.srcObject = evt.streams[0];
                videoStream = evt.streams[0];
                
                // Monitor track status
                evt.track.addEventListener('ended', () => {
                    console.log('Video track ended, attempting to reconnect...');
                    reconnect();
                });
            }
        });

        // Handle connection state changes
        pc.addEventListener('connectionstatechange', () => {
            console.log('Connection state:', pc.connectionState);
            if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
                console.error('Connection failed or disconnected');
                reconnect();
            }
        });

        try {
            console.log('Starting negotiation');
            
            // Create and set local description
            const offer = await pc.createOffer({
                offerToReceiveVideo: true,
            });
            await pc.setLocalDescription(offer);

            // Wait for ICE gathering to complete
            await new Promise((resolve) => {
                if (pc.iceGatheringState === 'complete') {
                    resolve();
                } else {
                    pc.addEventListener('icegatheringstatechange', () => {
                        if (pc.iceGatheringState === 'complete') {
                            resolve();
                        }
                    });
                }
            });

            // Send offer to server with selected video file
            const response = await fetch('/offer', {
                body: JSON.stringify({
                    sdp: pc.localDescription.sdp,
                    type: pc.localDescription.type,
                    video_file: videoSelect.value
                }),
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                method: 'POST'
            });

            const responseData = await response.json();
            if (!response.ok) {
                throw new Error(responseData.error || 'Server error: ' + response.status);
            }

            // Handle server response
            await pc.setRemoteDescription(responseData);
            connectionId = responseData.connection_id;
            console.log('Negotiation completed, connection ID:', connectionId);

            // Update UI
            document.getElementById('start').style.display = 'none';
            document.getElementById('stop').style.display = 'inline-block';

        } catch (e) {
            console.error('Negotiation failed:', e);
            await stop();
            showError('Failed to start streaming: ' + e.message);
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
