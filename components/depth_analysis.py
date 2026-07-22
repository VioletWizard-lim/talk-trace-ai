"""발언 깊이 분석 컴포넌트 — 교사 대시보드 전용."""
import logging

import pandas as pd
import plotly.express as px
import streamlit as st

from db import bulk_update_depth_levels, depth_level_available, fetch_opinions_for_depth
from env import get_secret
from config import AI_MODEL_NAME_PRO, UI_FONT_FAMILY
from services.ai import build_depth_analysis_prompt, generate_ai_response, parse_depth_levels

logger = logging.getLogger("talk_trace_ai")

_DEPTH_LABELS = {
    1: "1단계: 단순의견",
    2: "2단계: 근거제시",
    3: "3단계: 반박/심화질문",
    4: "4단계: 통합/종합",
}
_DEPTH_COLORS = {
    "1단계: 단순의견":     "#aec6e8",
    "2단계: 근거제시":     "#4a90d9",
    "3단계: 반박/심화질문": "#f5a623",
    "4단계: 통합/종합":    "#27ae60",
}
_BATCH_SIZE = 30  # 한 번에 AI에 보낼 최대 발언 수


def _classify_in_batches(opinions_to_classify: list, api_key: str) -> dict:
    """opinions_to_classify: list of (id, content). Returns {id: depth_level}."""
    all_results = {}
    for i in range(0, len(opinions_to_classify), _BATCH_SIZE):
        batch = opinions_to_classify[i: i + _BATCH_SIZE]
        prompt = build_depth_analysis_prompt(batch)
        response = generate_ai_response(
            prompt=prompt,
            model_name=AI_MODEL_NAME_PRO,
            api_key=api_key,
            log_message="depth_analysis_batch",
            fallback="",
        )
        if response:
            batch_ids = {oid for oid, _ in batch}
            parsed = parse_depth_levels(response, batch_ids)
            all_results.update(parsed)
        else:
            # AI 실패 시 배치 전체 1단계로 기본값
            for oid, _ in batch:
                all_results[oid] = 1
    return all_results


