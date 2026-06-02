"""
마케팅 성과 대시보드 (라이트 테마)
채널 데이터 + 앱스플라이어 자동 로드 → EDA + 시각화
"""
from __future__ import annotations

import os
from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from loader import JOIN_KEYS, compute_kpis, load_and_join
from analytics import (
    budget_pacing, detect_anomalies, get_prev_day,
    get_rolling_avg, compute_channel_kpis, pacing_anomalies,
    _channel_rolling_avgs,
)

# ─── 숫자 컬럼 dtype 보장 (Streamlit column_config 호환) ──────────────────
_INT_COLS   = ["노출", "클릭", "비용", "회원가입", "구매", "구매매출",
               "AF_클릭", "AF_회원가입", "AF_구매", "AF_구매매출"]

def _ensure_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """표시 직전 숫자 컬럼을 표준 int64/float64로 강제 변환."""
    df = df.copy()
    for col in _INT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")
    return df

# ─── 페이지 설정 ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="마케팅 성과 대시보드",
    page_icon=":material/analytics:",
    layout="wide",
)

_BASE      = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CH = os.path.join(_BASE, "data", "channel")
DEFAULT_AF = os.path.join(_BASE, "data", "appsflyer")

CHART_H = 300   # 차트 기본 높이

# ─── 사이드바 ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## :material/folder_open: 데이터 폴더")
    channel_folder   = st.text_input("채널 데이터 폴더",  value=DEFAULT_CH)
    appsflyer_folder = st.text_input("앱스플라이어 폴더", value=DEFAULT_AF)

    if st.button(":material/refresh: 새로고침", type="secondary"):
        st.cache_data.clear()
        st.rerun()
    st.caption("5분마다 자동 갱신됩니다.")
    st.divider()
    st.markdown("## :material/filter_alt: 필터")

# ─── 데이터 로드 ──────────────────────────────────────────────────────────
df_raw = load_and_join(channel_folder, appsflyer_folder)

if df_raw.empty:
    import glob as _glob
    ch_exists  = os.path.isdir(channel_folder)
    af_exists  = os.path.isdir(appsflyer_folder)
    ch_files   = _glob.glob(os.path.join(channel_folder,    "*.csv")) if ch_exists else []
    af_files   = _glob.glob(os.path.join(appsflyer_folder, "*.csv")) if af_exists else []

    st.warning("데이터가 없습니다. 폴더 경로를 확인해 주세요.")
    with st.expander("🔍 경로 진단", expanded=True):
        st.write(f"**채널 폴더 존재:** `{ch_exists}` → `{channel_folder}`")
        st.write(f"**AF 폴더 존재:** `{af_exists}` → `{appsflyer_folder}`")
        st.write(f"**채널 CSV:** {ch_files}")
        st.write(f"**AF CSV:** {af_files}")
        st.write(f"**앱 루트:** `{_BASE}`")
        st.write(f"**루트 파일 목록:** `{os.listdir(_BASE) if os.path.isdir(_BASE) else '없음'}`")
    st.stop()

# ─── 사이드바 필터 ────────────────────────────────────────────────────────
with st.sidebar:
    # 날짜
    if "일" in df_raw.columns:
        min_d = df_raw["일"].min().date()
        max_d = df_raw["일"].max().date()
        date_range = st.date_input("날짜 범위",
            value=(min_d, max_d), min_value=min_d, max_value=max_d)
    else:
        date_range = None

    # 채널
    if "채널" in df_raw.columns:
        ch_opts   = sorted(df_raw["채널"].dropna().unique())
        sel_ch    = st.multiselect("채널", ch_opts, default=list(ch_opts))
    else:
        sel_ch = []

    # 채널분류
    if "채널분류" in df_raw.columns:
        cl_opts   = sorted(df_raw["채널분류"].dropna().unique())
        sel_cl    = st.multiselect("채널분류", cl_opts, default=list(cl_opts))
    else:
        sel_cl = []

    # 캠페인목적
    if "캠페인목적" in df_raw.columns:
        cp_opts   = sorted(df_raw["캠페인목적"].dropna().unique())
        sel_cp    = st.multiselect("캠페인목적", cp_opts, default=list(cp_opts))
    else:
        sel_cp = []

