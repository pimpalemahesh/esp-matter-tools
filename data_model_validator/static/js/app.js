document.addEventListener("DOMContentLoaded", function () {
  // Initialize processing flags
  window.isProcessing = false;
  window.isValidationInProgress = false;
  window.isIntentionalNavigation = false;

  initializeFileUpload();
  initializeDragAndDrop();
  initializeInteractiveElements();
  initializeValidationFunctionality();
  initializeDataHandling();
  initializePageProtection();
});

// ============= FILE UPLOAD FUNCTIONALITY =============
function initializeFileUpload() {
  const uploadArea = document.getElementById("uploadArea");
  const fileInput = document.getElementById("fileInput");
  const uploadBtn = document.getElementById("uploadBtn");

  if (uploadBtn) {
    uploadBtn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (!window.isProcessing) {
        fileInput.click();
      }
    });
  }

  if (uploadArea) {
    uploadArea.addEventListener("click", function (e) {
      // Don't handle clicks on the button or file input
      if (
        e.target === uploadBtn ||
        e.target === fileInput ||
        uploadBtn.contains(e.target)
      ) {
        return;
      }

      if (!window.isProcessing) {
        fileInput.click();
      }
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", function (e) {
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
  const uploadArea = document.getElementById("uploadArea");

  if (!uploadArea) return;

  ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
    uploadArea.addEventListener(eventName, preventDefaults, false);
  });

  function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  ["dragenter", "dragover"].forEach((eventName) => {
    uploadArea.addEventListener(eventName, highlight, false);
  });

  ["dragleave", "drop"].forEach((eventName) => {
    uploadArea.addEventListener(eventName, unhighlight, false);
  });

  function highlight(e) {
    uploadArea.classList.add("dragover");
  }

  function unhighlight(e) {
    uploadArea.classList.remove("dragover");
  }

  uploadArea.addEventListener("drop", handleDrop, false);

  function handleDrop(e) {
    if (window.isProcessing) return;

    const dt = e.dataTransfer;
    const files = dt.files;

    if (files.length > 0) {
      const file = files[0];
      // Set the file to the file input
      const fileInput = document.getElementById("fileInput");
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
  const uploadText = document.querySelector(".upload-text");
  const uploadSubtext = document.querySelector(".upload-subtext");

  if (file.type === "text/plain" || file.name.endsWith(".txt") || file.name.endsWith(".zap") || file.type === "application/json") {
    if (uploadText) {
      uploadText.textContent = `Selected: ${file.name}`;
      uploadText.style.color = "var(--success-color)";
    }
    if (uploadSubtext) {
      uploadSubtext.textContent = `File size: ${formatFileSize(file.size)} | Ready to process`;
      uploadSubtext.style.color = "var(--success-color)";
    }

    // Small delay to ensure file input is properly set, then submit
    setTimeout(() => {
      submitFileForm();
    }, 100);
  } else {
    showError("Please select a .txt or .zap file");
    resetUploadArea();
  }
}

function submitFileForm() {
  const form = document.querySelector("form");
  const fileInput = document.getElementById("fileInput");

  if (!form) {
    console.error("Form not found");
    return;
  }

  // Verify the file input has the file
  if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
    console.error("File input not found or no file selected");
    showError("File input not found or no file selected");
    resetUploadArea();
    return;
  }

  const file = fileInput.files[0];
  console.log("Submitting file:", file.name, "Size:", file.size);

  // Show loading UI
  showLoading();

  // Submit the form
  console.log("Submitting form...");
  form.submit();
}

function formatFileSize(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

function resetUploadArea() {
  const uploadText = document.querySelector(".upload-text");
  const uploadSubtext = document.querySelector(".upload-subtext");
  const fileInput = document.getElementById("fileInput");

  if (uploadText) {
    uploadText.textContent = "Drop your .txt or .zap file here or click to browse";
    uploadText.style.color = "";
  }
  if (uploadSubtext) {
    uploadSubtext.textContent =
      "Supports .txt wildcard logs and .zap configuration files";
    uploadSubtext.style.color = "";
  }
  if (fileInput) {
    fileInput.value = "";
  }

  // Reset processing flag to allow new uploads
  window.isProcessing = false;
}

function showLoading() {
  const uploadSection = document.querySelector(".upload-section");
  if (uploadSection) {
    // Create loading overlay instead of replacing content
    const loadingOverlay = document.createElement("div");
    loadingOverlay.className = "loading-overlay";
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
    uploadSection.style.position = "relative";

    // Add overlay to upload section
    uploadSection.appendChild(loadingOverlay);
  }
}

function showError(message) {
  const uploadArea = document.getElementById("uploadArea");
  if (uploadArea) {
    const errorDiv = document.createElement("div");
    errorDiv.className = "error-message";
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

// ============= VALIDATION FUNCTIONALITY =============
function initializeValidationFunctionality() {
  initializeUploadNewButton();
  initializeValidateButton();
  restoreSelectedVersion();
  cleanUpURLParameter();
}

function initializeUploadNewButton() {
  const uploadNewBtn = document.getElementById("uploadNewBtn");
  if (uploadNewBtn) {
    uploadNewBtn.addEventListener("click", function () {
      if (
        confirm("This will clear all current data and start over. Continue?")
      ) {
        // Set intentional navigation flag to prevent second popup
        window.isIntentionalNavigation = true;
        window.isValidationInProgress = false;

        // Show loading state
        const originalText = uploadNewBtn.innerHTML;
        uploadNewBtn.innerHTML =
          '<i class="fas fa-spinner fa-spin"></i> Clearing data...';
        uploadNewBtn.disabled = true;

        fetch("/api/clear-data", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
        })
          .then((response) => response.json())
          .then((data) => {
            if (data.success) {
              uploadNewBtn.innerHTML =
                '<i class="fas fa-check"></i> Redirecting...';
              setTimeout(() => {
                window.location.href = "/";
              }, 500);
            } else {
              uploadNewBtn.innerHTML = originalText;
              uploadNewBtn.disabled = false;
              alert("Error clearing data: " + data.error);
            }
          })
          .catch((error) => {
            console.error("Error:", error);
            uploadNewBtn.innerHTML = originalText;
            uploadNewBtn.disabled = false;
            setTimeout(() => {
              window.location.href = "/";
            }, 500);
          });
      }
    });
  }
}

function initializeValidateButton() {
  const validateBtn = document.getElementById("validateBtn");
  if (validateBtn) {
    validateBtn.addEventListener("click", function () {
      const selectedVersion =
        document.getElementById("complianceVersion").value;

      // Validate version selection
      if (!selectedVersion) {
        showMessage(
          "validateMessage",
          "Please select a data model version to validate against",
          "error",
        );
        return;
      }

      // Store the selected version to retain it after validation
      sessionStorage.setItem("selectedVersion", selectedVersion);

      // Set flags to prevent refresh warning during validation
      window.isValidationInProgress = true;
      window.isIntentionalNavigation = true;

      // Show validation loader
      showValidationLoader();
      hideMessage("validateMessage");

      // Simulate progress updates
      simulateProgress();

      // Make API call
      fetch("/api/validate-compliance", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ chip_version: selectedVersion }),
      })
        .then((response) => response.json())
        .then((data) => {
          if (data.success) {
            updateProgress(100, "Validation complete!");
            setTimeout(() => {
              hideValidationLoader();
              // Redirect with a parameter to preserve session data
              window.location.href = "/?validation_complete=1";
            }, 1000);
          } else {
            // Reset flags on error
            window.isValidationInProgress = false;
            window.isIntentionalNavigation = false;
            hideValidationLoader();
            showMessage("validateMessage", data.error, "error");
          }
        })
        .catch((error) => {
          // Reset flags on error
          window.isValidationInProgress = false;
          window.isIntentionalNavigation = false;
          hideValidationLoader();
          showMessage("validateMessage", "Error: " + error.message, "error");
        });
    });
  }
}

