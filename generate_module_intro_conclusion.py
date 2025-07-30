import os
import json
import toml
import openai
from tqdm import tqdm
import re
import concurrent.futures
from collections import defaultdict

# --- Load OpenAI API key from secrets.toml ---
with open('secrets.toml', 'r') as f:
    secrets = toml.load(f)
openai.api_key = secrets['openai']['api_key']

# --- Load style sample from sample.txt ---
with open('intputs/sample.txt', 'r', encoding='utf-8') as f:
    style_sample = f.read()

# --- Load course title from course_info.json ---
with open('inputs/course_info.json', 'r', encoding='utf-8') as f:
    course_info = json.load(f)
course_title = course_info.get('course_title', 'Course')

# --- Constants ---
LECTURE_DUMP_PATH = 'inputs/full_lecture_dump.json'
OUTPUT_ROOT = 'lectures'
MODEL = 'gpt-4.1'

# --- Ensure output root directory exists ---
os.makedirs(OUTPUT_ROOT, exist_ok=True)

# --- Load and process full_lecture_dump.json to get modules and classes ---
def build_course_outline_from_lecture_dump(path):
    with open(path, 'r', encoding='utf-8') as f:
        lectures = json.load(f)
    modules = defaultdict(list)
    for lec in lectures:
        module_name = lec.get('module_en', 'Unknown Module')
        class_title = lec.get('title_en', 'Untitled Lecture')
        modules[module_name].append(class_title)
    # Convert to list of dicts as expected by the rest of the script
    course_outline = [
        {'module_name': module, 'classes': classes}
        for module, classes in modules.items()
    ]
    return course_outline

course_outline = build_course_outline_from_lecture_dump(LECTURE_DUMP_PATH)

# --- Helper: Format module summary (titles + outlines) ---
def format_module_summary(module):
    lines = []
    lines.append(f"Module: {module['module_name']}")
    for i, cls in enumerate(module['classes'], 1):
        lines.append(f"  {i}. {cls}")
    return '\n'.join(lines)

# --- Helper: Format course summary (all modules and their classes) ---
def format_course_summary(course_outline):
    lines = ["Course Overview:"]
    for m, module in enumerate(course_outline, 1):
        lines.append(f"{m}. {module['module_name']}")
        for i, cls in enumerate(module['classes'], 1):
            lines.append(f"    {i}. {cls}")
    return '\n'.join(lines)

# --- Helper: Sanitize filename for Windows ---
def sanitize_filename(name):
    # Remove all problematic/special characters, keep only alphanumerics and underscores from spaces
    return re.sub(r'[^A-Za-z0-9_]', '', name)

# --- Agent 1: Module Introduction Script ---
def generate_intro_script(prev_module, curr_module, style_sample, model=MODEL, course_summary=None, course_title=None):
    curr_summary = format_module_summary(curr_module)
    if prev_module is None and course_summary is not None and course_title is not None:
        # First module: introduce the first module
        prompt = f"""
You are an expert lecturer. Write a natural, engaging, and conversational lecture script to introduce the first module.
- The course is titled: '{course_title}'.
- Introduce what will be learned in the first module (see below).
- Mimic the style, personality, and structure of the provided example.
- Use a wide range of discourse markers and conversational openers, but do not copy the example verbatim.
- Keep the length to around 200 words or 1800 characters .
- The script should be a single plaintext monologue, as if directly addressing students.
- Avoid overly formal language.
- Hint the module that it is the first module of the course, but do not introduce the course.
First Module Summary:{curr_summary}
Example Lecture Style:{style_sample}

"""
    else:
        prev_summary = format_module_summary(prev_module) if prev_module else "None (this is the first module)"
        prompt = f"""
You are an expert lecturer. Write a natural, engaging, and conversational lecture script to introduce a new module in an online course.
- The course is titled: '{course_title}'.
- Briefly summarize what was learned in the previous module (see below).
- Introduce what will be learned in the new module (see below).
- Mimic the style, personality, and structure of the provided example.
- Use a wide range of discourse markers and conversational openers, but do not copy the example verbatim.
- Keep the length to 200 words or 1200 characters maximum.
- The script should be a single plaintext monologue, as if directly addressing students.
- Avoid overly formal language.
- If this is the first module, say so and do not reference a previous module.
Course Title: {course_title}
Previous Module Summary:{prev_summary}
Current Module Summary:{curr_summary}
Example Lecture Style:{style_sample}
"""
    try:
        resp = openai.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"[ERROR: Could not generate introduction: {e}]"

