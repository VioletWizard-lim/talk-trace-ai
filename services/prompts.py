def build_hint_prompt(act_type, current_topic, context):
    return (
        f"당신은 고등학교 {act_type} 조력자입니다. "
        f"'{current_topic}' 주제로 {act_type} 중입니다. "
        "학생들의 균형을 맞추거나 더 깊은 생각을 유도할 수 있는 "
        "예리한 질문을 1문장만 제안하세요. "
        "번호 매기기나 번잡한 서론 없이 질문 자체만 출력하세요."
        f"\n최근 대화: {context}"
    )


def build_summary_prompt(act_type, current_topic, full_history):
    return (
        f"'{current_topic}' 주제의 고등학교 {act_type} 기록입니다.\n\n"
        "[출력 형식 - 반드시 그대로]\n"
        "핵심요약 1: ...\n핵심요약 2: ...\n핵심요약 3: ...\n베스트 학생: ...\n선정 이유: ...\n\n"
        "[엄격한 규칙]\n"
        "- 핵심요약 1,2,3과 베스트 학생, 선정이유를 줄바꿈을 하여 보기 편하게 합니다.\n"
        "- 5~10줄로 출력합니다.\n- 제목/헤더(#,##,###), 소제목을 절대 쓰지 않습니다.\n"
        "- 불필요한 서론/결론 없이 바로 결과만 출력합니다.\n\n"
        f"기록:\n{full_history}"
    )


def build_record_prompt(act_type, current_topic, selected_student, debate_history):
    return (
        f"당신은 정보 교사입니다. "
        f"'{current_topic}' 주제 {act_type}에 참여한 "
        f"'{selected_student}' 학생의 활동 기록입니다. "
        "이를 바탕으로 생활기록부 교과세특 초안을 약 300자 내외로 작성하세요. "
        f"교육적 성장을 강조하세요.\n\n[활동 기록]\n{debate_history}"
    )