# ─── 필터 적용 ────────────────────────────────────────────────────────────
df = df_raw.copy()

if date_range and len(date_range) == 2 and "일" in df.columns:
    df = df[(df["일"] >= pd.Timestamp(date_range[0])) &
            (df["일"] <= pd.Timestamp(date_range[1]))]
if sel_ch and "채널"     in df.columns: df = df[df["채널"].isin(sel_ch)]
if sel_cl and "채널분류" in df.columns: df = df[df["채널분류"].isin(sel_cl)]
if sel_cp and "캠페인목적" in df.columns: df = df[df["캠페인목적"].isin(sel_cp)]

kpi = compute_kpis(df)

# ─── 헤더 ────────────────────────────────────────────────────────────────
with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    st.markdown("# :material/analytics: 마케팅 성과 대시보드")
    if st.button(":material/restart_alt: 초기화", type="tertiary"):
        st.session_state.clear()
        st.cache_data.clear()
        st.rerun()

# ─── KPI 카드 (채널) ─────────────────────────────────────────────────────
st.markdown("##### 채널 KPI")
with st.container(horizontal=True):
    st.metric(":material/visibility: 노출",      f"{kpi['노출']:,.0f}",      border=True)
    st.metric(":material/ads_click: 클릭",       f"{kpi['클릭']:,.0f}",      border=True)
    st.metric(":material/payments: 비용",        f"₩{kpi['비용']:,.0f}",     border=True)
    st.metric(":material/person_add: 회원가입",  f"{kpi['회원가입']:,.0f}",   border=True)
    st.metric(":material/shopping_cart: 구매",   f"{kpi['구매']:,.0f}",      border=True)
    st.metric(":material/currency_won: 매출",    f"₩{kpi['구매매출']:,.0f}", border=True)

with st.container(horizontal=True):
    st.metric(":material/percent: CTR",          f"{kpi['CTR']:.2f}%",       border=True)
    st.metric(":material/price_check: CPC",      f"₩{kpi['CPC']:,.0f}",      border=True)
    st.metric(":material/savings: CPA",          f"₩{kpi['CPA']:,.0f}",      border=True)
    st.metric(":material/trending_up: ROAS",     f"{kpi['ROAS']:.1f}%",      border=True)

# AF KPI
if kpi.get("has_af"):
    st.markdown("##### 앱스플라이어 KPI")
    with st.container(horizontal=True):
        st.metric("AF 회원가입", f"{kpi['af_가입']:,.0f}", border=True)
        st.metric("AF 구매",     f"{kpi['af_구매']:,.0f}", border=True)
        st.metric("AF 매출",     f"₩{kpi['af_매출']:,.0f}", border=True)
        if kpi["af_구매"] and kpi["af_구매"] > 0 and kpi["비용"] > 0:
            st.metric("AF ROAS", f"{kpi['af_매출'] / kpi['비용'] * 100:.1f}%", border=True)
            st.metric("AF CPA",  f"₩{kpi['비용'] / kpi['af_구매']:,.0f}", border=True)

st.divider()

# ─── 탭 ──────────────────────────────────────────────────────────────────
tab_brief, tab_trend, tab_ch, tab_camp, tab_creative, tab_raw = st.tabs([
    ":material/today: 오늘 브리핑",
    ":material/show_chart: 날짜 추이",
    ":material/pie_chart: 채널 분석",
    ":material/flag: 캠페인 분석",
    ":material/grid_view: 소재 분석",
    ":material/table: 원본 데이터",
], on_change="rerun")


