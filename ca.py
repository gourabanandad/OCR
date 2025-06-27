from flask import Flask, request, jsonify
import pytesseract
import cv2
import re
import json
import numpy as np
from PIL import Image
import os
from werkzeug.utils import secure_filename
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ----------------------------
# Your existing processing functions
def is_blurry(img):
    return cv2.Laplacian(img, cv2.CV_64F).var() < 150

def smart_preprocess(img_path):
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)

    # Denoise and deblur
    if is_blurry(img):
        img = cv2.GaussianBlur(img, (3, 3), 0)
    else:
        img = cv2.bilateralFilter(img, 11, 17, 17)

    # Auto Resize based on image width
    height, width = img.shape
    zoom_factor = 2 if width > 1200 else 1.6
    img = cv2.resize(img, None, fx=zoom_factor, fy=zoom_factor, interpolation=cv2.INTER_LINEAR)

    # Binary Thresholding
    img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

    return img

def safe_mark(value):
    if not value or value.strip().upper() == "A":
        return 'A'
    try:
        return float(value) if '.' in value else int(value)
    except:
        return None

def extract_table_text(img):
    custom_config = r'--oem 3 --psm 6'
    return pytesseract.image_to_string(img, config=custom_config)

def parse_ocr_marks(ocr_text):
    ocr_text = ocr_text.replace('{', '(').replace('}', ')').replace('[', '(').replace(']', ')').replace(',', '.')
    cleaned_text = re.sub(r'Page\sCount:\d{,3}', ' ', ocr_text, flags=re.IGNORECASE)
    lines = [line.strip() for line in cleaned_text.split('\n') if line.strip()]
    
    results = []
    current_record = None
    teacher_parts = []

    for line in lines:
        paper_code_match = re.match(r'^[A-Z]{2,3}-?\s?\(?[A-Z]{,3}\)?\s?\d{3}\s?[A-Z]?\(\d{4}\)', line)
        if paper_code_match:
            if current_record:
                current_record["teacher"] = ' '.join(teacher_parts).strip()
                results.append(current_record)
                teacher_parts = []

            code = paper_code_match.group(0)
            remaining = line[paper_code_match.end():].strip()

            marks_match = re.search(r'(.+?)\s+([A\d.]+)?\s+([A\d.]+)?\s+([A\d.]+)?(?:\s+([A\d.]+))?\s+([A-Z][A-Za-z .]+)$', remaining)
            if marks_match:
                subject = marks_match.group(1).strip().rstrip('.')
                raw_ca1 = marks_match.group(2)
                raw_ca2 = marks_match.group(3)
                third_value = marks_match.group(4)
                fourth_value = marks_match.group(5)
                teacher_start = marks_match.group(6).strip()

                ca1 = safe_mark(raw_ca1)
                ca2 = safe_mark(raw_ca2)

                if third_value and '.' in third_value:
                    ca3 = safe_mark(third_value)
                    ca4 = safe_mark(fourth_value)
                else:
                    ca3 = None
                    ca4 = safe_mark(third_value)
                teacher_start = marks_match.group(6).strip()

                current_record = {
                    "paper_code": code,
                    "subject": subject,
                    "CA1": ca1,
                    "CA2": ca2,
                    "CA3": ca3,
                    "CA4": ca4
                }
                teacher_parts = [teacher_start]
        elif current_record:
            teacher_parts.append(line.strip())

    if current_record:
        current_record["teacher"] = ' '.join(teacher_parts).strip()
        results.append(current_record)

    return results

# ----------------------------
# API Endpoint
@app.route('/process-marks', methods=['POST'])
def process_marks():
    # Check if the post request has the file part
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            # Process the image
            img = smart_preprocess(filepath)
            raw_text = extract_table_text(img)
            parsed_data = parse_ocr_marks(raw_text)
            
            # Clean up - remove the uploaded file after processing
            os.remove(filepath)
            
            return jsonify({
                "status": "success",
                "raw_text": raw_text,
                "parsed_data": parsed_data
            })
        
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
    
    return jsonify({"error": "File type not allowed"}), 400

if __name__ == '__main__':
    app.run(debug=True)