"""학생별 성취도 채점 로직.

teacher_dashboard.py(교사용 전체 테이블)와 opinion_change.py(학생 본인
화면), utils.py(다운로드 이미지)에서 동일한 기준으로 점수를 계산해 쓰기
위해 공통 모듈로 분리했다.

루브릭 (요소별 3점 만점, 총 15점):
  - 참여도: debate 발언 횟수 (5회+=3, 2~4회=2, 1회 이하=1)
  - 발언 깊이: depth_level 평균 (3.0+=3, 2.0~2.9=2, 2.0 미만=1)
  - 사고 성장: pre/post_opinion + stance (변화/근거 강화=3, 유지=2, 참여 저조=1, 기록 없음=None)
  - 공감도: 받은 좋아요 수 (3개+=3, 1~2개=2, 0개=1)
  - 상호작용: 댓글 수 + 준 댓글 공감 수 (3회+=3, 1~2회=2, 0회=1)
"""

import pandas as pd

from db import (
    comment_likes_available,
    comments_available,
    depth_level_available,
    fetch_all_opinion_changes,
    fetch_comment_likes_for_room,
    fetch_comments_for_room,
    fetch_room_likes,
    likes_available,
    opinion_changes_available,
    stance_available,
)

STARS = {3: "⭐⭐⭐", 2: "⭐⭐", 1: "⭐"}

ACHIEVEMENT_LABELS = ["참여도", "발언 깊이", "사고 성장", "공감도", "상호작용"]


def score_participation(count: int) -> int:
    if count >= 5:
        return 3
    if count >= 2:
        return 2
    return 1


def score_depth(avg_depth) -> int:
    if avg_depth is None:
        return 1
    if avg_depth >= 3.0:
        return 3
    if avg_depth >= 2.0:
        return 2
    return 1


def _clean_text(val) -> str:
    """pandas DataFrame에서 값이 없을 때 나오는 NaN(float)을 빈 문자열로 정리한다."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def score_growth(pre_opinion: str, post_opinion: str, initial_stance: str, final_stance: str):
    """사고 성장 점수. opinion_changes 기록 자체가 없으면 None('-' 표시)을 반환한다."""
    pre_opinion = _clean_text(pre_opinion)
    if not pre_opinion:
        return None
    post_opinion = _clean_text(post_opinion)
    if not post_opinion:
        return 1  # 토론 전 생각만 있고 참여가 저조함
    initial_stance = _clean_text(initial_stance)
    final_stance = _clean_text(final_stance)
    stance_changed = bool(initial_stance) and bool(final_stance) and initial_stance != final_stance
    reasoning_deepened = len(post_opinion) > len(pre_opinion)
    if stance_changed or reasoning_deepened:
        return 3
    return 2


def score_empathy(likes_received: int) -> int:
    if likes_received >= 3:
        return 3
    if likes_received >= 1:
        return 2
    return 1


def score_interaction(comments_given: int, comment_likes_given: int) -> int:
    total = comments_given + comment_likes_given
    if total >= 3:
        return 3
    if total >= 1:
        return 2
    return 1


def compute_room_achievements(supabase, room_name: str, df_all: pd.DataFrame) -> dict:
    """방 전체 학생의 성취도 점수를 계산해 {student_name: {...}} 딕셔너리로 반환한다.

    각 값은 {"참여도": int|None, "발언 깊이": int|None, "사고 성장": int|None,
    "공감도": int|None, "상호작용": int|None, "총점": int, "만점": int} 형태.
    """
    if df_all.empty:
        return {}

    student_rows = df_all[df_all.get("author_role", "학생") == "학생"] if "author_role" in df_all.columns else df_all
    if student_rows.empty:
        return {}

    students = sorted(student_rows["student_name"].dropna().unique().tolist())

    # 공감(좋아요) 받은 수: opinion_id → 발언 작성자 매핑 후 집계
    owner_by_opinion_id = dict(zip(student_rows["id"], student_rows["student_name"])) if "id" in student_rows.columns else {}
    likes_received_by_student = {}
    if likes_available():
        for like_row in fetch_room_likes(supabase, room_name):
            owner = owner_by_opinion_id.get(like_row.get("opinion_id"))
            if owner:
                likes_received_by_student[owner] = likes_received_by_student.get(owner, 0) + 1

    # 상호작용: 댓글 작성 수 + 준 댓글 공감 수
    comments_given_by_student = {}
    if comments_available():
        for c in fetch_comments_for_room(supabase, room_name):
            name = c.get("student_name")
            if name:
                comments_given_by_student[name] = comments_given_by_student.get(name, 0) + 1
    comment_likes_given_by_student = {}
    if comment_likes_available():
        for cl in fetch_comment_likes_for_room(supabase, room_name):
            name = cl.get("student_name")
            if name:
                comment_likes_given_by_student[name] = comment_likes_given_by_student.get(name, 0) + 1

    # 발언 깊이 평균
    avg_depth_by_student = {}
    if depth_level_available() and "depth_level" in student_rows.columns:
        depth_df = student_rows.copy()
        depth_df["depth_level"] = pd.to_numeric(depth_df["depth_level"], errors="coerce")
        depth_df = depth_df.dropna(subset=["depth_level"])
        if not depth_df.empty:
            avg_depth_by_student = depth_df.groupby("student_name")["depth_level"].mean().to_dict()

    # 사고 성장: opinion_changes 기록
    growth_by_student = {}
    if opinion_changes_available():
        df_oc = fetch_all_opinion_changes(supabase, room_name)
        for _, oc_row in df_oc.iterrows():
            growth_by_student[oc_row["student_name"]] = score_growth(
                oc_row.get("pre_opinion"), oc_row.get("post_opinion"),
                oc_row.get("initial_stance") if stance_available() else None,
                oc_row.get("final_stance") if stance_available() else None,
            )

    participation_counts = student_rows["student_name"].value_counts().to_dict()

    result = {}
    for name in students:
        p_score = score_participation(participation_counts.get(name, 0))
        d_score = score_depth(avg_depth_by_student.get(name)) if depth_level_available() else None
        g_score = growth_by_student.get(name) if opinion_changes_available() else None
        e_score = score_empathy(likes_received_by_student.get(name, 0)) if likes_available() else None
        i_score = (
            score_interaction(comments_given_by_student.get(name, 0), comment_likes_given_by_student.get(name, 0))
            if (comments_available() or comment_likes_available()) else None
        )
        scores = [s for s in (p_score, d_score, g_score, e_score, i_score) if s is not None]
        result[name] = {
            "참여도": p_score,
            "발언 깊이": d_score,
            "사고 성장": g_score,
            "공감도": e_score,
            "상호작용": i_score,
            "총점": sum(scores),
            "만점": len(scores) * 3,
        }
    return result


def format_achievement_lines(achievement: dict) -> list:
    """{"참여도": 3, ...} 형태의 점수 딕셔너리를 사람이 읽는 텍스트 줄 목록으로 변환."""
    lines = []
    for label in ACHIEVEMENT_LABELS:
        score = achievement.get(label)
        stars = STARS.get(score, "-") if score is not None else "-"
        lines.append(f"{label}: {stars}" + (f" ({score}점)" if score is not None else ""))
    lines.append(f"총점: {achievement.get('총점', 0)}/{achievement.get('만점', 0)}")
    return lines