function restoreSelectedVersion() {
  const versionSelect = document.getElementById("complianceVersion");
  const storedVersion = sessionStorage.getItem("selectedVersion");

  if (versionSelect && storedVersion) {
    versionSelect.value = storedVersion;
    // Update the display text as well
    const selectedOption = versionSelect.querySelector(
      `option[value="${storedVersion}"]`,
    );
    if (selectedOption) {
      versionSelect.selectedIndex = Array.from(versionSelect.options).indexOf(
        selectedOption,
      );
    }
  }
}

function cleanUpURLParameter() {
  // Clean up URL parameter after validation completion
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get("validation_complete")) {
    // Reset all flags since validation is now complete
    window.isValidationInProgress = false;
    window.isIntentionalNavigation = false;

    // Remove the parameter from URL without triggering a page reload
    const newUrl = window.location.pathname;
    window.history.replaceState({}, document.title, newUrl);
  }
}

// Validation Loader Functions
function showValidationLoader() {
  document.getElementById("validationLoader").style.display = "flex";
  document.body.style.overflow = "hidden";
}

function hideValidationLoader() {
  document.getElementById("validationLoader").style.display = "none";
  document.body.style.overflow = "auto";
}

function updateProgress(percentage, message) {
  document.getElementById("progressFill").style.width = percentage + "%";
  document.getElementById("progressText").textContent = message;
}

