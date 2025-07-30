import os
import json
import toml
import openai
from tqdm import tqdm
import concurrent.futures
import re

# --- Load OpenAI API key from secrets.toml ---
with open('secrets.toml', 'r') as f:
    secrets = toml.load(f)
openai.api_key = secrets['openai']['api_key']

# --- Load style sample from sample.txt ---
with open('inputs/sample.txt', 'r', encoding='utf-8') as f:
    style_sample = f.read()

# --- Constants ---
JSON_PATH = 'inputs/full_lecture_dump.json'
OUTPUT_ROOT = 'lectures'
MODEL = 'gpt-4.1'  # fallback to 'gpt-3.5-turbo' if needed

# --- Ensure output root directory exists ---
os.makedirs(OUTPUT_ROOT, exist_ok=True)

# --- Load JSON data ---
with open(JSON_PATH, 'r', encoding='utf-8') as f:
    lectures = json.load(f)

# --- Helper: Sanitize folder and file names ---
def sanitize_filename(name):
    name = re.sub(r'[^\w\-_ ]', '', name)
    name = name.strip().replace(' ', '_')
    return name[:100]  # limit length

# --- Helper: Get previous/next lecture titles for smooth transitions ---
def get_prev_next_titles(lectures):
    titles = [lec['title_en'] for lec in lectures]
    prev_next = {}
    for i, title in enumerate(titles):
        prev_title = titles[i-1] if i > 0 else None
        next_title = titles[i+1] if i < len(titles)-1 else None
        prev_next[title] = (prev_title, next_title)
    return prev_next

# --- Helper: Summarize previous lecture script using LLM ---
def summarize_script(script_text, model=MODEL):
    prompt = f"""
You are a helpful assistant. Summarize the following lecture script in 5-7 concise bullet points, focusing on the main ideas and key takeaways. Do not include any content not present in the script.
---
Lecture Script:
{script_text}
---
"""
    try:
        resp = openai.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"[ERROR: Could not summarize previous lecture: {e}]"

def fact_check_script(reference_content, lecture_script, model=MODEL):
    prompt = f"""You are a fact-checking assistant.
    Compare the following lecture script with the provided reference content.
    If the reference content contains the fact, do not correct it and if the fact is not in the reference content, correct it.
    Only correct statements in the script that are factually incorrect according to the reference.
    If a statement is vague or ambiguous due to the lecture's tone or style, do not correct it.
    If you make any corrections, return a JSON object with the following keys:
    \"corrected_script\": \"The corrected script\",
    \"state\": \"Corrected\"
    If no corrections are needed and all facts are accurate, return an empty JSON object: {{}}
    Reference Content:
    {reference_content}
    Lecture Script:
    {lecture_script}
    """
    try:
        resp = openai.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"[ERROR: Could not fact-check lecture: {e}]"

