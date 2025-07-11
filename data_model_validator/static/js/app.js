document.addEventListener('DOMContentLoaded', function() {
    // Initialize processing flag
    window.isProcessing = false;
    
    initializeFileUpload();
    initializeDragAndDrop();
    initializeInteractiveElements();
});

function initializeFileUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const uploadBtn = document.getElementById('uploadBtn');

    if (uploadBtn) {
        uploadBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            if (!window.isProcessing) {
                fileInput.click();
            }
        });
    }

    if (uploadArea) {
        uploadArea.addEventListener('click', function(e) {
            // Don't handle clicks on the button or file input
            if (e.target === uploadBtn || e.target === fileInput || uploadBtn.contains(e.target)) {
                return;
            }
            
            if (!window.isProcessing) {
                fileInput.click();
            }
        });
    }

    if (fileInput) {
        fileInput.addEventListener('change', function(e) {
            if (window.isProcessing) {
                return;
            }
            
            const file = e.target.files[0];
            if (file) {
                window.isProcessing = true;
                handleFileSelection(file);
            }
        });
    }
}

function initializeDragAndDrop() {
    const uploadArea = document.getElementById('uploadArea');
    
    if (!uploadArea) return;

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        uploadArea.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, unhighlight, false);
    });

    function highlight(e) {
        uploadArea.classList.add('dragover');
    }

    function unhighlight(e) {
        uploadArea.classList.remove('dragover');
    }

    uploadArea.addEventListener('drop', handleDrop, false);

    function handleDrop(e) {
        if (window.isProcessing) return;
        
        const dt = e.dataTransfer;
        const files = dt.files;

        if (files.length > 0) {
            const file = files[0];
            // Set the file to the file input
            const fileInput = document.getElementById('fileInput');
            if (fileInput) {
                // Create a new FileList object
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(file);
                fileInput.files = dataTransfer.files;
            }
            window.isProcessing = true;
            handleFileSelection(file);
        }
    }
}

function handleFileSelection(file) {
    const uploadText = document.querySelector('.upload-text');
    const uploadSubtext = document.querySelector('.upload-subtext');
    
    if (file.type === 'text/plain' || file.name.endsWith('.txt')) {
        if (uploadText) {
            uploadText.textContent = `Selected: ${file.name}`;
            uploadText.style.color = 'var(--success-color)';
        }
        if (uploadSubtext) {
            uploadSubtext.textContent = `File size: ${formatFileSize(file.size)} | Ready to process`;
            uploadSubtext.style.color = 'var(--success-color)';
        }
        
        // Small delay to ensure file input is properly set, then submit
        setTimeout(() => {
            submitFileForm();
        }, 100);
    } else {
        showError('Please select a .txt file');
        resetUploadArea();
    }
}

function submitFileForm() {
    const form = document.querySelector('form');
    const fileInput = document.getElementById('fileInput');
    
    if (!form) {
        console.error('Form not found');
        return;
    }
    
    // Verify the file input has the file
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        console.error('File input not found or no file selected');
        showError('File input not found or no file selected');
        resetUploadArea();
        return;
    }
    
    const file = fileInput.files[0];
    console.log('Submitting file:', file.name, 'Size:', file.size);
    
    // Show loading UI
    showLoading();
    
    // Submit the form
    console.log('Submitting form...');
    form.submit();
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function resetUploadArea() {
    const uploadText = document.querySelector('.upload-text');
    const uploadSubtext = document.querySelector('.upload-subtext');
    const fileInput = document.getElementById('fileInput');
    
    if (uploadText) {
        uploadText.textContent = 'Drop your .txt file here or click to browse';
        uploadText.style.color = '';
    }
    if (uploadSubtext) {
        uploadSubtext.textContent = 'Supports .txt files containing device log data';
        uploadSubtext.style.color = '';
    }
    if (fileInput) {
        fileInput.value = '';
    }
    
    // Reset processing flag to allow new uploads
    window.isProcessing = false;
}

