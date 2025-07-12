from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from pymongo import MongoClient
import os
import spacy
import pandas as pd
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from parser import extract_text  # Using your custom parser module
from score import calculate_ats_score  # Using your custom score module
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from werkzeug.utils import secure_filename  # Added for secure filename handling

job_matcher_bp = Blueprint('job_matcher', __name__)
load_dotenv()

# MongoDB setup
client = MongoClient(os.getenv('MONGO_URI'))
db = client.job_portal
users_collection = db.users

# Load resources at startup
nlp = spacy.load('en_core_web_sm')
data_path = 'C:/Users/91938/OneDrive/Desktop/resume project/ResumeOptimization/data.csv'
df = pd.read_csv(data_path, encoding="ISO-8859-1")
it_skills = df["IT Skills"].dropna().str.split(",").explode().str.strip().str.lower()
valid_skills = set(it_skills)

# Temporary upload folder
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def extract_phrases(text):
    doc = nlp(text.lower())
    phrases = set()
    stop_phrases = {
        "communication", "team", "work", "responsibilities", "skills",
        "development", "experience", "knowledge", "ability", "role", "scripting skills"
    }
    for chunk in doc.noun_chunks:
        phrase = chunk.text.strip()
        if 2 < len(phrase) < 50 and phrase.count(" ") <= 3:
            if any(char.isalpha() for char in phrase) and phrase not in stop_phrases:
                phrases.add(phrase)
    for token in doc:
        if token.pos_ in ["NOUN", "PROPN"] and not token.is_stop:
            if len(token.text) > 3 and token.text.lower() not in stop_phrases:
                phrases.add(token.lemma_.strip())
    return phrases

def suggest_relevant_skills(job_desc, missing_skills):
    if not missing_skills:
        return []
    vectorizer = TfidfVectorizer()
    vectors = vectorizer.fit_transform([job_desc] + missing_skills)
    similarities = cosine_similarity(vectors[0:1], vectors[1:])
    sorted_indices = similarities.argsort()[0][::-1]
    return [missing_skills[i] for i in sorted_indices[:3]]

def get_learning_resources(skill):
    search_query = f"Best {skill} online course with certification"
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(search_query, max_results=3))[:3]
            return [{"title": r['title'], "url": r['href']} for r in results] if results else []
    except Exception as e:
        print(f"Error fetching certification resources for {skill}: {e}")
        return []

@job_matcher_bp.route('/job_matcher', methods=['GET', 'POST'])
@login_required
def job_matcher():
    job_desc = request.form.get('job_desc', '') if request.method == 'POST' else ''
    uploaded_filename = None

    if request.method == 'POST':
        if 'resume' not in request.files:
            flash('No file part', 'danger')
            return redirect(url_for('job_matcher.job_matcher'))
        file = request.files['resume']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(url_for('job_matcher.job_matcher'))
        if not file.filename.endswith('.pdf'):
            flash('Only PDF files are supported', 'danger')
            return redirect(url_for('job_matcher.job_matcher'))

        # Save the file temporarily
        uploaded_filename = secure_filename(file.filename)
        temp_path = os.path.join(UPLOAD_FOLDER, uploaded_filename)
        file.save(temp_path)

        # Extract text using custom parser
        resume_text = extract_text(temp_path)
        if not resume_text:
            os.remove(temp_path)  # Clean up even if extraction fails
            flash('Failed to extract text from resume. Ensure it’s a valid PDF.', 'danger')
            return redirect(url_for('job_matcher.job_matcher'))

        # Calculate ATS score using custom score module
        score = calculate_ats_score(resume_text, job_desc)

        # Extract and filter skills
        resume_skills = extract_phrases(resume_text)
        job_skills = extract_phrases(job_desc)
        filtered_job_skills = set(skill for skill in job_skills if skill.lower() in valid_skills)
        filtered_resume_skills = set(skill for skill in resume_skills if skill.lower() in valid_skills)
        missing_skills = list(filtered_job_skills - filtered_resume_skills)

        # Suggest relevant skills
        suggested_skills = suggest_relevant_skills(job_desc, missing_skills)

        # Get learning resources for suggested skills
        resources = {skill: get_learning_resources(skill) for skill in suggested_skills}
        valid_suggested_skills = [skill for skill, res in resources.items() if res]
        resources = {skill: res for skill, res in resources.items() if res}

        # Store submission and output in MongoDB
        submission = {
            'filename': uploaded_filename,
            'resume_text': resume_text,
            'timestamp': datetime.utcnow(),
            'module': 'job_matcher',
            'output': {
                'score': score,
                'missing_skills': missing_skills,
                'suggested_skills': valid_suggested_skills,
                'resources': resources,
                'job_desc': job_desc
            }
        }
        users_collection.update_one(
            {'email': current_user.id},
            {'$push': {'submissions': submission}},
            upsert=True
        )

        # Clean up the temporary file
        os.remove(temp_path)

        return render_template('job_matcher.html', score=score, missing_skills=missing_skills,
                               suggested_skills=valid_suggested_skills, resources=resources,
                               job_desc=job_desc, uploaded_filename=uploaded_filename)

    return render_template('job_matcher.html', job_desc=job_desc, uploaded_filename=uploaded_filename)