# ── 오늘 브리핑 ───────────────────────────────────────────────────────────
if tab_brief.open:
    with tab_brief:
        prev_day_df = get_prev_day(df)
        roll_df     = get_rolling_avg(df, days=7)
        latest_date = prev_day_df["일"].max() if not prev_day_df.empty else None

        # 이상 감지 + 페이싱 이상 통합
        anomalies   = detect_anomalies(df)
        pacing_list = budget_pacing(df)
        pac_issues  = pacing_anomalies(pacing_list)
        all_issues  = anomalies + pac_issues
        danger_cnt  = sum(1 for a in all_issues if a["level"] == "danger")
        warn_cnt    = sum(1 for a in all_issues if a["level"] == "warning")

        # ── 알람 배너 ──────────────────────────────────────────────────────
        if not all_issues:
            st.success("✅ 이상 감지 없음 — 전체 채널 정상 운영 중", icon=None)
        elif danger_cnt > 0:
            st.error(
                f"🚨 **즉시 확인 필요 {danger_cnt}건** "
                f"{'· ⚠ 모니터링 ' + str(warn_cnt) + '건' if warn_cnt else ''}",
                icon=None,
            )
        else:
            st.warning(f"⚠ 모니터링 필요 {warn_cnt}건", icon=None)

        st.caption(
            f"기준일: **{latest_date.strftime('%Y-%m-%d') if latest_date is not None else '-'}**"
            "　|　직전 7일 평균 대비 비교"
        )

        # ── 전일 KPI 요약 ──────────────────────────────────────────────────
        if not prev_day_df.empty:
            from analytics import _channel_rolling_avgs
            kpi_now = compute_channel_kpis(prev_day_df)

            # 7일 평균 — 데이터 부족해도 항상 안전하게 초기화
            avgs = _channel_rolling_avgs(roll_df)
            avg_비용 = avgs["avg_비용"]
            avg_클릭 = avgs["avg_클릭"]
            avg_구매 = avgs["avg_구매"]
            avg_CPA  = avgs["avg_CPA"]
            avg_ROAS = avgs["avg_ROAS"]

            def _delta(now: float, prev: float):
                if prev and prev > 0:
                    return f"{(now - prev) / prev * 100:+.1f}%"
                return None

            has_baseline = avg_비용 > 0  # 7일 기준 있을 때만 delta 표시

            with st.container(border=True):
                st.markdown("**📊 전일 성과 요약**"
                            + ("  <span style='font-size:11px;color:#aaa'>  · 괄호 % = 7일평균 대비</span>" if has_baseline else
                               "  <span style='font-size:11px;color:#aaa'>  · 7일치 데이터 쌓이면 비교값 표시</span>"),
                            unsafe_allow_html=True)
                with st.container(horizontal=True):
                    st.metric("비용",  f"₩{kpi_now['비용']:,.0f}",
                              delta=_delta(kpi_now["비용"], avg_비용) if has_baseline else None,
                              border=True)
                    st.metric("ROAS",  f"{kpi_now['ROAS']:.1f}%",
                              delta=_delta(kpi_now["ROAS"], avg_ROAS) if has_baseline else None,
                              border=True)
                    st.metric("구매",  f"{kpi_now['구매']:,.0f}건",
                              delta=_delta(kpi_now["구매"], avg_구매) if has_baseline else None,
                              border=True)
                    st.metric("CPA",   f"₩{kpi_now['CPA']:,.0f}",
                              delta=_delta(kpi_now["CPA"], avg_CPA) if has_baseline else None,
                              border=True, delta_color="inverse")
                    st.metric("CTR",   f"{kpi_now['CTR']:.2f}%",
                              border=True)
                    st.metric("클릭",  f"{kpi_now['클릭']:,.0f}",
                              delta=_delta(kpi_now["클릭"], avg_클릭) if has_baseline else None,
                              border=True)

        # ── 2열: 예산 페이싱 | 이상감지 & 액션 ───────────────────────────
        col_pacing, col_alarm = st.columns([1, 1.2])

        # 예산 페이싱
        with col_pacing:
            with st.container(border=True, height=280):
                st.markdown("**💰 채널별 예산 페이싱**")
                st.caption("전일 비용 ÷ 직전 7일 평균 일비용")

                if not pacing_list:
                    st.info("데이터 부족 (7일 이상 필요)")
                else:
                    for p in pacing_list:
                        pct = p["pacing_pct"] or 0
                        bar_color = (
                            "#e03131" if p["status"] == "over"
                            else "#fab005" if p["status"] == "low"
                            else "#4263eb"
                        )
                        label_extra = (
                            " 🔴 과집행" if p["status"] == "over"
                            else " 🟡 저조"  if p["status"] == "low"
                            else ""
                        )
                        st.markdown(
                            f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:8px'>"
                            f"<span style='width:48px;font-size:12px;font-weight:600'>{p['채널']}</span>"
                            f"<div style='flex:1;background:#eee;border-radius:4px;height:14px'>"
                            f"<div style='width:{min(pct,100):.0f}%;background:{bar_color};height:100%;border-radius:4px'></div></div>"
                            f"<span style='font-size:11px;white-space:nowrap'>{pct:.0f}%{label_extra}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                        st.caption(
                            f"　　전일 ₩{p['today_cost']:,.0f}  ·  7일평균 ₩{p['avg_cost']:,.0f}",
                        )

        # 이상감지 & 액션
        with col_alarm:
            with st.container(border=True, height=280):
                st.markdown("**🚨 이상감지 & 액션 추천**")

                if not all_issues:
                    st.success("모든 채널 정상")
                else:
                    for issue in all_issues:
                        icon  = "🔴" if issue["level"] == "danger" else "🟡" if issue["level"] == "warning" else "🔵"
                        color = "#fff0f0" if issue["level"] == "danger" else "#fffbe6" if issue["level"] == "warning" else "#e8f4fd"
                        border_color = "#ffa8a8" if issue["level"] == "danger" else "#ffe066" if issue["level"] == "warning" else "#74c0fc"
                        st.markdown(
                            f"<div style='background:{color};border:1px solid {border_color};"
                            f"border-left:3px solid {border_color};border-radius:6px;"
                            f"padding:7px 10px;margin-bottom:6px;font-size:12px'>"
                            f"<div style='font-weight:700'>{icon} {issue['message']}</div>"
                            f"<div style='color:#555;font-size:11px;margin:2px 0'>{issue['detail']}</div>"
                            f"<div style='color:#333;font-size:11px'>→ {issue['action']}</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )


# ── 날짜 추이 ─────────────────────────────────────────────────────────────
if tab_trend.open:
    with tab_trend:
        if "일" not in df.columns or df.empty:
            st.info("데이터 없음")
        else:
            metric_opts = [c for c in ["비용","노출","클릭","회원가입","구매","구매매출"] if c in df.columns]
            sel_m = st.segmented_control("지표", metric_opts, default=metric_opts[0], key="trend_m")

            if sel_m:
                daily = df.groupby("일")[[sel_m]].sum().reset_index()
                daily["MA7"] = daily[sel_m].rolling(7, min_periods=1).mean()

                # 라이트 테마에서 Altair 기본 색상 사용
                area = (
                    alt.Chart(daily)
                    .mark_area(opacity=0.3)
                    .encode(
                        x=alt.X("일:T", title=None),
                        y=alt.Y(f"{sel_m}:Q", title=sel_m, scale=alt.Scale(zero=False)),
                        tooltip=[
                            alt.Tooltip("일:T", format="%Y-%m-%d"),
                            alt.Tooltip(f"{sel_m}:Q", format=",.0f", title=sel_m),
                        ],
                    )
                )
                line = (
                    alt.Chart(daily)
                    .mark_line(strokeWidth=2)
                    .encode(
                        x=alt.X("일:T", title=None),
                        y=alt.Y(f"{sel_m}:Q", scale=alt.Scale(zero=False)),
                    )
                )
                ma = (
                    alt.Chart(daily)
                    .mark_line(strokeDash=[4, 4], color="gray", strokeWidth=1.5)
                    .encode(
                        x="일:T",
                        y=alt.Y("MA7:Q", scale=alt.Scale(zero=False)),
                        tooltip=[
                            alt.Tooltip("일:T", format="%Y-%m-%d"),
                            alt.Tooltip("MA7:Q", format=",.0f", title="7일 MA"),
                        ],
                    )
                )

                col1, col2 = st.columns([3, 1])
                with col1:
                    with st.container(border=True):
                        st.caption(f"**{sel_m}** 일별 추이  ·  점선: 7일 이동평균")
                        st.altair_chart((area + line + ma).properties(height=CHART_H))
                with col2:
                    with st.container(border=True):
                        st.caption("**일별 집계**")
                        fmt = "₩{:,.0f}" if sel_m in ["비용","구매매출"] else "{:,.0f}"
                        st.dataframe(
                            daily[["일", sel_m]].sort_values("일", ascending=False),
                            column_config={
                                "일": st.column_config.DateColumn("날짜", format="YYYY-MM-DD"),
                                sel_m: st.column_config.NumberColumn(sel_m, format=fmt),
                            },
                            hide_index=True, height=320,
                        )


# ── 채널 분석 ─────────────────────────────────────────────────────────────
if tab_ch.open:
    with tab_ch:
        if "채널" not in df.columns or df.empty:
            st.info("데이터 없음")
        else:
            ch_m   = [c for c in ["노출","클릭","비용","회원가입","구매","구매매출"] if c in df.columns]
            ch_agg = df.groupby("채널")[ch_m].sum().reset_index()

            if "노출" in ch_agg.columns and "클릭" in ch_agg.columns:
                ch_agg["CTR(%)"]  = (ch_agg["클릭"] / ch_agg["노출"].replace(0, 1) * 100).round(2)
            if "비용" in ch_agg.columns and "클릭" in ch_agg.columns:
                ch_agg["CPC(₩)"]  = (ch_agg["비용"] / ch_agg["클릭"].replace(0, 1)).round(0)
            if "비용" in ch_agg.columns and "구매" in ch_agg.columns:
                ch_agg["CPA(₩)"]  = (ch_agg["비용"] / ch_agg["구매"].replace(0, 1)).round(0)
            if "비용" in ch_agg.columns and "구매매출" in ch_agg.columns:
                ch_agg["ROAS(%)"] = (ch_agg["구매매출"] / ch_agg["비용"].replace(0, 1) * 100).round(1)

            all_m = [c for c in ch_agg.columns if c != "채널"]

            c1, c2 = st.columns(2)
            with c1:
                bar_m = st.selectbox("막대 지표", [c for c in ["비용","노출","클릭","구매","구매매출"] if c in all_m], key="ch_bar")
            with c2:
                pie_m = st.selectbox("파이 지표", [c for c in ["비용","구매매출","구매"] if c in all_m], key="ch_pie")

            row = st.columns(2)
            with row[0]:
                with st.container(border=True):
                    st.caption(f"**채널별 {bar_m}**")
                    st.altair_chart(
                        alt.Chart(ch_agg)
                        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                        .encode(
                            x=alt.X("채널:N", sort="-y", title=None),
                            y=alt.Y(f"{bar_m}:Q", title=bar_m),
                            color=alt.Color("채널:N", legend=None),
                            tooltip=["채널:N"] + [
                                alt.Tooltip(f"{m}:Q", format=",.1f")
                                for m in all_m if m in ch_agg.columns
                            ],
                        ).properties(height=CHART_H)
                    )

            with row[1]:
                with st.container(border=True):
                    st.caption(f"**채널별 {pie_m} 비중**")
                    st.altair_chart(
                        alt.Chart(ch_agg)
                        .mark_arc(innerRadius=60)
                        .encode(
                            theta=alt.Theta(f"{pie_m}:Q"),
                            color=alt.Color("채널:N", legend=alt.Legend(orient="right")),
                            tooltip=["채널:N", alt.Tooltip(f"{pie_m}:Q", format=",.0f")],
                        ).properties(height=CHART_H)
                    )

            with st.container(border=True):
                st.caption("**채널별 종합 성과**")
                _fmt = {
                    "노출":     st.column_config.NumberColumn(format="%.0f"),
                    "클릭":     st.column_config.NumberColumn(format="%.0f"),
                    "비용":     st.column_config.NumberColumn(format="₩%.0f"),
                    "회원가입": st.column_config.NumberColumn(format="%.0f"),
                    "구매":     st.column_config.NumberColumn(format="%.0f"),
                    "구매매출": st.column_config.NumberColumn(format="₩%.0f"),
                    "CTR(%)":   st.column_config.NumberColumn(format="%.2f%%"),
                    "CPC(₩)":   st.column_config.NumberColumn(format="₩%.0f"),
                    "CPA(₩)":   st.column_config.NumberColumn(format="₩%.0f"),
                    "ROAS(%)":  st.column_config.NumberColumn(format="%.1f%%"),
                }
                st.dataframe(
                    ch_agg.sort_values("비용", ascending=False) if "비용" in ch_agg.columns else ch_agg,
                    column_config={k: v for k, v in _fmt.items() if k in ch_agg.columns},
                    hide_index=True,
                )


# ── 캠페인 분석 ───────────────────────────────────────────────────────────
if tab_camp.open:
    with tab_camp:
        if "캠페인" not in df.columns or df.empty:
            st.info("데이터 없음")
        else:
            grp_by = ["캠페인"] + [c for c in ["채널","캠페인목적"] if c in df.columns]
            cm     = [c for c in ["비용","노출","클릭","회원가입","구매","구매매출"] if c in df.columns]
            ca     = df.groupby(grp_by)[cm].sum().reset_index()

            if "비용" in ca.columns and "구매"     in ca.columns:
                ca["CPA(₩)"]  = (ca["비용"] / ca["구매"].replace(0, 1)).round(0)
            if "비용" in ca.columns and "구매매출" in ca.columns:
                ca["ROAS(%)"] = (ca["구매매출"] / ca["비용"].replace(0, 1) * 100).round(1)

            sort_col = st.selectbox(
                "정렬",
                [c for c in ["비용","ROAS(%)","구매매출","CPA(₩)","구매"] if c in ca.columns],
                key="camp_sort",
            )

            c1, c2 = st.columns([3, 2])
            with c1:
                with st.container(border=True):
                    st.caption("**캠페인별 성과**")
                    _fmt2 = {
                        "비용":     st.column_config.NumberColumn(format="₩%.0f"),
                        "노출":     st.column_config.NumberColumn(format="%.0f"),
                        "클릭":     st.column_config.NumberColumn(format="%.0f"),
                        "회원가입": st.column_config.NumberColumn(format="%.0f"),
                        "구매":     st.column_config.NumberColumn(format="%.0f"),
                        "구매매출": st.column_config.NumberColumn(format="₩%.0f"),
                        "CPA(₩)":   st.column_config.NumberColumn(format="₩%.0f"),
                        "ROAS(%)":  st.column_config.NumberColumn(format="%.1f%%"),
                    }
                    ascending = sort_col not in ["ROAS(%)"]
                    st.dataframe(
                        ca.sort_values(sort_col, ascending=ascending),
                        column_config={k: v for k, v in _fmt2.items() if k in ca.columns},
                        hide_index=True, height=420,
                    )

            with c2:
                bar_m2 = st.selectbox(
                    "차트 지표",
                    [c for c in ["비용","구매매출","구매"] if c in ca.columns],
                    key="camp_bar",
                )
                with st.container(border=True):
                    st.caption(f"**캠페인별 {bar_m2}** (상위 10)")
                    st.altair_chart(
                        alt.Chart(ca.nlargest(10, bar_m2))
                        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                        .encode(
                            y=alt.Y("캠페인:N", sort="-x", title=None),
                            x=alt.X(f"{bar_m2}:Q", title=bar_m2),
                            color=alt.Color("캠페인:N", legend=None),
                            tooltip=["캠페인:N", alt.Tooltip(f"{bar_m2}:Q", format=",.0f")],
                        ).properties(height=380)
                    )


# ── 소재 분석 ─────────────────────────────────────────────────────────────
if tab_creative.open:
    with tab_creative:
        if df.empty:
            st.info("데이터 없음")
        else:
            g_opts = [c for c in ["소재","채널","캠페인","그룹"] if c in df.columns]
            g_by   = st.multiselect(
                "그룹 기준", g_opts,
                default=[c for c in ["소재","채널"] if c in df.columns],
                key="cr_grp",
            )
            if not g_by:
                st.info("그룹 기준을 하나 이상 선택하세요.")
            else:
                cr_m  = [c for c in ["비용","노출","클릭","회원가입","구매","구매매출"] if c in df.columns]
                cr    = df.groupby(g_by)[cr_m].sum().reset_index()

                if "노출" in cr.columns and "클릭" in cr.columns:
                    cr["CTR(%)"]  = (cr["클릭"] / cr["노출"].replace(0, 1) * 100).round(2)
                if "비용" in cr.columns and "구매" in cr.columns:
                    cr["CPA(₩)"]  = (cr["비용"] / cr["구매"].replace(0, 1)).round(0)
                if "비용" in cr.columns and "구매매출" in cr.columns:
                    cr["ROAS(%)"] = (cr["구매매출"] / cr["비용"].replace(0, 1) * 100).round(1)

                sort_cr = st.selectbox(
                    "정렬",
                    [c for c in ["비용","ROAS(%)","구매매출","CPA(₩)"] if c in cr.columns],
                    key="cr_sort",
                )
                asc_cr = sort_cr not in ["ROAS(%)","CTR(%)"]

                with st.container(border=True):
                    st.caption(f"**소재 분석** — {len(cr):,}개 조합")
                    _fmt3 = {
                        "비용":     st.column_config.NumberColumn(format="₩%.0f"),
                        "노출":     st.column_config.NumberColumn(format="%.0f"),
                        "클릭":     st.column_config.NumberColumn(format="%.0f"),
                        "회원가입": st.column_config.NumberColumn(format="%.0f"),
                        "구매":     st.column_config.NumberColumn(format="%.0f"),
                        "구매매출": st.column_config.NumberColumn(format="₩%.0f"),
                        "CTR(%)":   st.column_config.NumberColumn(format="%.2f%%"),
                        "CPA(₩)":   st.column_config.NumberColumn(format="₩%.0f"),
                        "ROAS(%)":  st.column_config.NumberColumn(format="%.1f%%"),
                    }
                    st.dataframe(
                        cr.sort_values(sort_cr, ascending=asc_cr),
                        column_config={k: v for k, v in _fmt3.items() if k in cr.columns},
                        hide_index=True, height=480,
                    )


# ── 원본 데이터 ───────────────────────────────────────────────────────────
if tab_raw.open:
    with tab_raw:
        search = st.text_input(
            "검색", placeholder="채널, 캠페인, 소재명 검색...",
            label_visibility="collapsed",
        )
        disp = _ensure_numeric(df)
        if search:
            mask = disp.apply(
                lambda c: c.astype(str).str.contains(search, case=False, na=False)
            ).any(axis=1)
            disp = disp[mask]

        with st.container(border=True):
            st.caption(f"**{len(disp):,}행** × {len(disp.columns)}열")
            _fmt4 = {
                "일":          st.column_config.DateColumn("날짜", format="YYYY-MM-DD"),
                "노출":        st.column_config.NumberColumn("노출",     format="%d"),
                "클릭":        st.column_config.NumberColumn("클릭",     format="%d"),
                "비용":        st.column_config.NumberColumn("비용",     format="₩%d"),
                "회원가입":    st.column_config.NumberColumn("회원가입", format="%d"),
                "구매":        st.column_config.NumberColumn("구매",     format="%d"),
                "구매매출":    st.column_config.NumberColumn("구매매출", format="₩%d"),
                "AF_클릭":     st.column_config.NumberColumn("AF_클릭",  format="%d"),
                "AF_회원가입": st.column_config.NumberColumn("AF_회원가입", format="%d"),
                "AF_구매":     st.column_config.NumberColumn("AF_구매",  format="%d"),
                "AF_구매매출": st.column_config.NumberColumn("AF_구매매출", format="₩%d"),
            }
            st.dataframe(
                disp,
                column_config={k: v for k, v in _fmt4.items() if k in disp.columns},
                hide_index=True, height=500,
            )
            csv_bytes = disp.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                ":material/download: CSV 다운로드",
                data=csv_bytes,
                file_name="marketing_data.csv",
                mime="text/csv",
                type="tertiary",
            )
