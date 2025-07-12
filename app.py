from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, current_user, login_required
from auth import auth_bp, login_manager
from job_predictor import job_predictor_bp
from ats_score import ats_score_bp
from job_matcher import job_matcher_bp
from pymongo import MongoClient
import PyPDF2
from dotenv import load_dotenv
import os
from datetime import datetime

app = Flask(__name__)   
load_dotenv()
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

# MongoDB setup
try:
    client = MongoClient(os.getenv('MONGO_URI'))
    db = client.job_portal
    users_collection = db.users
except Exception as e:
    app.logger.error(f"Failed to connect to MongoDB: {e}")
    raise

# Initialize Flask-Login
login_manager.init_app(app)
login_manager.login_view = 'auth.login'

# Register Blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(job_predictor_bp)
app.register_blueprint(ats_score_bp)
app.register_blueprint(job_matcher_bp)

def extract_text_from_pdf(pdf_file):
    text = ""
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        for page in reader.pages:
            extracted = page.extract_text()
            text += extracted if extracted else ""
    except Exception as e:
        app.logger.error(f"Error extracting text from PDF: {e}")
        return ""
    return text

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        if 'resume' not in request.files:
            flash('No file part', 'danger')
            return redirect(url_for('index'))
        file = request.files['resume']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(url_for('index'))
        try:
            resume_text = extract_text_from_pdf(file)
            if not resume_text:
                flash('Failed to extract text from resume. Ensure it’s a valid PDF.', 'danger')
                return redirect(url_for('index'))
            
            # Prepare submission record
            submission = {
                'filename': file.filename,
                'resume_text': resume_text,
                'timestamp': datetime.utcnow(),
                'module': 'index',  # Indicate this is from the index page
                'output': None  # No specific output for index page
            }
            
            # Update user document with submission history
            users_collection.update_one(
                {'email': current_user.id},
                {'$push': {'submissions': submission}, '$set': {'resume_text': resume_text}},
                upsert=True
            )
            flash('Resume uploaded successfully!', 'success')
        except Exception as e:
            flash(f'Error uploading resume: {str(e)}', 'danger')
            return redirect(url_for('index'))
    
    user = users_collection.find_one({'email': current_user.id})
    resume_exists = bool(user and user.get('resume_text'))
    return render_template('index.html', resume_exists=resume_exists)

if __name__ == '__main__':
    app.run(debug=True, port=5001)  