from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from pymongo import MongoClient
from werkzeug.security import generate_password_hash,check_password_hash
import PyPDF2
from dotenv import load_dotenv
import os

auth_bp = Blueprint('auth', __name__)
load_dotenv()

# MongoDB setup
client = MongoClient(os.getenv('MONGO_URI'))
db = client.job_portal
users_collection = db.users

# Flask-Login setup
login_manager = LoginManager()

class User(UserMixin):
    def __init__(self, email):
        self.id = email

@login_manager.user_loader
def load_user(email):
    user = users_collection.find_one({'email': email})
    return User(email) if user else None

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        if users_collection.find_one({'email': email}):
            flash('Email already exists!', 'danger')
            return redirect(url_for('auth.register'))
        
        # ✅ Correct hashing method
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        
        users_collection.insert_one({'email': email, 'password': hashed_password, 'resume_text': None})
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = users_collection.find_one({'email': email})
        if user and check_password_hash(user['password'], password):
            login_user(User(email))
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        flash('Invalid credentials!', 'danger')
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))

def extract_text_from_pdf(pdf_file):
    text = ""
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        for page in reader.pages:
            extracted = page.extract_text()
            text += extracted if extracted else ""
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""
    return text

@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        if 'resume' not in request.files:
            flash('No file part', 'danger')
            return redirect(url_for('auth.profile'))
        file = request.files['resume']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(url_for('auth.profile'))
        try:
            resume_text = extract_text_from_pdf(file)
            if not resume_text:
                flash('Failed to extract text from resume. Ensure it’s a valid PDF.', 'danger')
                return redirect(url_for('auth.profile'))
            users_collection.update_one(
                {'email': current_user.id},
                {'$set': {'resume_text': resume_text}},
                upsert=True
            )
            flash('Resume uploaded successfully!', 'success')
        except Exception as e:
            flash(f'Error uploading resume: {str(e)}', 'danger')
            return redirect(url_for('auth.profile'))
    
    user = users_collection.find_one({'email': current_user.id})
    resume_exists = bool(user and user.get('resume_text'))
    return render_template('profile.html', resume_exists=resume_exists)