def render_depth_analysis_section(supabase, room_name: str, act_type: str, is_ended: bool = True) -> None:
    """교사 대시보드에 삽입되는 발언 깊이 분석 섹션."""
    if not depth_level_available():
        return  # depth_level 컬럼 없으면 섹션 비활성화

    st.divider()
    st.subheader("📈 발언 깊이 분석")
    st.caption(
        "AI가 각 발언을 1~4단계로 분류합니다. "
        "1=단순의견 → 2=근거제시 → 3=반박/심화질문 → 4=통합/종합"
    )

    if not is_ended:
        st.info(f"💡 {act_type} 종료 후 분석을 실행할 수 있습니다. 위의 **{act_type} 종료** 버튼을 눌러 진행을 마쳐주세요.")
        return

    opinions = fetch_opinions_for_depth(supabase, room_name)
    if not opinions:
        st.info(f"아직 {act_type} 발언이 없습니다.")
        return

    df = pd.DataFrame(opinions)

    # 미분류(depth_level이 null) 개수
    unclassified = df[df["depth_level"].isna()]
    unclassified_count = len(unclassified)

    col_btn, col_status = st.columns([3, 5])
    with col_btn:
        btn_label = (
            f"🔍 분석 실행 ({unclassified_count}개 미분류)"
            if unclassified_count > 0
            else "🔄 재분석"
        )
        run_analysis = st.button(btn_label, use_container_width=True, type="primary")

    with col_status:
        if unclassified_count == 0:
            st.success("✅ 모든 발언이 분류되었습니다.")
        else:
            st.warning(f"⚠️ {unclassified_count}개 발언이 아직 분류되지 않았습니다.")

    if run_analysis:
        api_key = get_secret("GEMINI_API_KEY", "")
        if not api_key:
            st.error("❌ GEMINI_API_KEY가 설정되어 있지 않습니다.")
            return

        # 재분석 시 전체 재분류, 처음 실행 시 미분류만
        to_classify = (
            list(zip(df["id"].tolist(), df["content"].tolist()))
            if unclassified_count == 0  # 재분석
            else list(zip(unclassified["id"].tolist(), unclassified["content"].tolist()))
        )

        with st.spinner(f"🤖 AI가 {len(to_classify)}개 발언을 분석 중입니다..."):
            results = _classify_in_batches(to_classify, api_key)

        updates = [{"id": oid, "depth_level": lvl} for oid, lvl in results.items()]
        success = bulk_update_depth_levels(supabase, updates)
        if success:
            st.toast(f"✅ {len(updates)}개 발언 분류 완료!", icon="📈")
            st.rerun()
        else:
            st.error("일부 발언 저장에 실패했습니다. 다시 시도해 주세요.")

    # 분류된 데이터가 있으면 차트 표시
    classified_df = df[df["depth_level"].notna()].copy()
    if classified_df.empty:
        return

    classified_df["depth_level"] = classified_df["depth_level"].astype(int)
    classified_df["depth_label"] = classified_df["depth_level"].map(_DEPTH_LABELS)

    col_chart1, col_chart2 = st.columns(2)

    # ── 차트 1: 발언 깊이 분포 막대 그래프 ──
    with col_chart1:
        st.caption("발언 깊이 분포")
        count_df = (
            classified_df["depth_label"]
            .value_counts()
            .reindex(list(_DEPTH_LABELS.values()), fill_value=0)
            .reset_index()
        )
        count_df.columns = ["깊이 단계", "발언 수"]
        fig_bar = px.bar(
            count_df,
            x="깊이 단계",
            y="발언 수",
            color="깊이 단계",
            color_discrete_map=_DEPTH_COLORS,
            text="발언 수",
        )
        fig_bar.update_layout(
            showlegend=False,
            dragmode=False,
            font={"family": UI_FONT_FAMILY},
            margin=dict(t=20, b=10),
            xaxis_title="",
        )
        fig_bar.update_traces(textposition="outside")
        st.plotly_chart(fig_bar, use_container_width=True, config={"displayModeBar": False})

    # ── 차트 2: 시간순 발언 깊이 변화 산점도 ──
    with col_chart2:
        st.caption("시간 흐름에 따른 발언 깊이")
        time_df = classified_df.sort_values("id").reset_index(drop=True)
        time_df["순서"] = range(1, len(time_df) + 1)
        fig_scatter = px.scatter(
            time_df,
            x="순서",
            y="depth_level",
            color="student_name",
            hover_data={"content": True, "student_name": True, "depth_label": True, "순서": False},
            labels={"depth_level": "깊이 단계", "student_name": "학생"},
        )
        fig_scatter.update_layout(
            yaxis=dict(tickvals=[1, 2, 3, 4], ticktext=list(_DEPTH_LABELS.values()), range=[0.5, 4.5]),
            dragmode=False,
            font={"family": UI_FONT_FAMILY},
            margin=dict(t=50, b=10),
            xaxis_title="발언 순서",
            legend_title="학생 (클릭: 개별 토글)",
            updatemenus=[dict(
                type="buttons",
                direction="left",
                x=0, y=1.18,
                buttons=[
                    dict(label="✅ 전체 선택", method="restyle", args=["visible", True]),
                    dict(label="⬜ 전체 해제", method="restyle", args=["visible", "legendonly"]),
                ],
                bgcolor="#f0f2f6",
                bordercolor="#ccc",
                font=dict(size=12),
            )],
        )
        st.plotly_chart(fig_scatter, use_container_width=True, config={"displayModeBar": False})

    # ── 학생별 평균 깊이 테이블 ──
    st.caption("학생별 평균 발언 깊이")
    student_summary = (
        classified_df.groupby("student_name")["depth_level"]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"student_name": "학생", "mean": "평균 깊이", "count": "발언 수"})
        .sort_values("평균 깊이", ascending=False)
    )
    student_summary["평균 깊이"] = student_summary["평균 깊이"].round(2)
    st.dataframe(
        student_summary,
        use_container_width=True,
        hide_index=True,
        column_config={
            "평균 깊이": st.column_config.ProgressColumn(
                "평균 깊이",
                min_value=1,
                max_value=4,
                format="%.2f",
            ),
        },
    )
