import re
with open('app/services/prompts_service.py', 'r') as f:
    content = f.read()

# Pattern 1
pattern1 = r'\{\{\n  "removed_clips": \[\](?:.|\n)*?"reasoning": "Explain how the sequence satisfies the USER EDITING DIRECTIVES\."\n\}\}'
content = re.sub(pattern1, '{json_schema}', content)

# Pattern 2
pattern2 = r'\{\{\n  "removed_clips": \[(?:.|\n)*?"reasoning": "Explain why the hook works(?:.|\n)*?"\n\}\}'
content = re.sub(pattern2, '{json_schema}', content)

# Pattern 3 (The very last one in the file if any)
pattern3 = r'\{\{\n  "removed_clips": \[(?:.|\n)*?"reasoning": "Explain why this sequence is the most emotionally engaging(?:.|\n)*?"\n\}\}'
content = re.sub(pattern3, '{json_schema}', content)

with open('app/services/prompts_service.py', 'w') as f:
    f.write(content)
