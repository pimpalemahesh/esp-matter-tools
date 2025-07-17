from flask import Flask, request, render_template, jsonify, send_file
import json
import logging
import os
import time

# Import our modular components
from core.log_parser import parse_datamodel_logs
from core.compliance_checker import (
    validate_device_compliance,
    load_element_requirements,
)

# Configure Flask to find templates and static files from parent directory
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
template_dir = os.path.join(parent_dir, "templates")
static_dir = os.path.join(parent_dir, "static")

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB limit

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define paths for JSON files
OUTPUT_DIR = "output"
PARSED_DATA_FILE = os.path.join(OUTPUT_DIR, "parsed_data.json")
VALIDATION_RESULTS_FILE = os.path.join(OUTPUT_DIR, "validation_results.json")

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Clear existing JSON files on app start (refresh behavior)
def clear_existing_files():
    """Clear existing JSON files to reset the app state"""
    try:
        if os.path.exists(PARSED_DATA_FILE):
            os.remove(PARSED_DATA_FILE)
            logger.info("Cleared existing parsed_data.json")
        if os.path.exists(VALIDATION_RESULTS_FILE):
            os.remove(VALIDATION_RESULTS_FILE)
            logger.info("Cleared existing validation_results.json")
    except Exception as e:
        logger.error(f"Error clearing existing files: {e}")

# Clear files on app start
clear_existing_files()


@app.route("/", methods=["GET", "POST"])
def index():
    """Main page for file upload and results display"""
    parsed_data = None
    validation_data = None
    error = None
    uploaded_filename = None

    # Load existing validation results if available
    if os.path.exists(VALIDATION_RESULTS_FILE):
        try:
            with open(VALIDATION_RESULTS_FILE, "r") as f:
                validation_data = json.load(f)
        except Exception as e:
            logger.error(f"Error loading validation results: {e}")

    # Load existing parsed data if available
    if os.path.exists(PARSED_DATA_FILE):
        try:
            with open(PARSED_DATA_FILE, "r") as f:
                parsed_data = json.load(f)
        except Exception as e:
            logger.error(f"Error loading parsed data: {e}")

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
            logger.info(f"Processing file: {file.filename}, size: {len(data)} bytes")

            # Parse the data
            parsed_data = parse_datamodel_logs(data)
            logger.info("Successfully parsed data")

            # Save parsed data
            with open(PARSED_DATA_FILE, "w") as f:
                json.dump(parsed_data, f, indent=2)

        except Exception as e:
            logger.error(f"Error processing request: {str(e)}")
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
                jsonify(
                    {
                        "error": f'Invalid chip_version. Must be one of: {", ".join(valid_versions)}'
                    }
                ),
                400,
            )

        # Check if parsed data exists
        if not os.path.exists(PARSED_DATA_FILE):
            return (
                jsonify(
                    {
                        "error": "No parsed data found. Please upload and parse a wildcard file first."
                    }
                ),
                400,
            )

        # Check if element requirements file exists
        requirements_file = f"data/element_requirements_{chip_version}.json"
        if not os.path.exists(requirements_file):
            return (
                jsonify(
                    {
                        "error": f"Version {chip_version} is not supported yet. Currently supported versions will be available once the element requirements are generated."
                    }
                ),
                400,
            )

        # Load requirements and validate
        element_requirements = load_element_requirements(chip_version)
        if not element_requirements:
            return (
                jsonify(
                    {
                        "error": f"Failed to load element requirements for version {chip_version}."
                    }
                ),
                500,
            )

        # Load parsed data
        with open(PARSED_DATA_FILE, "r") as f:
            parsed_data = json.load(f)

        # Perform validation
        validation_data = validate_device_compliance(
            parsed_data, element_requirements, chip_version
        )

        # Save validation results
        with open(VALIDATION_RESULTS_FILE, "w") as f:
            json.dump(validation_data, f, indent=2)

        logger.info(f"Compliance validation completed for version {chip_version}")
        return jsonify(
            {
                "success": True,
                "message": f"Compliance validation completed for version {chip_version}",
                "summary": validation_data.get("summary", {}),
            }
        )

    except Exception as e:
        logger.error(f"Error in validate_compliance: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/clear-data", methods=["POST"])
def clear_data():
    """API endpoint to clear parsed data and validation results"""
    try:
        if os.path.exists(PARSED_DATA_FILE):
            os.remove(PARSED_DATA_FILE)
            logger.info("Removed parsed_data.json")

        if os.path.exists(VALIDATION_RESULTS_FILE):
            os.remove(VALIDATION_RESULTS_FILE)
            logger.info("Removed validation_results.json")

        return jsonify({"success": True, "message": "Data cleared successfully"})

    except Exception as e:
        logger.error(f"Error clearing data: {e}")
        return jsonify({"error": f"Failed to clear data: {str(e)}"}), 500


@app.route("/api/download/<data_type>")
def download_data(data_type):
    """API endpoint to download parsed data or validation results"""
    try:
        if data_type == "parsed":
            with open(PARSED_DATA_FILE, "r") as f:
                data = json.load(f)
            filename = "parsed_data.json"
        elif data_type == "validation":
            with open(VALIDATION_RESULTS_FILE, "r") as f:
                data = json.load(f)
            filename = "validation_results.json"
        else:
            return jsonify({"error": "Invalid data type"}), 400

        response = jsonify(data)
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        return response

    except FileNotFoundError:
        return jsonify({"error": "Data not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def main():
    """Main function to run the Flask application"""
    app.run(debug=True, host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