function simulateProgress() {
  const steps = [
    { progress: 10, message: "Loading requirements...", delay: 200 },
    { progress: 25, message: "Parsing device data...", delay: 500 },
    { progress: 40, message: "Validating clusters...", delay: 800 },
    { progress: 60, message: "Checking attributes...", delay: 1200 },
    { progress: 80, message: "Verifying commands...", delay: 1500 },
    { progress: 95, message: "Finalizing results...", delay: 1800 },
  ];

  steps.forEach((step) => {
    setTimeout(() => {
      updateProgress(step.progress, step.message);
    }, step.delay);
  });
}

// ============= DATA HANDLING =============
function initializeDataHandling() {
  // Initialize data availability for other functions
  initializeGlobalDataAccess();
}

function initializeGlobalDataAccess() {
  // These will be set by the template when data is available
  window.validationData = window.validationData || null;
  window.parsedData = window.parsedData || null;
}

// ============= PAGE PROTECTION =============
function initializePageProtection() {
  // Add warning for page refresh when data is present
  window.addEventListener("beforeunload", function (event) {
    // Don't show warning if validation is in progress or user intentionally
    // navigating
    if (window.isValidationInProgress || window.isIntentionalNavigation) {
      return;
    }

    // Check if there's parsed data or validation data present
    const hasParsedData = window.parsedData !== null;
    const hasValidationData = window.validationData !== null;

    if (hasParsedData || hasValidationData) {
      // Show confirmation dialog
      const message =
        "All data will be erased if you refresh the page. Are you sure you want to continue?";
      event.preventDefault();
      event.returnValue = message; // For older browsers
      return message;
    }
  });
}

// ============= UTILITY FUNCTIONS =============
function showMessage(elementId, message, type) {
  const messageEl = document.getElementById(elementId);
  messageEl.style.display = "block";
  messageEl.className =
    "message-container " +
    (type === "error" ? "error-message" : "success-message");
  messageEl.innerHTML =
    '<i class="fas fa-' +
    (type === "error" ? "exclamation-triangle" : "check-circle") +
    '"></i> ' +
    message;
}

function hideMessage(elementId) {
  document.getElementById(elementId).style.display = "none";
}

// Function to toggle detailed results visibility
window.toggleDetailedResults = function () {
  const detailedResults = document.getElementById("detailedResults");
  const toggleIcon = document.querySelector(".toggle-icon");

  if (detailedResults.style.display === "none") {
    detailedResults.style.display = "grid";
    toggleIcon.innerHTML =
      '<i class="fas fa-chevron-up"></i> Click to collapse';
  } else {
    detailedResults.style.display = "none";
    toggleIcon.innerHTML =
      '<i class="fas fa-chevron-down"></i> Click to expand';
  }
};

// ============= COPY FUNCTIONALITY =============
window.copyCommand = function () {
  const command =
    "./chip-tool any read-by-id 0xFFFFFFFF 0xFFFFFFFF 1 0xFFFF > wildcard_logs.txt";

  if (navigator.clipboard) {
    navigator.clipboard
      .writeText(command)
      .then(() => {
        showCopyFeedback();
      })
      .catch(() => {
        fallbackCopyTextToClipboard(command);
      });
  } else {
    fallbackCopyTextToClipboard(command);
  }
};

function fallbackCopyTextToClipboard(text) {
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.top = "0";
  textArea.style.left = "0";
  textArea.style.position = "fixed";

  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  try {
    const successful = document.execCommand("copy");
    if (successful) {
      showCopyFeedback();
    }
  } catch (err) {
    console.error("Fallback: Oops, unable to copy", err);
  }

  document.body.removeChild(textArea);
}

