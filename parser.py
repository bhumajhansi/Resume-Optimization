import pdfminer.high_level
import docx2txt
import os

def extract_text(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.pdf':
        return pdfminer.high_level.extract_text(filepath)
    elif ext in ['.docx', '.doc']:
        return docx2txt.process(filepath)
    else:
        return "Unsupported file format"
