from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import pytesseract
import cv2
import re
import os
import traceback
from werkzeug.utils import secure_filename

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)  # Enable CORS for all routes

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def preprocess_image(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("Could not read image file")
    img = cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    img = cv2.threshold(img, 150, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    return img

def extract_table_text(img):
    custom_config = r'--oem 3 --psm 6'
    return pytesseract.image_to_string(img, config=custom_config)

def clean_paper_code(code):
    return re.sub(r'\(.*?\)', '', code).strip()

def parse_ocr_marks(ocr_text):
    cleaned_text = re.sub(r'Page Count:\s*\d+', '', ocr_text, flags=re.IGNORECASE)
    lines = [line.strip() for line in cleaned_text.split('\n') if line.strip()]
    
    results = []
    current_record = None
    teacher_parts = []
    
    for line in lines:
        paper_code_match = re.match(r'^([A-Z]{2,}[\s-]?[A-Z\d]*\d+)\(?\d*\)?', line)
        
        if paper_code_match:
            if current_record:
                current_record["teacher"] = ' '.join(teacher_parts).strip()
                results.append(current_record)
                teacher_parts = []
            
            code = clean_paper_code(paper_code_match.group(1))
            remaining = line[paper_code_match.end():].strip()
            
            marks_match = re.search(r'(.+?)\s+(\d+)\s+(\d+)\s+([\d.]+)(?:\s+(\d+))?\s+(.+)$', remaining)
            if marks_match:
                subject = marks_match.group(1).strip().rstrip('.')
                current_record = {
                    "paper_code": code,
                    "subject": subject,
                    "CA1": int(marks_match.group(2)),
                    "CA2": int(marks_match.group(3)),
                    "CA3": float(marks_match.group(4)),
                    "CA4": int(marks_match.group(5)) if marks_match.group(5) else None,
                    "teacher": marks_match.group(6).strip()
                }
                teacher_parts = [marks_match.group(6).strip()]
        elif current_record:
            teacher_parts.append(line.strip())
    
    if current_record:
        current_record["teacher"] = ' '.join(teacher_parts).strip()
        results.append(current_record)
    
    return results

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    response_template = {
        "status": "error",
        "error": "",
        "message": "",
        "parsed_data": [],
        "raw_text": ""
    }
    
    try:
        if 'file' not in request.files:
            response_template.update({
                "error": "No file part",
                "message": "Please select a file to upload"
            })
            return jsonify(response_template), 400
        
        file = request.files['file']
        
        if file.filename == '':
            response_template.update({
                "error": "No selected file",
                "message": "Please select a file to upload"
            })
            return jsonify(response_template), 400
        
        if not allowed_file(file.filename):
            response_template.update({
                "error": "Invalid file type",
                "message": "Only JPG, JPEG, and PNG files are allowed"
            })
            return jsonify(response_template), 400
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            img = preprocess_image(filepath)
            raw_text = extract_table_text(img)
            parsed_data = parse_ocr_marks(raw_text)
            
            response_template.update({
                "status": "success",
                "message": "Image processed successfully",
                "parsed_data": parsed_data,
                # "raw_text": raw_text
            })
            return jsonify(response_template), 200
            
        except Exception as e:
            app.logger.error(f"Processing error: {str(e)}\n{traceback.format_exc()}")
            response_template.update({
                "error": str(e),
                "message": "Error processing image"
            })
            return jsonify(response_template), 500
            
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
                
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
        response_template.update({
            "error": "Internal server error",
            "message": "An unexpected error occurred"
        })
        return jsonify(response_template), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=5000, debug=True)