function showCopyFeedback() {
  const copyBtn = document.querySelector(".copy-btn");
  const originalHTML = copyBtn.innerHTML;

  copyBtn.innerHTML = '<i class="fas fa-check"></i>';
  copyBtn.style.background = "var(--success-color)";

  setTimeout(() => {
    copyBtn.innerHTML = originalHTML;
    copyBtn.style.background = "var(--accent-color)";
  }, 2000);
}

// ============= INTERACTIVE ELEMENTS =============
function initializeInteractiveElements() {
  // Add smooth scrolling for anchor links
  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener("click", function (e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute("href"));
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
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
  const deviceTypeCards = document.querySelectorAll(".device-type-card");

  deviceTypeCards.forEach((card) => {
    const header = card.querySelector(".device-type-header");
    if (header) {
      header.style.cursor = "pointer";
      header.addEventListener("click", function () {
        const content = card.querySelector(".clusters-grid");
        if (content) {
          const isVisible = content.style.display !== "none";
          content.style.display = isVisible ? "none" : "grid";

          // Add expand/collapse icon
          let icon = header.querySelector(".expand-icon");
          if (!icon) {
            icon = document.createElement("span");
            icon.className = "expand-icon";
            header.appendChild(icon);
          }
          icon.textContent = isVisible ? "▶" : "▼";
        }
      });
    }
  });
}

function initializeModal() {
  // Close modal when pressing Escape key
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      closeClusterModal();
    }
  });
}

function openClusterModal(clusterId, endpointId) {
  // Find the cluster data from the script tag
  const clusterDataScript = document.querySelector(
    `.cluster-data[data-cluster-id="${clusterId}"][data-endpoint-id="${
      endpointId
    }"]`,
  );

  if (!clusterDataScript) {
    console.error("Cluster data not found");
    return;
  }

  let clusterData;
  try {
    clusterData = JSON.parse(clusterDataScript.textContent);
  } catch (e) {
    console.error("Error parsing cluster data:", e);
    return;
  }

  // Find validation data from embedded script tag
  const validationDataScript = document.querySelector(
    `.validation-data[data-cluster-id="${clusterId}"][data-endpoint-id="${
      endpointId
    }"]`,
  );

  let validationData = null;
  if (validationDataScript) {
    try {
      validationData = JSON.parse(validationDataScript.textContent);
    } catch (e) {
      console.error("Error parsing validation data:", e);
    }
  }

  // Update modal title
  const modalTitle = document.getElementById("modalTitle");
  modalTitle.innerHTML = `<i class="fas fa-network-wired"></i> Cluster ${
    clusterId
  } - Endpoint ${endpointId}`;

  // Build modal content
  const modalBody = document.getElementById("modalBody");
  modalBody.innerHTML = buildClusterContent(
    clusterData,
    clusterId,
    validationData,
  );

  // Show modal
  document.getElementById("clusterModal").style.display = "flex";
  document.getElementById("modalOverlay").style.display = "block";
  document.body.style.overflow = "hidden"; // Prevent background scrolling
}

function closeClusterModal() {
  document.getElementById("clusterModal").style.display = "none";
  document.getElementById("modalOverlay").style.display = "none";
  document.body.style.overflow = "auto"; // Restore scrolling
}

function buildClusterContent(clusterData, clusterId, validationData) {
  let html = "";

  // Missing Elements Section (if validation data is available)
  if (
    validationData &&
    validationData.missing_elements &&
    validationData.missing_elements.length > 0
  ) {
    html += buildMissingElementsSection(validationData.missing_elements);
  }

  // Revision Issues Section (cluster-specific)
  if (
    validationData &&
    validationData.revision_issues &&
    validationData.revision_issues.length > 0
  ) {
    html += buildRevisionIssuesSection(validationData.revision_issues);
  }

  // Event Information Section
  if (
    validationData &&
    validationData.event_warnings &&
    validationData.event_warnings.length > 0
  ) {
    html += buildEventInformationSection(validationData.event_warnings);
  }

  // Attributes Section
  if (
    clusterData.attributes &&
    Object.keys(clusterData.attributes).length > 0
  ) {
    html += buildAttributesSection(clusterData.attributes, validationData);
  }

  // Commands Section
  if (clusterData.commands) {
    html += buildCommandsSection(clusterData.commands, validationData);
  }

  // Only show if there's content
  return (
    html ||
    '<p style="text-align: center; color: #666; padding: 20px;">No detailed information available for this cluster.</p>'
  );
}

