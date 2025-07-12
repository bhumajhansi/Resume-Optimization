from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from pymongo import MongoClient
import os
from dotenv import load_dotenv
import re
import pandas as pd
from PyPDF2 import PdfReader
from docx import Document
from datetime import datetime

ats_score_bp = Blueprint('ats_score', __name__)
load_dotenv()

# MongoDB setup
client = MongoClient(os.getenv('MONGO_URI'))
db = client.job_portal
users_collection = db.users

# Load dataset at startup
data_path = 'C:/Users/91938/OneDrive/Desktop/resume project/ResumeOptimization/data.csv'
if not os.path.exists(data_path):
    raise FileNotFoundError("Dataset file not found. Please check the file path.")
df = pd.read_csv(data_path)

def extract_text(file):
    text = ""
    page_count = 0
    try:
        if file.filename.endswith('.pdf'):
            pdf = PdfReader(file)
            page_count = len(pdf.pages)
            for page in pdf.pages:
                text += page.extract_text() or ""
        elif file.filename.endswith('.docx'):
            doc = Document(file)
            page_count = 1
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
        else:
            return "Unsupported file format", 0
    except Exception as e:
        return f"Error extracting text: {str(e)}", 0
    return text, page_count

def get_job_data():
    skills = set()
    titles = df["Job Title"].dropna().tolist()
    for skill_list in df["IT Skills"].dropna():
        skills.update(skill_list.split(", "))
    return list(skills), titles

