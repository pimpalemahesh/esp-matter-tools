import json
import logging
import os
import sys
import uuid
from datetime import datetime
from datetime import timedelta

from flask import Flask
from flask import jsonify
from flask import render_template
from flask import request
from flask import session

from core.compliance_checker import load_element_requirements
from core.compliance_checker import validate_device_compliance
from core.log_parser import parse_datamodel_logs

# Add parent directory to Python path to fix imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# Import our modular components

# Configure Flask to find templates and static files from parent directory
template_dir = os.path.join(parent_dir, "templates")
static_dir = os.path.join(parent_dir, "static")

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB limit

# Configure secret key for sessions
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define paths for session-based storage
SESSION_DATA_DIR = "session_data"
os.makedirs(SESSION_DATA_DIR, exist_ok=True)


def get_session_id():
    """Get or create a session ID for the current browser session"""
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
        session.permanent = True
        app.permanent_session_lifetime = timedelta(hours=24)  # Session expires in 24 hours
    return session["session_id"]


def get_session_file_path(session_id, file_type):
    """Get the file path for session-specific data

    :param session_id: param file_type:
    :param file_type:

    """
    return os.path.join(SESSION_DATA_DIR, f"{session_id}_{file_type}.json")


def cleanup_old_sessions():
    """Clean up session files older than 24 hours"""
    try:
        cutoff_time = datetime.now() - timedelta(hours=24)
        for filename in os.listdir(SESSION_DATA_DIR):
            if filename.endswith(".json"):
                file_path = os.path.join(SESSION_DATA_DIR, filename)
                if os.path.getmtime(file_path) < cutoff_time.timestamp():
                    os.remove(file_path)
                    logger.info(f"Cleaned up old session file: {filename}")
    except Exception as e:
        logger.error(f"Error cleaning up old sessions: {e}")


def load_session_data(session_id, data_type):
    """Load data for a specific session

    :param session_id: param data_type:
    :param data_type:

    """
    file_path = get_session_file_path(session_id, data_type)
    try:
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading session data {data_type} for session {session_id}: {e}")
    return None


def save_session_data(session_id, data_type, data):
    """Save data for a specific session

    :param session_id: param data_type:
    :param data:
    :param data_type:

    """
    file_path = get_session_file_path(session_id, data_type)
    try:
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving session data {data_type} for session {session_id}: {e}")
        return False


def clear_session_data(session_id):
    """Clear all data for a specific session

    :param session_id:

    """
    try:
        for data_type in ["parsed_data", "validation_results"]:
            file_path = get_session_file_path(session_id, data_type)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Removed {data_type} for session {session_id}")
        return True
    except Exception as e:
        logger.error(f"Error clearing session data for session {session_id}: {e}")
        return False


@app.before_request
def before_request():
    """Clean up old sessions before each request"""
    cleanup_old_sessions()


@app.route("/", methods=["GET", "POST"])
def index():
    """Main page for file upload and results display"""
    session_id = get_session_id()
    parsed_data = None
    validation_data = None
    error = None
    uploaded_filename = None

    # For GET requests, check if we should preserve session data
    if request.method == "GET":
        # Check if this is a redirect after validation completion
        validation_complete = request.args.get("validation_complete")

        if validation_complete:
            # Load existing data to preserve state after validation
            parsed_data = load_session_data(session_id, "parsed_data")
            validation_data = load_session_data(session_id, "validation_results")
        else:
            # Normal GET request - start fresh
            clear_session_data(session_id)
            parsed_data = None
            validation_data = None
    else:
        # For POST requests (file upload), load existing validation data only
        validation_data = load_session_data(session_id, "validation_results")

    if request.method == "POST":
        try:
            if "file" not in request.files:
                error = "No file uploaded"
                return render_template(
                    "index.html",
                    parsed_data=parsed_data,
                    validation_data=validation_data,
                    uploaded_filename=uploaded_filename,
                    error=error,
                )

            file = request.files["file"]
            if file.filename == "":
                error = "No file selected"
                return render_template(
                    "index.html",
                    parsed_data=parsed_data,
                    validation_data=validation_data,
                    uploaded_filename=uploaded_filename,
                    error=error,
                )

            if not file.filename.endswith(".txt"):
                error = "Please upload a .txt file"
                return render_template(
                    "index.html",
                    parsed_data=parsed_data,
                    validation_data=validation_data,
                    uploaded_filename=uploaded_filename,
                    error=error,
                )

            uploaded_filename = file.filename
            data = file.read().decode("utf-8")
            logger.info(f"Processing file: {file.filename}, size: {len(data)} bytes for session {session_id}")

            # Clear any existing validation data when new file is uploaded
            clear_session_data(session_id)

            # Parse the data
            parsed_data = parse_datamodel_logs(data)
            logger.info(f"Successfully parsed data for session {session_id}")

            # Save parsed data for this session
            if not save_session_data(session_id, "parsed_data", parsed_data):
                error = "Error saving parsed data"

        except Exception as e:
            logger.error(f"Error processing request for session {session_id}: {str(e)}")
            error = f"Error processing file: {str(e)}"

    return render_template(
        "index.html",
        parsed_data=parsed_data,
        validation_data=validation_data,
        uploaded_filename=uploaded_filename,
        error=error,
    )


