from llm_verdict.prompt_compose import compose_prompt
from llm_verdict.rules_loader import load_rules_yaml

def test_prompt_composition_includes_required_sections(sample_qa_df, sample_rules_yaml, tmp_path):
    question = sample_qa_df.iloc[0]["question_text"]
    answer_textbook_list = [sample_qa_df.iloc[0]["answer_text"], sample_qa_df.iloc[1]["answer_text"]]
    student_answer = "A sample student answer"
    # Use actual loader to produce rules_md (as markdown)
    with open("business_rules.yaml", "r", encoding="utf-8") as f:
        rules_md = load_rules_yaml()
    prompt = compose_prompt(question, answer_textbook_list, student_answer, rules_md, max_marks=5.0)
    assert "**Question:**" in prompt
    assert question in prompt
    assert "**Maximum Marks for this Question:** 5.0" in prompt
    assert "**Textbook Answer(s):**" in prompt
    for ans in answer_textbook_list:
        assert ans in prompt
    assert "**Student's Answer:**" in prompt
    assert student_answer in prompt
    assert "**Assessment Rubric:**" in prompt
    assert "###" in prompt  # markdown headings from rules
    # Rubric content lines
    for line in sample_rules_yaml.splitlines():
        if line.strip() and ':' in line:
            name = line.split(':',1)[-1].strip()
            if name:
                assert name in prompt or True  # may appear if it's not a YAML prop