function buildMissingElementsSection(missingElements) {
  let html = `
        <div class="modal-section">
            <h3 style="color: var(--error-color);"><i class="fas fa-exclamation-triangle"></i> Missing Elements</h3>
            <div class="modal-items">
    `;

  // Group missing elements by type
  const groupedElements = {
    attribute: [],
    command: [],
    feature: [],
    cluster: [],
    feature_attribute: [],
    feature_command: [],
    feature_event: [],
  };

  missingElements.forEach((element) => {
    const type = element.type || "unknown";
    if (groupedElements[type]) {
      groupedElements[type].push(element);
    }
  });

  // Display each type of missing element
  Object.entries(groupedElements).forEach(([type, elements]) => {
    if (elements.length > 0) {
      let typeDisplayName = type;
      let iconClass = "network-wired";

      switch (type) {
        case "attribute":
          typeDisplayName = "Attributes";
          iconClass = "list";
          break;
        case "command":
          typeDisplayName = "Commands";
          iconClass = "terminal";
          break;
        case "feature":
          typeDisplayName = "Features";
          iconClass = "cog";
          break;
        case "cluster":
          typeDisplayName = "Clusters";
          iconClass = "network-wired";
          break;
        case "feature_attribute":
          typeDisplayName = "Feature-Specific Attributes";
          iconClass = "list-alt";
          break;
        case "feature_command":
          typeDisplayName = "Feature-Specific Commands";
          iconClass = "code";
          break;
        case "feature_event":
          typeDisplayName = "Feature-Specific Events";
          iconClass = "bell";
          break;
      }

      html += `
                <div class="missing-type-section">
                    <h4 style="color: var(--error-color); margin: 15px 0 10px 0;">
                        <i class="fas fa-${iconClass}"></i>
                        ${typeDisplayName} (${elements.length})
                    </h4>
            `;

      elements.forEach((element) => {
        // Special handling for feature-specific elements
        if (type.startsWith("feature_")) {
          html += `
                        <div class="modal-item missing-element">
                            <div class="modal-item-header">
                                <span class="modal-id-badge error">${
                                  element.id || "Unknown ID"
                                }</span>
                                <span class="modal-name error">${
                                  element.name || "Unknown Name"
                                }</span>
                            </div>
                            <div class="feature-context" style="margin-top: 5px; font-size: 0.9em; color: var(--text-secondary); background: var(--background-secondary); padding: 5px 8px; border-radius: 4px;">
                                <i class="fas fa-cog"></i> Required by feature: <strong>${
                                  element.feature_name || "Unknown Feature"
                                }</strong> (${
                                  element.feature_id || "Unknown ID"
                                })
                            </div>
                        </div>
                    `;
        } else {
          html += `
                        <div class="modal-item missing-element">
                            <div class="modal-item-header">
                                <span class="modal-id-badge error">${
                                  element.id || "Unknown ID"
                                }</span>
                                <span class="modal-name error">${
                                  element.name || "Unknown Name"
                                }</span>
                            </div>
                        </div>
                    `;
        }
      });

      html += "</div>";
    }
  });

  html += "</div></div>";
  return html;
}

function buildRevisionIssuesSection(revisionIssues) {
  let html = `
        <div class="modal-section">
            <h3 style="color: var(--error-color);"><i class="fas fa-exclamation-circle"></i> Revision Issues</h3>
            <div class="modal-items">
    `;

  revisionIssues.forEach((issue) => {
    html += `
            <div class="modal-item revision-issue">
                <div class="modal-item-header">
                    <span class="modal-id-badge error">${
                      issue.item_id || "N/A"
                    }</span>
                    <span class="modal-name error">${
                      issue.item_name || "Unknown Item"
                    }</span>
                </div>
                <div class="modal-values">
                    <div class="modal-value">
                        <span class="modal-value-label">Issue:</span>
                        <span class="modal-value-data">${issue.message}</span>
                    </div>
                    <div class="modal-value">
                        <span class="modal-value-label">Actual Revision:</span>
                        <span class="modal-value-data">${
                          issue.actual_revision || "Unknown"
                        }</span>
                    </div>
                    <div class="modal-value">
                        <span class="modal-value-label">Required Revision:</span>
                        <span class="modal-value-data">${
                          issue.required_revision || "Unknown"
                        }</span>
                    </div>
                </div>
            </div>
        `;
  });

  html += "</div></div>";
  return html;
}