# --- Agent 2: Module Conclusion Script ---
def generate_conclusion_script(curr_module, next_module, style_sample, model=MODEL, course_summary=None, course_title=None):
    curr_summary = format_module_summary(curr_module)
    if next_module is None and course_summary is not None and course_title is not None:
        # Last module: wrap up the module
        prompt = f"""
You are an expert lecturer. Write a natural, engaging, and conversational lecture script to conclude the last module. 
- There is a separate course conclusion script that will wrap up the entire course, so no need to conclude the course.
- Briefly summarize what was learned in the last module (see below).
- Mimic the style, personality, and structure of the provided example.
- Use a wide range of discourse markers and conversational openers, but do not copy the example verbatim.
- Keep the length to 200 words or 1800 characters maximum.
- The script should be a single plaintext monologue, as if directly addressing students.
- Avoid overly formal language.
Last Module Summary:{curr_summary}
Course Summary:
{course_summary}
Example Lecture Style:{style_sample}
"""
    else:
        next_summary = format_module_summary(next_module) if next_module else "None (this is the last module)"
        prompt = f"""
You are an expert lecturer. Write a natural, engaging, and conversational lecture script to conclude a module in an online course.
- The course is titled: '{course_title}'.
- Briefly summarize what was learned in the current module (see below).
- Preview what will be learned in the next module (see below).
- Mimic the style, personality, and structure of the provided example.
- Use a wide range of discourse markers and conversational openers, but do not copy the example verbatim.
- Keep the length to 200 words or 1200 characters maximum.
- The script should be a single plaintext monologue, as if directly addressing students.
- Avoid overly formal language.
- If this is the last module, say so and do not reference a next module.
Course Title: {course_title}
Current Module Summary:{curr_summary}
Next Module Summary:{next_summary}
Example Lecture Style:{style_sample}
"""
    try:
        resp = openai.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"[ERROR: Could not generate conclusion: {e}]"

# --- Agent 0: Course Introduction Script ---
def generate_course_intro_script(style_sample, model=MODEL, course_summary=None, course_title=None):
    prompt = f"""
You are an expert lecturer. Write a natural, engaging, and conversational script to introduce an online course.
- The course is titled: '{course_title}'.
- Briefly introduce the entire course (see below).
- Mimic the style, personality, and structure of the provided example.
- Use a wide range of discourse markers and conversational openers, but do not copy the example verbatim.
- Keep the length to around 300 words or 1800 characters.
- The script should be a single plaintext monologue, as if directly addressing students.
- Avoid overly formal language.
Course Title: {course_title}
Course Summary:{course_summary}
Example Lecture Style:{style_sample}
"""
    try:
        resp = openai.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"[ERROR: Could not generate course introduction: {e}]"

# --- Agent 3: Course Conclusion Script ---
def generate_course_conclusion_script(style_sample, model=MODEL, course_summary=None, course_title=None):
    prompt = f"""
You are an expert lecturer. Write a natural, engaging, and conversational script to conclude an online course.
- The course is titled: '{course_title}'.
- Reflect on and wrap up the entire course (see below).
- Mimic the style, personality, and structure of the provided example.
- Use a wide range of discourse markers and conversational openers, but do not copy the example verbatim.
- Keep the length to around 300 words or 1800 characters.
- The script should be a single plaintext monologue, as if directly addressing students.
- Avoid overly formal language.
Course Title: {course_title}
Course Summary:{course_summary}
Example Lecture Style:{style_sample}
"""
    try:
        resp = openai.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"[ERROR: Could not generate course conclusion: {e}]"

