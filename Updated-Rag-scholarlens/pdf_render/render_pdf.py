import re
import os
import pandas as pd
from markdown import markdown
from weasyprint import HTML

# 1. Parse qa_content.md
with open('qa_content.md', encoding='utf-8') as f:
    content = f.read()

# Split the content into questions
qa_pattern = re.compile(
    r'(\d+)\.\s+\*\*Question:\*\*\s*(.*?)\n+'
    r'\s*\*\*Answer:\*\*\s*(.*?)\n+'
    r'\s*\*\*Subject:\*\*\s*(.*?)\n',
    re.DOTALL
)

qas = []
for match in qa_pattern.finditer(content):
    q_no, question, answer, subject = match.groups()
    # Clean up whitespace
    question = question.strip()
    answer = answer.strip()
    subject = subject.strip()
    qas.append({'question_text': question, 'answer_text': answer, 'subject': subject})

if len(qas) != 10:
    raise Exception(f"Expected 10 Q&A pairs, found {len(qas)}.")

# 2. Generate Markdown for PDF
pdf_md_parts = []
for i, qa in enumerate(qas, 1):
    pdf_md_parts.append(
        f"## {i}. Question\n\n"
        f"**{qa['question_text']}**\n\n"
        f"### Answer\n\n"
        f"{qa['answer_text']}\n\n"
        f"*Subject: {qa['subject']}*\n"
        f"---"
    )
pdf_md = "\n\n".join(pdf_md_parts)

# Add a title
pdf_md = "# Indian Business Law: Model Q&A Bank\n\n" + pdf_md

# 3. Markdown to HTML
html = markdown(pdf_md, output_format='html5')

# Minimal styling for print
STYLES = """
<style>
body {
  font-family: "Times New Roman", Times, serif;
  margin: 2.5em 1.5em;
  color: #222;
}
h1 { text-align:center; font-size:2.5em; margin-bottom:0.3em }
h2 { color: #183870; margin-top:1.2em; }
h3 { color: #234; font-size: 1.15em; }
hr, .hr { border: 0; border-top: 1px solid #bbb; margin: 2em 0;}
.question, .answer { margin-bottom: 1.2em; }
.subject { font-size: 1em; color: #606060; font-style: italic; }
</style>
"""

# Combine CSS and HTML
html_full = f"<!DOCTYPE html><html><head>{STYLES}</head><body>{html}</body></html>"

# 4. Write PDF
os.makedirs('out', exist_ok=True)
pdf_path = os.path.join('out', 'qa.pdf')
HTML(string=html_full, base_url='.').write_pdf(pdf_path)

# 5. Write CSV
csv_path = 'qa.csv'
df = pd.DataFrame(qas)
df.to_csv(csv_path, index=False, columns=["question_text", "answer_text", "subject"])

# 6. Confirm output
assert os.path.exists(pdf_path), "PDF not generated"
assert os.path.exists(csv_path), "CSV not generated"
print(f"Success! Generated PDF: {pdf_path}\nGenerated CSV: {csv_path}")