function showLoading() {
    const uploadSection = document.querySelector('.upload-section');
    if (uploadSection) {
        // Create loading overlay instead of replacing content
        const loadingOverlay = document.createElement('div');
        loadingOverlay.className = 'loading-overlay';
        loadingOverlay.innerHTML = `
            <div class="loading">
                <div class="loading-spinner"></div>
                <h3>Processing your file...</h3>
                <p>Parsing device data and running validation checks</p>
            </div>
        `;
        
        // Style the overlay
        loadingOverlay.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255, 255, 255, 0.95);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            border-radius: 12px;
        `;
        
        // Make upload section relative positioned
        uploadSection.style.position = 'relative';
        
        // Add overlay to upload section
        uploadSection.appendChild(loadingOverlay);
    }
}

function showError(message) {
    const uploadArea = document.getElementById('uploadArea');
    if (uploadArea) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.innerHTML = `
            <strong>Error:</strong> ${message}
        `;
        uploadArea.parentNode.insertBefore(errorDiv, uploadArea.nextSibling);
        
        // Remove error message after 5 seconds
        setTimeout(() => {
            if (errorDiv.parentNode) {
                errorDiv.parentNode.removeChild(errorDiv);
            }
        }, 5000);
    }
    
    // Reset processing flag on error
    window.isProcessing = false;
}

function initializeInteractiveElements() {
    // Add smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });

    // Add click handlers for expandable sections
    initializeExpandableSections();
    
    // Add copy functionality for IDs and codes
    initializeCopyButtons();
    
    // Add modal functionality
    initializeModal();
}

function initializeExpandableSections() {
    const deviceTypeCards = document.querySelectorAll('.device-type-card');
    
    deviceTypeCards.forEach(card => {
        const header = card.querySelector('.device-type-header');
        if (header) {
            header.style.cursor = 'pointer';
            header.addEventListener('click', function() {
                const content = card.querySelector('.clusters-grid');
                if (content) {
                    const isVisible = content.style.display !== 'none';
                    content.style.display = isVisible ? 'none' : 'grid';
                    
                    // Add expand/collapse icon
                    let icon = header.querySelector('.expand-icon');
                    if (!icon) {
                        icon = document.createElement('span');
                        icon.className = 'expand-icon';
                        header.appendChild(icon);
                    }
                    icon.textContent = isVisible ? '▶' : '▼';
                }
            });
        }
    });
}

function initializeModal() {
    // Close modal when pressing Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeClusterModal();
        }
    });
}

function openClusterModal(clusterId, endpointId) {
    // Find the cluster data from the script tag
    const clusterDataScript = document.querySelector(
        `.cluster-data[data-cluster-id="${clusterId}"][data-endpoint-id="${endpointId}"]`
    );
    
    if (!clusterDataScript) {
        console.error('Cluster data not found');
        return;
    }
    
    let clusterData;
    try {
        clusterData = JSON.parse(clusterDataScript.textContent);
    } catch (e) {
        console.error('Error parsing cluster data:', e);
        return;
    }
    
    // Update modal title
    const modalTitle = document.getElementById('modalTitle');
    modalTitle.innerHTML = `<i class="fas fa-network-wired"></i> Cluster ${clusterId} - Endpoint ${endpointId}`;
    
    // Build modal content
    const modalBody = document.getElementById('modalBody');
    modalBody.innerHTML = buildClusterContent(clusterData, clusterId);
    
    // Show modal
    document.getElementById('clusterModal').style.display = 'flex';
    document.getElementById('modalOverlay').style.display = 'block';
    document.body.style.overflow = 'hidden'; // Prevent background scrolling
}

function closeClusterModal() {
    document.getElementById('clusterModal').style.display = 'none';
    document.getElementById('modalOverlay').style.display = 'none';
    document.body.style.overflow = 'auto'; // Restore scrolling
}

function buildClusterContent(clusterData, clusterId) {
    let html = '';
    
    // Attributes Section
    if (clusterData.attributes && Object.keys(clusterData.attributes).length > 0) {
        html += buildAttributesSection(clusterData.attributes);
    }
    
    // Commands Section
    if (clusterData.commands) {
        html += buildCommandsSection(clusterData.commands);
    }
    
    // Events Section
    if (clusterData.events && clusterData.events.EventList && clusterData.events.EventList.EventList) {
        html += buildEventsSection(clusterData.events.EventList.EventList);
    }
    
    // Features Section
    if (clusterData.features && Object.keys(clusterData.features).length > 0) {
        html += buildFeaturesSection(clusterData.features);
    }
    
    return html || '<p style="text-align: center; color: #666; padding: 20px;">No detailed information available for this cluster.</p>';
}

function buildAttributesSection(attributes) {
    let html = `
        <div class="modal-section">
            <h3><i class="fas fa-list"></i> Attributes</h3>
            <div class="modal-items">
    `;
    
    // Create name mapping from AttributeList
    const nameMap = {};
    if (attributes.AttributeList && attributes.AttributeList.AttributeList) {
        attributes.AttributeList.AttributeList.forEach(attr => {
            nameMap[attr.id] = attr.name;
        });
    }
    
    // Display all attributes except AttributeList
    Object.entries(attributes).forEach(([attrId, attrData]) => {
        if (attrId !== 'AttributeList') {
            const attrName = nameMap[attrId] || attrId.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            
            html += `
                <div class="modal-item">
                    <div class="modal-item-header">
                        <span class="modal-id-badge">${attrId}</span>
                        <span class="modal-name">${attrName}</span>
                    </div>
                    <div class="modal-values">
            `;
            
            if (typeof attrData === 'object' && attrData !== null) {
                Object.entries(attrData).forEach(([key, value]) => {
                    const displayValue = typeof value === 'object' ? JSON.stringify(value, null, 2) : value;
                    html += `
                        <div class="modal-value">
                            <span class="modal-value-label">${key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}:</span>
                            <span class="modal-value-data">${displayValue}</span>
                        </div>
                    `;
                });
            } else {
                html += `
                    <div class="modal-value">
                        <span class="modal-value-label">Value:</span>
                        <span class="modal-value-data">${attrData}</span>
                    </div>
                `;
            }
            
            html += `
                    </div>
                </div>
            `;
        }
    });
    
    html += '</div></div>';
    return html;
}

function buildCommandsSection(commands) {
    let html = `
        <div class="modal-section">
            <h3><i class="fas fa-terminal"></i> Commands</h3>
            <div class="modal-items">
    `;
    
    // Generated Commands
    if (commands.GeneratedCommandList && commands.GeneratedCommandList.GeneratedCommandList) {
        commands.GeneratedCommandList.GeneratedCommandList.forEach(cmd => {
            html += `
                <div class="modal-item">
                    <div class="modal-item-header">
                        <span class="modal-id-badge">${cmd.id}</span>
                        <span class="modal-name">${cmd.name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</span>
                        <span class="modal-type-badge generated">Generated</span>
                    </div>
                </div>
            `;
        });
    }
    
    // Accepted Commands
    if (commands.AcceptedCommandList && commands.AcceptedCommandList.AcceptedCommandList) {
        commands.AcceptedCommandList.AcceptedCommandList.forEach(cmd => {
            html += `
                <div class="modal-item">
                    <div class="modal-item-header">
                        <span class="modal-id-badge">${cmd.id}</span>
                        <span class="modal-name">${cmd.name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</span>
                        <span class="modal-type-badge accepted">Accepted</span>
                    </div>
                </div>
            `;
        });
    }
    
    html += '</div></div>';
    return html;
}

function buildEventsSection(events) {
    let html = `
        <div class="modal-section">
            <h3><i class="fas fa-bolt"></i> Events</h3>
            <div class="modal-items">
    `;
    
    events.forEach(event => {
        html += `
            <div class="modal-item">
                <div class="modal-item-header">
                    <span class="modal-id-badge">${event.id}</span>
                    <span class="modal-name">${event.name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</span>
                    <span class="modal-type-badge event">Event</span>
                </div>
            </div>
        `;
    });
    
    html += '</div></div>';
    return html;
}

function buildFeaturesSection(features) {
    let html = `
        <div class="modal-section">
            <h3><i class="fas fa-cog"></i> Features</h3>
            <div class="modal-items">
    `;
    
    Object.entries(features).forEach(([featureId, featureData]) => {
        html += `
            <div class="modal-item">
                <div class="modal-item-header">
                    <span class="modal-id-badge">${featureId}</span>
                    <span class="modal-name">${featureId.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</span>
                </div>
        `;
        
        if (typeof featureData === 'object' && featureData !== null) {
            html += '<div class="modal-values">';
            Object.entries(featureData).forEach(([key, value]) => {
                html += `
                    <div class="modal-value">
                        <span class="modal-value-label">${key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}:</span>
                        <span class="modal-value-data">${value}</span>
                    </div>
                `;
            });
            html += '</div>';
        }
        
        html += '</div>';
    });
    
    html += '</div></div>';
    return html;
}

function initializeCopyButtons() {
    // Add copy buttons to device type IDs and cluster IDs
    const deviceTypeIds = document.querySelectorAll('.device-type-id');
    const clusterIds = document.querySelectorAll('.cluster-id');
    
    [...deviceTypeIds, ...clusterIds].forEach(element => {
        element.style.cursor = 'pointer';
        element.title = 'Click to copy';
        element.addEventListener('click', function() {
            copyToClipboard(this.textContent);
            showCopySuccess(this);
        });
    });
}

function copyToClipboard(text) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            console.log('Copied to clipboard:', text);
        });
    } else {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = text;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
    }
}

function showCopySuccess(element) {
    const originalBg = element.style.backgroundColor;
    element.style.backgroundColor = 'var(--success-color)';
    element.style.color = 'white';
    
    setTimeout(() => {
        element.style.backgroundColor = originalBg;
        element.style.color = '';
    }, 1000);
}

// Download functionality
function downloadValidationReport() {
    const validationData = getValidationData();
    if (validationData) {
        downloadJSON(validationData, 'validation_report.json');
    }
}

function downloadParsedData() {
    const parsedData = getParsedData();
    if (parsedData) {
        downloadJSON(parsedData, 'parsed_data.json');
    }
}

function downloadJSON(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
}

function getValidationData() {
    // This would be populated by the server-side template
    return window.validationData || null;
}

function getParsedData() {
    // This would be populated by the server-side template
    return window.parsedData || null;
}

// Add keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + U to trigger file upload
    if ((e.ctrlKey || e.metaKey) && e.key === 'u') {
        e.preventDefault();
        const fileInput = document.getElementById('fileInput');
        if (fileInput) {
            fileInput.click();
        }
    }
    
    // Escape to close any open modals or reset upload area
    if (e.key === 'Escape') {
        resetUploadArea();
    }
}); 