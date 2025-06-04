# src/routes/utils.py
import re
import string

def clean_text(text):
    """Clean and preprocess text for emotion analysis"""
    text = str(text).lower()
    text = re.sub(r'\d+', '', text)  # Remove digits
    text = text.translate(str.maketrans("", "", string.punctuation))  # Remove punctuation
    text = re.sub(r'\s+', ' ', text).strip()  # Normalize whitespace
    return text