@app.route("/api/validate-compliance", methods=["POST"])
def validate_compliance():
    """API endpoint to validate compliance against a specific version"""
    try:
        session_id = get_session_id()
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        chip_version = data.get("chip_version", "").strip()

        if not chip_version:
            return jsonify({"error": "chip_version is required"}), 400

        # Validate version choices
        valid_versions = ["1.3", "1.4", "1.4.1", "1.4.2", "master"]
        if chip_version not in valid_versions:
            return (
                jsonify({"error": f'Invalid chip_version. Must be one of: {", ".join(valid_versions)}'}),
                400,
            )

        # Check if parsed data exists for this session
        parsed_data = load_session_data(session_id, "parsed_data")
        if not parsed_data:
            return (
                jsonify({"error": "No parsed data found. Please upload and parse a wildcard file first."}),
                400,
            )

        # Check if element requirements file exists
        requirements_file = f"data/element_requirements_{chip_version}.json"
        if not os.path.exists(requirements_file):
            return (
                jsonify({"error": f"Version {chip_version} is not supported yet. Currently supported versions will be available once the element requirements are generated."}),
                400,
            )

        # Load requirements and validate
        element_requirements = load_element_requirements(chip_version)
        if not element_requirements:
            return (
                jsonify({"error": f"Failed to load element requirements for version {chip_version}."}),
                500,
            )

        # Perform validation
        validation_data = validate_device_compliance(parsed_data, element_requirements, chip_version)

        # Save validation results for this session
        if not save_session_data(session_id, "validation_results", validation_data):
            return jsonify({"error": "Error saving validation results"}), 500

        logger.info(f"Compliance validation completed for version {chip_version} for session {session_id}")
        return jsonify(
            {
                "success": True,
                "message": f"Compliance validation completed for version {chip_version}",
                "summary": validation_data.get("summary", {}),
            }
        )

    except Exception as e:
        logger.error(f"Error in validate_compliance for session {session_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/clear-data", methods=["POST"])
def clear_data():
    """API endpoint to clear parsed data and validation results for current session"""
    try:
        session_id = get_session_id()

        if clear_session_data(session_id):
            logger.info(f"Cleared data for session {session_id}")
            return jsonify({"success": True, "message": "Data cleared successfully"})
        else:
            return jsonify({"error": "Failed to clear session data"}), 500

    except Exception as e:
        logger.error(f"Error clearing data for session {session_id}: {e}")
        return jsonify({"error": f"Failed to clear data: {str(e)}"}), 500


@app.route("/api/download/<data_type>")
def download_data(data_type):
    """API endpoint to download parsed data or validation results for current session

    :param data_type:

    """
    try:
        session_id = get_session_id()

        if data_type == "parsed":
            data = load_session_data(session_id, "parsed_data")
            filename = "parsed_data.json"
        elif data_type == "validation":
            data = load_session_data(session_id, "validation_results")
            filename = "validation_results.json"
        else:
            return jsonify({"error": "Invalid data type"}), 400

        if not data:
            return jsonify({"error": "Data not found for current session"}), 404

        response = jsonify(data)
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        return response

    except Exception as e:
        logger.error(f"Error downloading data for session {session_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500


def main():
    """Main function to run the Flask application"""
    app.run(debug=True, host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