# --- Main pipeline for a single module ---
def process_module(module_name, module_lectures, module_index):
    sanitized_module = sanitize_filename(module_name)
    module_folder = f"{module_index+1:02d}_{sanitized_module}"
    output_dir = os.path.join(OUTPUT_ROOT, module_folder)
    os.makedirs(output_dir, exist_ok=True)
    prev_next_map = get_prev_next_titles(module_lectures)
    summary = []
    for i, lec in enumerate(tqdm(module_lectures, desc=f'Generating {module_folder}')):
        title = lec['title_en']
        sanitized_title = sanitize_filename(title)
        prev_title, next_title = prev_next_map[title]

        # --- Get previous lecture summary if applicable ---
        if prev_title:
            prev_filename = f"{i:02d}_{sanitize_filename(prev_title)}.txt"
            prev_filepath = os.path.join(output_dir, prev_filename)
            if os.path.exists(prev_filepath):
                with open(prev_filepath, 'r', encoding='utf-8') as pf:
                    prev_script = pf.read()
                prev_summary = summarize_script(prev_script)
            else:
                prev_summary = "[Previous lecture script not found.]"
        else:
            prev_summary = "None (this is the first topic in the module)"

        # --- Agent 1: Researcher ---
        print(f"Processing '{title}'...")
        researcher_prompt = f"""
You are a research assistant. Given the following content, extract and summarize the main points and key facts in clear bullet points using the lecture outlines as a reference of what should be included.
IMPORTANT INSTRUCTIONS:
- Use the provided **Lecture Outline** as your structural guide.
- Keep each bullet focused and self-contained.
- Prioritize accuracy and completeness over brevity, but avoid unnecessary detail.
- Label each bullet with a short descriptor (e.g. “Concept: …”, “Example: …”, “Data: …”) when helpful.
- Maintain a professional and objective tone.
Lecture Title: {title}
Content:\n{lec.get('topic_content_en', '').strip()}
Description:\n{lec.get('description', '').strip()}
Learning Objective:\n{lec.get('learning_objective', '').strip()}
Lecture Outline:\n{lec.get('lecture_outline', [])}"""
        try:
            researcher_resp = openai.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": researcher_prompt}],
                temperature=0.3,
            )
            main_points = researcher_resp.choices[0].message.content.strip()
        except Exception as e:
            main_points = f"[ERROR: Could not extract main points for '{title}': {e}]"

        # --- Agent 2: Lecture Structurer ---
        structurer_prompt = f"""
You are an expert course designer. Given these bullet points, organize them into a logical lecture outline with an introduction, main body (with subpoints), transitions, and a conclusion.
Make sure the outline flows naturally and is suitable for a spoken lecture.
Keep the length to 500 words or 3250 characters maximum.
Lecture Title: {title}
Bullet Points:{main_points}
"""
        try:
            structurer_resp = openai.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": structurer_prompt}],
                temperature=0.4,
            )
            structured_outline = structurer_resp.choices[0].message.content.strip()
        except Exception as e:
            structured_outline = f"[ERROR: Could not structure outline for '{title}': {e}]"

        # --- Agent 3: Lecturer ---
        lecturer_prompt = f"""
You are an expert lecturer. Using the following structured outline, write a natural, engaging, and conversational lecture script. Reference the previous and next topics for smooth transitions.
IMPORTANT: Do not overlap with the previous lecture's content (see summary below) or the next lecture's topic.
Keep the length to 500 words or 3250 characters maximum.
Lecture Title: {title}
Structured Outline:\n{structured_outline}
Previous Lecture Summary:\n{prev_summary}
Next Topic: {next_title if next_title else 'None (this is the last topic in the module)'}
"""
        try:
            lecturer_resp = openai.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": lecturer_prompt}],
                temperature=0.7,
            )
            script = lecturer_resp.choices[0].message.content.strip()
        except Exception as e:
            script = f"[ERROR: Could not generate lecture for '{title}': {e}]"

        # --- Agent 4: Mimic Stylist ---
        mimic_prompt = f"""
You are a skilled lecture scriptwriter. Your task is to rewrite the following lecture script so that it mimics the personality, style and structure of the provided example.
IMPORTANT INSTRUCTIONS FOR STYLE:
- Use wide range of discourse markers and conversational openers other than the ones in the example, but maintain the same style and structure.
- Keep the length to 500 words or 3250 characters maximum.
- The format should be for a online lecture, so it should be a single plaintext monologue.
- Do not use any special symbols, create a single plaintext monologue.
- Speak conversationally as if you're directly addressing students.
- Break complex ideas into understandable and simple analogies or stories.
- Avoid overly formal language or overly structured outlines.
- Keep note of the lecture title, previous topic and next topic. If the lecture is the first or last in the module, use the appropriate placeholder in the lecture script.
Lecture Title: {title}
Previous Topic: {prev_title if prev_title else 'None (this is the first topic in the module)'}
Next Topic: {next_title if next_title else 'None (this is the last topic in the module)'}
Lecture Title: {title}
Example Lecture Style:
{style_sample}
Lecture Script to Mimic:{script}
"""
        try:
            mimic_resp = openai.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": mimic_prompt}],
                temperature=0.7,
            )
            mimicked_script = mimic_resp.choices[0].message.content.strip()
        except Exception as e:
            mimicked_script = f"[ERROR: Could not mimic style for '{title}': {e}]"

        # --- Agent 5: Fact-Checker ---
        reference_content = lec.get('topic_content_en', '').strip() or lec.get('content_en', '').strip()
        result = fact_check_script(reference_content, mimicked_script)
        try:
            result_json = json.loads(result)
        except Exception:
            result_json = {}
        if result_json and result_json.get('corrected_script'):
            final_script = result_json['corrected_script'].strip()
            correction_status = 'Corrected'
        else:
            final_script = mimicked_script
            correction_status = 'No corrections needed'

        # --- Save to file ---
        filename = f"{i+1:02d}_{sanitized_title}.txt"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(final_script)
        summary.append((title, filename, correction_status))
    return module_folder, summary

# --- Get all unique module names in order of appearance ---
module_names = []
seen = set()
for lec in lectures:
    module = lec.get('module_en')
    if module and module not in seen:
        module_names.append(module)
        seen.add(module)

# --- Group lectures by module ---
from collections import defaultdict
module_lectures_map = defaultdict(list)
for lec in lectures:
    module = lec.get('module_en')
    if module:
        module_lectures_map[module].append(lec)

# --- Run modules in parallel ---
results = [None] * len(module_names)
import concurrent.futures
with concurrent.futures.ThreadPoolExecutor() as executor:
    future_to_index = {
        executor.submit(process_module, module, module_lectures_map[module], idx): idx
        for idx, module in enumerate(module_names)
    }
    for future in concurrent.futures.as_completed(future_to_index):
        idx = future_to_index[future]
        try:
            result = future.result()
            results[idx] = result
        except Exception as exc:
            print(f'Error processing module {module_names[idx]}: {exc}')

# --- Print summary ---
print(f"\nGenerated lecture scripts in '{OUTPUT_ROOT}':")
for module_folder, summary in results:
    print(f"Module: {module_folder}")
    for title, filename, correction_status in summary:
        print(f"- {filename}: {title} [{correction_status}]") 