function buildEventInformationSection(eventWarnings) {
  let html = `
        <div class="modal-section">
            <h3 style="color: var(--info-color);"><i class="fas fa-info-circle"></i> Event Information</h3>
            <div class="event-notice" style="background: rgba(33, 150, 243, 0.1); padding: 10px; border-radius: 8px; margin-bottom: 15px;">
                <i class="fas fa-lightbulb" style="color: var(--info-color);"></i>
                <span style="color: var(--info-color); margin-left: 8px;">Events are informational only and do not affect compliance status.</span>
            </div>
            <div class="modal-items">
    `;

  eventWarnings.forEach((warning) => {
    const isWarning = warning.severity === "warning";
    html += `
            <div class="modal-item event-item">
                <div class="modal-item-header">
                    <span class="modal-id-badge ${
                      isWarning ? "warning" : "info"
                    }">${warning.event_id || "Event"}</span>
                    <span class="modal-name ${
                      isWarning ? "warning" : "info"
                    }">${
                      warning.event_name || warning.type || "Event Information"
                    }</span>
                </div>
                <div class="modal-values">
                    <div class="modal-value">
                        <span class="modal-value-label">Message:</span>
                        <span class="modal-value-data">${warning.message}</span>
                    </div>
                    ${
                      warning.severity
                        ? `
                    <div class="modal-value">
                        <span class="modal-value-label">Severity:</span>
                        <span class="modal-value-data">${
                          warning.severity
                        }</span>
                    </div>
                    `
                        : ""
                    }
                </div>
            </div>
        `;
  });

  html += "</div></div>";
  return html;
}