# --- Main Parallel Generation Function ---
def process_module_intro_concl(idx, module, prev_module, next_module, num_modules, course_summary, course_title):
    module_name = module['module_name']
    module_folder = module_folder_map[module_name]
    output_dir = os.path.join(OUTPUT_ROOT, module_folder)
    os.makedirs(output_dir, exist_ok=True)
    # Delete old intro/conclusion files if they exist
    intro_path = os.path.join(output_dir, '00_intro.txt')
    concl_path = os.path.join(output_dir, '99_conclusion.txt')
    for path in [intro_path, concl_path]:
        if os.path.exists(path):
            os.remove(path)
    # Generate intro and conclusion in parallel
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_intro = executor.submit(
            generate_intro_script, prev_module, module, style_sample, MODEL, course_summary, course_title
        )
        future_concl = executor.submit(
            generate_conclusion_script, module, next_module, style_sample, MODEL, course_summary, course_title
        )
        intro_script = future_intro.result()
        concl_script = future_concl.result()
    # Write intro and conclusion
    with open(intro_path, 'w', encoding='utf-8') as f:
        f.write(intro_script)
    with open(concl_path, 'w', encoding='utf-8') as f:
        f.write(concl_script)
    return (module_folder, '00_intro.txt', '99_conclusion.txt')

# --- Main Loop ---
intro_concl_summary = []
num_modules = len(course_outline)
course_summary = format_course_summary(course_outline)

# Build mapping from module_name to numbered folder by matching module number to actual folder in lectures/
module_folder_map = {}
lectures = build_course_outline_from_lecture_dump(LECTURE_DUMP_PATH) # Re-load lectures to get module names
lecture_folders = os.listdir(OUTPUT_ROOT)
for idx, module in enumerate(course_outline):
    module_name = module['module_name']
    found = False
    for lec in lectures:
        if lec.get('module_en', '').strip().upper() == module_name.strip().upper():
            for folder in lecture_folders:
                # Remove number prefix and underscore from folder name
                folder_core = folder.split('_', 1)[-1] if '_' in folder else folder
                # Sanitize both names for robust comparison
                sanitized_folder_core = sanitize_filename(folder_core).upper()
                sanitized_module_name = sanitize_filename(module_name.replace(' ', '_')).upper()
                if sanitized_folder_core == sanitized_module_name:
                    module_folder_map[module_name] = folder
                    found = True
                    break
                # Fallback: match by number prefix
                if folder[:2].isdigit() and int(folder[:2]) == idx+1:
                    module_folder_map[module_name] = folder
                    found = True
                    break
            if found:
                break
    else:
        # If not found, fallback to previous logic
        sanitized = sanitize_filename(module_name.replace(' ', '_'))
        module_folder = f"{idx+1:02d}_{sanitized}"
        module_folder_map[module_name] = module_folder

# Generate course introduction script
course_intro_path = os.path.join(OUTPUT_ROOT, '000_course_intro.txt')
course_intro_script = generate_course_intro_script(style_sample, MODEL, course_summary, course_title)
with open(course_intro_path, 'w', encoding='utf-8') as f:
    f.write(course_intro_script)

with concurrent.futures.ThreadPoolExecutor() as executor:
    futures = []
    for idx, module in enumerate(course_outline):
        prev_module = course_outline[idx-1] if idx > 0 else None
        next_module = course_outline[idx+1] if idx < num_modules-1 else None
        futures.append(executor.submit(
            process_module_intro_concl, idx, module, prev_module, next_module, num_modules, course_summary, course_title
        ))
    for future in tqdm(concurrent.futures.as_completed(futures), total=num_modules, desc='Module intros/conclusions'):
        result = future.result()
        intro_concl_summary.append(result)

# Generate course conclusion script
course_concl_path = os.path.join(OUTPUT_ROOT, 'zzz_course_conclusion.txt')
course_concl_script = generate_course_conclusion_script(style_sample, MODEL, course_summary, course_title)
with open(course_concl_path, 'w', encoding='utf-8') as f:
    f.write(course_concl_script)

# --- Print summary ---
print(f"\nGenerated course introduction script: {os.path.basename(course_intro_path)}")
print(f"Generated module introduction and conclusion scripts in '{OUTPUT_ROOT}':")
for module_folder, intro_file, concl_file in intro_concl_summary:
    print(f"- {module_folder}: {intro_file}, {concl_file}")
print(f"Generated course conclusion script: {os.path.basename(course_concl_path)}")

