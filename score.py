from matcher import hybrid_match_score

def calculate_ats_score(resume_text, job_desc):
    return hybrid_match_score(resume_text, job_desc)