function buildAttributesSection(attributes, validationData) {
  let html = `
        <div class="modal-section">
            <h3><i class="fas fa-list"></i> Attributes</h3>
            <div class="modal-items">
    `;

  // Create name mapping from AttributeList
  const nameMap = {};
  if (attributes.AttributeList && attributes.AttributeList.AttributeList) {
    attributes.AttributeList.AttributeList.forEach((attr) => {
      if (typeof attr === "object" && attr !== null && attr.id) {
        nameMap[attr.id] = attr.name;
      }
      // If attr is just a number, we can't get the name from it
      // The name will be generated from the attrId later
    });
  }

  // Display all attributes
  Object.entries(attributes).forEach(([attrId, attrData]) => {
    // Skip empty attributes but show AttributeList
    if (attrData !== null && attrData !== undefined) {
      const attrName =
        nameMap[attrId] ||
        attrId.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());

      html += `
                <div class="modal-item">
                    <div class="modal-item-header">
                        <span class="modal-id-badge">${attrId}</span>
                        <span class="modal-name">${attrName}</span>
                    </div>
                    <div class="modal-values">
            `;

      if (typeof attrData === "object" && attrData !== null) {
        Object.entries(attrData).forEach(([key, value]) => {
          const displayValue =
            typeof value === "object" ? JSON.stringify(value, null, 2) : value;
          html += `
                        <div class="modal-value">
                            <span class="modal-value-label">${key
                              .replace(/_/g, " ")
                              .replace(/\b\w/g, (l) => l.toUpperCase())}:</span>
                            <span class="modal-value-data">${
                              displayValue
                            }</span>
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

  html += "</div></div>";
  return html;
}

function buildCommandsSection(commands, validationData) {
  let html = `
        <div class="modal-section">
            <h3><i class="fas fa-terminal"></i> Commands</h3>
            <div class="modal-items">
    `;

  // Generated Commands
  if (
    commands.GeneratedCommandList &&
    commands.GeneratedCommandList.GeneratedCommandList
  ) {
    commands.GeneratedCommandList.GeneratedCommandList.forEach((cmd) => {
      let cmdId, cmdName;

      if (typeof cmd === "object" && cmd !== null) {
        cmdId = cmd.id || "Unknown";
        cmdName = cmd.name
          ? cmd.name.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())
          : "Unknown Command";
      } else {
        // cmd is a number
        cmdId = `0x${parseInt(cmd).toString(16).toUpperCase().padStart(4, "0")}`;
        cmdName = `Command ${cmdId}`;
      }

      html += `
                <div class="modal-item">
                    <div class="modal-item-header">
                        <span class="modal-id-badge">${cmdId}</span>
                        <span class="modal-name">${cmdName}</span>
                        <span class="modal-type-badge generated">Generated</span>
                    </div>
                </div>
            `;
    });
  }

  // Accepted Commands
  if (
    commands.AcceptedCommandList &&
    commands.AcceptedCommandList.AcceptedCommandList
  ) {
    commands.AcceptedCommandList.AcceptedCommandList.forEach((cmd) => {
      let cmdId, cmdName;

      if (typeof cmd === "object" && cmd !== null) {
        cmdId = cmd.id || "Unknown";
        cmdName = cmd.name
          ? cmd.name.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())
          : "Unknown Command";
      } else {
        // cmd is a number
        cmdId = `0x${parseInt(cmd).toString(16).toUpperCase().padStart(4, "0")}`;
        cmdName = `Command ${cmdId}`;
      }

      html += `
                <div class="modal-item">
                    <div class="modal-item-header">
                        <span class="modal-id-badge">${cmdId}</span>
                        <span class="modal-name">${cmdName}</span>
                        <span class="modal-type-badge accepted">Accepted</span>
                    </div>
                </div>
            `;
    });
  }

  html += "</div></div>";
  return html;
}

function buildEventsSection(events) {
  let html = `
        <div class="modal-section">
            <h3><i class="fas fa-bolt"></i> Events</h3>
            <div class="modal-items">
    `;

  events.forEach((event) => {
    html += `
            <div class="modal-item">
                <div class="modal-item-header">
                    <span class="modal-id-badge">${event.id}</span>
                    <span class="modal-name">${event.name
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (l) => l.toUpperCase())}</span>
                    <span class="modal-type-badge event">Event</span>
                </div>
            </div>
        `;
  });

  html += "</div></div>";
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
                    <span class="modal-name">${featureId
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (l) => l.toUpperCase())}</span>
                </div>
        `;

    if (typeof featureData === "object" && featureData !== null) {
      html += '<div class="modal-values">';
      Object.entries(featureData).forEach(([key, value]) => {
        html += `
                    <div class="modal-value">
                        <span class="modal-value-label">${key
                          .replace(/_/g, " ")
                          .replace(/\b\w/g, (l) => l.toUpperCase())}:</span>
                        <span class="modal-value-data">${value}</span>
                    </div>
                `;
      });
      html += "</div>";
    }

    html += "</div>";
  });

  html += "</div></div>";
  return html;
}

function initializeCopyButtons() {
  // Add copy buttons to device type IDs and cluster IDs
  const deviceTypeIds = document.querySelectorAll(".device-type-id");
  const clusterIds = document.querySelectorAll(".cluster-id");

  [...deviceTypeIds, ...clusterIds].forEach((element) => {
    element.style.cursor = "pointer";
    element.title = "Click to copy";
    element.addEventListener("click", function () {
      copyToClipboard(this.textContent);
      showCopySuccess(this);
    });
  });
}

function copyToClipboard(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => {
      console.log("Copied to clipboard:", text);
    });
  } else {
    // Fallback for older browsers
    const textArea = document.createElement("textarea");
    textArea.value = text;
    document.body.appendChild(textArea);
    textArea.select();
    document.execCommand("copy");
    document.body.removeChild(textArea);
  }
}

function showCopySuccess(element) {
  const originalBg = element.style.backgroundColor;
  element.style.backgroundColor = "var(--success-color)";
  element.style.color = "white";

  setTimeout(() => {
    element.style.backgroundColor = originalBg;
    element.style.color = "";
  }, 1000);
}

// ============= DOWNLOAD FUNCTIONALITY =============
window.downloadValidationReport = function () {
  // Use link element to avoid triggering beforeunload
  const link = document.createElement("a");
  link.href = "/api/download/validation";
  link.download = "validation_report.json";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};

window.downloadParsedData = function () {
  // Use link element to avoid triggering beforeunload
  const link = document.createElement("a");
  link.href = "/api/download/parsed";
  link.download = "parsed_data.json";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};

// ============= KEYBOARD SHORTCUTS =============
document.addEventListener("keydown", function (e) {
  // Ctrl/Cmd + U to trigger file upload
  if ((e.ctrlKey || e.metaKey) && e.key === "u") {
    e.preventDefault();
    const fileInput = document.getElementById("fileInput");
    if (fileInput) {
      fileInput.click();
    }
  }

  // Escape to close any open modals or reset upload area
  if (e.key === "Escape") {
    const modal = document.getElementById("clusterModal");
    if (modal && modal.style.display === "flex") {
      closeClusterModal();
    } else {
      resetUploadArea();
    }
  }
});
