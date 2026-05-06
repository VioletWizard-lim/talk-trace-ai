def build_hint_prompt(act_type, current_topic, context):
    return (
        f"당신은 고등학교 {act_type} 조력자입니다. "
        f"'{current_topic}' 주제로 {act_type} 중입니다. "
        "학생들의 균형을 맞추거나 더 깊은 생각을 유도할 수 있는 "
        "예리한 질문을 1문장만 제안하세요. "
        "번호 매기기나 번잡한 서론 없이 질문 자체만 출력하세요."
        f"\n최근 대화: {context}"
    )


def build_record_prompt(act_type, current_topic, selected_student, debate_history):
    return (
        f"당신은 정보 교사입니다. "
        f"'{current_topic}' 주제 {act_type}에 참여한 "
        f"'{selected_student}' 학생의 활동 기록입니다. "
        "이를 바탕으로 생활기록부 교과세특 초안을 약 300자 내외로 작성하세요. "
        f"교육적 성장을 강조하세요.\n\n[활동 기록]\n{debate_history}"
    )
