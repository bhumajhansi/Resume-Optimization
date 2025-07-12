from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from pymongo import MongoClient
import pandas as pd
import os
from dotenv import load_dotenv
import PyPDF2
import spacy
import nltk
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from datetime import datetime

job_predictor_bp = Blueprint('job_predictor', __name__)
load_dotenv()

# MongoDB setup
client = MongoClient(os.getenv('MONGO_URI'))
db = client.job_portal
users_collection = db.users

# Load NLP model
nlp = spacy.load("en_core_web_sm")
nltk.download('punkt', quiet=True)
nltk.download('stopwords', quiet=True)

# Load job dataset
data_path = 'C:/Users/91938/OneDrive/Desktop/resume project/ResumeOptimization/data.csv'
try:
    job_data = pd.read_csv(data_path)
except FileNotFoundError:
    print(f"Error: {data_path} not found. Please ensure data.csv is in the project root.")
    raise

def extract_text_from_pdf(pdf_file):
    text = ""
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + " "
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""
    return text.strip()

def extract_skills(text):
    doc = nlp(text)
    skills = {ent.text.lower() for ent in doc.ents if ent.label_ in {"ORG", "PRODUCT", "SKILL"} and not ent.text.isdigit()}
    for chunk in doc.noun_chunks:
        chunk_text = chunk.text.lower()
        if len(chunk_text) > 1 and not chunk_text.isdigit():
            skills.add(chunk_text)
    return skills

def calculate_skills_match(resume_skills, job_skills):
    if not job_skills or not resume_skills:
        return 0.0
    common_skills = len(resume_skills.intersection(job_skills))
    total_job_skills = len(job_skills)
    return (common_skills / total_job_skills) * 100 if total_job_skills > 0 else 0.0

def predict_job_title(resume_text, job_dataset):
    resume_skills = extract_skills(resume_text)
    if not resume_skills:
        flash('No relevant skills extracted from the resume.', 'danger')
        return None

    job_dataset["Skill_Join"] = job_dataset["IT Skills"].fillna("") + " " + job_dataset["Soft Skills"].fillna("")
    all_skills = set()
    for skill_text in job_dataset["Skill_Join"]:
        all_skills.update(extract_skills(str(skill_text)))

    vectorizer = TfidfVectorizer(vocabulary=all_skills, lowercase=True, ngram_range=(1,3), max_df=0.85, min_df=1, sublinear_tf=True)
    job_vectors = vectorizer.fit_transform(job_dataset["Skill_Join"].astype(str).tolist())
    resume_vector = vectorizer.transform([" ".join(resume_skills)])
    similarities = cosine_similarity(resume_vector, job_vectors)[0]

    job_dataset["Similarity"] = similarities
    matched_jobs_df = job_dataset.sort_values(by="Similarity", ascending=False).head(5)[["Job Title", "Skill_Join"]]

    job_matches = []
    for _, row in matched_jobs_df.iterrows():
        job_skills = extract_skills(str(row["Skill_Join"]))
        match_percentage = calculate_skills_match(resume_skills, job_skills)
        job_matches.append({
            "Job Title": row["Job Title"],
            "Skills Match": match_percentage
        })

    job_matches.sort(key=lambda x: x["Skills Match"], reverse=True)
    return job_matches

@job_predictor_bp.route('/job_predictor', methods=['GET', 'POST'])
@login_required
def job_predictor():
    uploaded_filename = None

    if request.method == 'POST':
        if 'resume' not in request.files:
            flash('No file part', 'danger')
            return redirect(url_for('job_predictor.job_predictor'))
        file = request.files['resume']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(url_for('job_predictor.job_predictor'))
        if not file.filename.endswith('.pdf'):
            flash('Only PDF files are supported', 'danger')
            return redirect(url_for('job_predictor.job_predictor'))

        uploaded_filename = file.filename
        resume_text = extract_text_from_pdf(file)
        if not resume_text:
            flash('Could not extract text from resume. Please upload a valid PDF.', 'danger')
            return redirect(url_for('job_predictor.job_predictor'))

        suggested_jobs = predict_job_title(resume_text, job_data)
        if suggested_jobs is None:
            return redirect(url_for('job_predictor.job_predictor'))

        # Store submission and output in MongoDB
        submission = {
            'filename': uploaded_filename,
            'resume_text': resume_text,
            'timestamp': datetime.utcnow(),
            'module': 'job_predictor',
            'output': suggested_jobs
        }
        users_collection.update_one(
            {'email': current_user.id},
            {'$push': {'submissions': submission}},
            upsert=True
        )

        return render_template('job_predictor.html', jobs=suggested_jobs, uploaded_filename=uploaded_filename)

    return render_template('job_predictor.html', uploaded_filename=uploaded_filename)