def analyze_formatting(text, page_count):
    score = 100
    text_lower = text.lower()
    if page_count > 2: score -= 15
    if "\n\n" not in text: score -= 10
    if re.search(r'<table|<tr|<td|<th|\|', text, re.IGNORECASE): score -= 15
    date_patterns = [r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b", r"\b\d{2}/\d{4}\b", r"\b\d{4}\b"]
    found_dates = [re.findall(pattern, text) for pattern in date_patterns]
    found_dates = [date for sublist in found_dates for date in sublist]
    if len(set(found_dates)) > 1: score -= 10
    bullet_count = sum(len(re.findall(pattern, text, re.MULTILINE)) for pattern in [r"^\s*[-•]\s+", r"^\s*\d+\.\s+"])
    if bullet_count < 5: score -= 10
    if re.search(r'header|footer', text, re.IGNORECASE): score -= 5
    if re.search(r'[✔★►→❖✨]', text): score -= 10
    if re.search(r'\.(png|jpg|jpeg|gif|svg)|<img', text, re.IGNORECASE): score -= 15
    if len(re.findall(r'\*{1,2}.*?\*{1,2}|_{1,2}.*?_{1,2}', text)) > 5: score -= 10
    if re.search(r'[^\x00-\x7F]+', text): score -= 10
    if len(re.findall(r'(\*\*|\*|__|_)[\w\s]+(\*\*|\*|__|_)', text)) > 10: score -= 10
    missing_headers = sum(1 for header in ["education", "experience", "skills", "projects", "certifications", "contact", "summary"] if header not in text_lower)
    if missing_headers > 2: score -= 10
    if len(re.findall(r'[^\w\s,.!?-]', text)) > 20: score -= 10
    word_count = len(text.split())
    if word_count < 200 or word_count > 1500: score -= 10
    repeated_words = {word for word in text.split() if text.split().count(word) > 10}
    if len(repeated_words) > 5: score -= 10
    return max(score, 0)

def analyze_experience(text):
    text_lower = text.lower()
    has_internship = "internship" in text_lower
    experience_patterns = re.findall(r'(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})\s*[-–]\s*(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)?\s*\d{4}|\bPresent)', text)
    work_years = sum(max(0, (2025 if 'present' in end.lower() else int(re.search(r'\d{4}', end).group())) - int(re.search(r'\d{4}', start).group())) for start, end in experience_patterns)
    return min(20 + (work_years * 10), 100) if work_years >= 1 else (40 if has_internship else 20)

def analyze_skills(text):
    skills_list, _ = get_job_data()
    text_lower = text.lower()
    matched_skills = [skill for skill in skills_list if skill.lower() in text_lower]
    skills_score = min(len(matched_skills) * 5, 50)
    soft_skills = ['communication', 'teamwork', 'leadership', 'problem-solving', 'adaptability']
    matched_soft_skills = [skill for skill in soft_skills if skill in text_lower]
    skills_score += min(len(matched_soft_skills) * 5, 20)
    return skills_score

def analyze_education(text):
    text_lower = text.lower()
    score = 0
    if re.search(r'\b(phd|doctorate)\b', text_lower): score = 100
    elif re.search(r'\b(master|m\.tech|postgraduate|pg diploma)\b', text_lower): score = 90
    elif re.search(r'\b(bachelor|b\.tech|under\s?graduation|engineering|bsc|bca)\b', text_lower): score = 70
    elif re.search(r'\b(intermediate|12th|higher\s?secondary|junior college)\b', text_lower): score = 50
    elif re.search(r'\b(secondary\s?school|10th|high\s?school)\b', text_lower): score = 40
    if re.search(r'\b(cgpa|gpa)\s*[:\-]?\s*\d+(\.\d+)?', text_lower): score += 20
    elif re.search(r'\bpercentage\s*[:\-]?\s*\d{2,3}', text_lower): score += 15
    if re.search(r'\b(university|college|institute|school)\b', text_lower): score += 10
    if re.search(r'\b(certified|certification|certificate|course)\b', text_lower): score += 10
    return min(score, 100)

def analyze_certifications(text):
    text_lower = text.lower()
    return 50 if any(cert in text_lower for cert in ['certified', 'certification', 'certificate']) else 0

@ats_score_bp.route('/ats_score', methods=['GET', 'POST'])
@login_required
def ats_score():
    uploaded_filename = None

    if request.method == 'POST':
        if 'resume' not in request.files:
            flash('No file part', 'danger')
            return redirect(url_for('ats_score'))
        file = request.files['resume']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(url_for('ats_score'))
        if not (file.filename.endswith('.pdf') or file.filename.endswith('.docx')):
            flash('Only PDF and DOCX files are supported', 'danger')
            return redirect(url_for('ats_score'))

        uploaded_filename = file.filename
        resume_text, page_count = extract_text(file)
        if "Error" in resume_text or "Unsupported" in resume_text:
            flash(resume_text, 'danger')
            return redirect(url_for('ats_score'))

        try:
            formatting_score = analyze_formatting(resume_text, page_count)
            experience_score = analyze_experience(resume_text)
            skills_score = analyze_skills(resume_text)
            education_score = analyze_education(resume_text)
            cert_score = analyze_certifications(resume_text)
            overall_score = (skills_score * 0.50) + (experience_score * 0.30) + (formatting_score * 0.10) + \
                            (education_score * 0.05) + (cert_score * 0.05)

            # Store submission and output in MongoDB
            submission = {
                'filename': uploaded_filename,
                'resume_text': resume_text,
                'timestamp': datetime.utcnow(),
                'module': 'ats_score',
                'output': {
                    'overall_score': overall_score,
                    'formatting_score': formatting_score,
                    'experience_score': experience_score,
                    'skills_score': skills_score,
                    'education_score': education_score,
                    'cert_score': cert_score
                }
            }
            users_collection.update_one(
                {'email': current_user.id},
                {'$push': {'submissions': submission}},
                upsert=True
            )

            return render_template('ats_score.html', overall_score=overall_score, formatting_score=formatting_score,
                                experience_score=experience_score, skills_score=skills_score,
                                education_score=education_score, cert_score=cert_score,
                                uploaded_filename=uploaded_filename)
        except Exception as e:
            flash(f"Error calculating ATS score: {str(e)}", 'danger')
            return redirect(url_for('ats_score'))

    return render_template('ats_score.html', uploaded_filename=uploaded_filename)