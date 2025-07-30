import subprocess
import sys

scripts = [
    ("generate_lectures.py", "Generating all lectures for all modules..."),
    ("generate_module_intro_conclusion.py", "Generating module intros and conclusions...")
]

for script, message in scripts:
    print(f"\n[main.py] {message}")
    try:
        result = subprocess.run([sys.executable, script], check=True)
    except subprocess.CalledProcessError as e:
        print(f"[main.py] Error running {script}: {e}")
        sys.exit(1)

print("\n[main.py] All lectures, intros, and conclusions generated successfully.") 