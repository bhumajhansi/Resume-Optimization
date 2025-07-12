from sentence_transformers import SentenceTransformer, util
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics.pairwise import cosine_similarity
from fuzzywuzzy import fuzz
import numpy as np
import spacy
import re


nlp = spacy.load("en_core_web_sm")
model = SentenceTransformer('all-MiniLM-L6-v2')

def preprocess(text):
    return ' '.join([word for word in text.lower().split() if word not in ENGLISH_STOP_WORDS])

def extract_key_phrases(text):
    doc = nlp(text.lower())
    phrases = set()

    for chunk in doc.noun_chunks:
        phrase = chunk.text.strip()
        if 2 < len(phrase) < 50 and phrase.count(" ") <= 3:
            if any(char.isalpha() for char in phrase):
                phrases.add(phrase)

    for token in doc:
        if token.pos_ in ["NOUN", "PROPN"] and not token.is_stop:
            if len(token.text) > 3:
                phrases.add(token.lemma_.strip())

    return list(phrases)

def hybrid_match_score(resume_text, job_desc):
    # --- Semantic Similarity ---
    resume_clean = [sent for sent in re.split(r'[.\n]', resume_text) if len(sent.split()) > 5]
    job_clean = [sent for sent in re.split(r'[.\n]', job_desc) if len(sent.split()) > 5]

    resume_embed = model.encode(resume_clean, convert_to_tensor=True)
    job_embed = model.encode(job_clean, convert_to_tensor=True)

    semantic_score = float(util.cos_sim(resume_embed.mean(dim=0), job_embed.mean(dim=0))) * 100

    # --- TF-IDF Similarity ---
    tfidf = TfidfVectorizer(stop_words="english")
    tfidf_matrix = tfidf.fit_transform([preprocess(resume_text), preprocess(job_desc)])
    tfidf_score = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0] * 100

    # --- Fuzzy Matching ---
    resume_phrases = extract_key_phrases(resume_text)
    job_phrases = extract_key_phrases(job_desc)

    fuzzy_hits = sum(1 for j in job_phrases for r in resume_phrases if fuzz.token_set_ratio(j, r) > 85)
    fuzzy_score = min(fuzzy_hits / len(job_phrases), 1) * 100 if job_phrases else 0

    # --- Weighted Score ---
    final_score = round(0.5 * semantic_score + 0.35 * tfidf_score + 0.15 * fuzzy_score, 2)

    print(f"[DEBUG] Semantic: {semantic_score:.2f}, TF-IDF: {tfidf_score:.2f}, Fuzzy: {fuzzy_score:.2f}, Final: {final_score:.2f}")
    return final_score
