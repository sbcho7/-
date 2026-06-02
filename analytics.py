"""
이상 감지 + 예산 페이싱 + 액션 추천 로직
전일 vs 직전 7일 평균 비교 기반
"""
from __future__ import annotations

import pandas as pd

# ─── 이상 감지 임계값 ─────────────────────────────────────────────────────
THRESHOLDS = {
    "CPA_up_pct":    30,    # CPA 30% 이상 상승 → 위험
    "ROAS_down_pct": 20,    # ROAS 20% 이상 하락 → 위험
    "CTR_down_pct":  30,    # CTR 30% 이상 하락 → 경고
    "cost_up_pct":   50,    # 비용 50% 이상 급증 → 경고
    "pacing_high":  120,    # 7일 평균 대비 120% 초과 = 과집행
    "pacing_low":    70,    # 7일 평균 대비 70% 미만 = 저조
}


def _latest_date(df: pd.DataFrame) -> pd.Timestamp | None:
    if "일" not in df.columns or df.empty:
        return None
    return df["일"].max()


def get_prev_day(df: pd.DataFrame) -> pd.DataFrame:
    """전일(최신일) 데이터"""
    d = _latest_date(df)
    return df[df["일"] == d].copy() if d is not None else pd.DataFrame()


def get_rolling_avg(df: pd.DataFrame, days: int = 7) -> pd.DataFrame:
    """전일 제외 직전 N일 데이터 (비교용)"""
    latest = _latest_date(df)
    if latest is None:
        return pd.DataFrame()
    end   = latest - pd.Timedelta(days=1)
    start = end    - pd.Timedelta(days=days - 1)
    return df[(df["일"] >= start) & (df["일"] <= end)].copy()


def _safe_div(a: float, b: float) -> float:
    return a / b if b and b > 0 else 0.0


def compute_channel_kpis(sub: pd.DataFrame) -> dict:
    """데이터 서브셋에서 KPI 계산"""
    노출 = float(sub["노출"].sum())     if "노출"     in sub.columns else 0.0
    클릭 = float(sub["클릭"].sum())     if "클릭"     in sub.columns else 0.0
    비용 = float(sub["비용"].sum())     if "비용"     in sub.columns else 0.0
    구매 = float(sub["구매"].sum())     if "구매"     in sub.columns else 0.0
    매출 = float(sub["구매매출"].sum()) if "구매매출" in sub.columns else 0.0
    return dict(
        노출=노출, 클릭=클릭, 비용=비용, 구매=구매, 매출=매출,
        CTR =_safe_div(클릭, 노출) * 100,
        CPC =_safe_div(비용, 클릭),
        CPA =_safe_div(비용, 구매),
        ROAS=_safe_div(매출, 비용) * 100,
    )


def _pct_change(now: float, prev: float) -> float | None:
    if prev and prev > 0:
        return (now - prev) / prev * 100
    return None


def _channel_rolling_avgs(rl: pd.DataFrame) -> dict:
    """채널 데이터 서브셋에서 7일 평균 KPI 계산. 데이터 없으면 모두 0."""
    zeros = dict(avg_비용=0.0, avg_클릭=0.0, avg_구매=0.0,
                 avg_매출=0.0, avg_노출=0.0,
                 avg_CPA=0.0, avg_ROAS=0.0, avg_CTR=0.0)

    if rl.empty:
        return zeros

    needed = [c for c in ["비용","클릭","구매","구매매출","노출"] if c in rl.columns]
    if not needed or "일" not in rl.columns:
        return zeros

    daily = rl.groupby("일")[needed].sum().reset_index()

    avg_비용 = float(daily["비용"].mean())      if "비용"     in daily.columns else 0.0
    avg_클릭 = float(daily["클릭"].mean())      if "클릭"     in daily.columns else 0.0
    avg_구매 = float(daily["구매"].mean())      if "구매"     in daily.columns else 0.0
    avg_매출 = float(daily["구매매출"].mean())  if "구매매출" in daily.columns else 0.0
    avg_노출 = float(daily["노출"].mean())      if "노출"     in daily.columns else 0.0

    return dict(
        avg_비용=avg_비용, avg_클릭=avg_클릭, avg_구매=avg_구매,
        avg_매출=avg_매출, avg_노출=avg_노출,
        avg_CPA =_safe_div(avg_비용, avg_구매),
        avg_ROAS=_safe_div(avg_매출, avg_비용) * 100,
        avg_CTR =_safe_div(avg_클릭, avg_노출) * 100,
    )


# ─── 예산 페이싱 ──────────────────────────────────────────────────────────

def budget_pacing(df: pd.DataFrame) -> list[dict]:
    """
    채널별 예산 페이싱:
      전일 비용 ÷ 직전 7일 평균 일비용 × 100
      100% = 평균 페이스  /  >120% = 과집행  /  <70% = 저조
    데이터가 1일치뿐이면 pacing_pct=None 으로 반환 (비교 불가)
    """
    if "채널" not in df.columns or df.empty:
        return []

    prev_day = get_prev_day(df)
    rolling  = get_rolling_avg(df, days=7)

    if prev_day.empty or "비용" not in prev_day.columns:
        return []

    result = []
    for ch in sorted(df["채널"].dropna().unique()):
        today_cost = float(prev_day[prev_day["채널"] == ch]["비용"].sum())

        rl_ch = rolling[rolling["채널"] == ch] if not rolling.empty else pd.DataFrame()
        avgs  = _channel_rolling_avgs(rl_ch)
        avg_cost = avgs["avg_비용"]

        if avg_cost > 0:
            pacing_pct = today_cost / avg_cost * 100
            if pacing_pct >= THRESHOLDS["pacing_high"]:
                status = "over"
            elif pacing_pct <= THRESHOLDS["pacing_low"]:
                status = "low"
            else:
                status = "normal"
        else:
            pacing_pct = None   # 비교 기준 없음 (1일치 데이터)
            status = "no_baseline"

        result.append(dict(
            채널=ch,
            today_cost=today_cost,
            avg_cost=avg_cost,
            pacing_pct=pacing_pct,
            status=status,
        ))

    return result


# ─── 이상 감지 ────────────────────────────────────────────────────────────

def detect_anomalies(df: pd.DataFrame) -> list[dict]:
    """
    채널 단위로 전일 KPI vs 직전 7일 평균 비교.
    7일 평균 데이터가 없으면 해당 채널은 건너뜀.
    """
    if df.empty or "채널" not in df.columns:
        return []

    prev_day = get_prev_day(df)
    rolling  = get_rolling_avg(df, days=7)

    if prev_day.empty:
        return []

    anomalies: list[dict] = []

    for ch in sorted(df["채널"].dropna().unique()):
        td = prev_day[prev_day["채널"] == ch]
        if td.empty:
            continue

        kpi = compute_channel_kpis(td)

        rl_ch = rolling[rolling["채널"] == ch] if not rolling.empty else pd.DataFrame()
        avgs  = _channel_rolling_avgs(rl_ch)

        # 비교 기준 없으면 이상감지 불가 → 건너뜀
        if avgs["avg_비용"] == 0 and avgs["avg_CPA"] == 0:
            continue

        # CPA 급등
        chg = _pct_change(kpi["CPA"], avgs["avg_CPA"])
        if chg and chg >= THRESHOLDS["CPA_up_pct"]:
            anomalies.append(dict(
                level="danger", 채널=ch, metric="CPA",
                message=f"{ch} CPA {chg:+.0f}% 급등",
                detail=f"전일 ₩{kpi['CPA']:,.0f}  vs  7일평균 ₩{avgs['avg_CPA']:,.0f}",
                action=f"{ch} 고CPA 소재 중지 또는 입찰가 인하 검토",
                change_pct=chg,
            ))

        # ROAS 급락
        chg = _pct_change(kpi["ROAS"], avgs["avg_ROAS"])
        if chg and chg <= -THRESHOLDS["ROAS_down_pct"]:
            anomalies.append(dict(
                level="danger", 채널=ch, metric="ROAS",
                message=f"{ch} ROAS {chg:+.0f}% 급락",
                detail=f"전일 {kpi['ROAS']:.0f}%  vs  7일평균 {avgs['avg_ROAS']:.0f}%",
                action=f"{ch} 구매전환율 점검 및 랜딩페이지 확인",
                change_pct=chg,
            ))

        # CTR 하락
        chg = _pct_change(kpi["CTR"], avgs["avg_CTR"])
        if chg and chg <= -THRESHOLDS["CTR_down_pct"]:
            anomalies.append(dict(
                level="warning", 채널=ch, metric="CTR",
                message=f"{ch} CTR {chg:+.0f}% 하락",
                detail=f"전일 {kpi['CTR']:.2f}%  vs  7일평균 {avgs['avg_CTR']:.2f}%",
                action=f"{ch} 소재 피로도 점검, 크리에이티브 교체 검토",
                change_pct=chg,
            ))

        # 비용 급증
        chg = _pct_change(kpi["비용"], avgs["avg_비용"])
        if chg and chg >= THRESHOLDS["cost_up_pct"]:
            anomalies.append(dict(
                level="warning", 채널=ch, metric="비용",
                message=f"{ch} 비용 {chg:+.0f}% 급증",
                detail=f"전일 ₩{kpi['비용']:,.0f}  vs  7일평균 ₩{avgs['avg_비용']:,.0f}",
                action=f"{ch} 비용 급증 원인 확인 (입찰 경쟁도·예산 설정 점검)",
                change_pct=chg,
            ))

    # 위험도 정렬 (danger → warning 순, 변화율 큰 것 앞)
    return sorted(anomalies, key=lambda x: (
        0 if x["level"] == "danger" else 1,
        -abs(x.get("change_pct", 0))
    ))


def pacing_anomalies(pacing_list: list[dict]) -> list[dict]:
    """예산 페이싱 이상을 anomaly 포맷으로 변환"""
    result = []
    for p in pacing_list:
        if p["status"] == "over" and p["pacing_pct"]:
            result.append(dict(
                level="warning", 채널=p["채널"], metric="페이싱",
                message=f"{p['채널']} 예산 {p['pacing_pct']:.0f}% 과집행",
                detail=f"전일 ₩{p['today_cost']:,.0f}  vs  7일평균 ₩{p['avg_cost']:,.0f}",
                action=f"{p['채널']} 일예산 상향 또는 입찰가 점검",
                change_pct=p["pacing_pct"] - 100,
            ))
        elif p["status"] == "low" and p["pacing_pct"]:
            result.append(dict(
                level="info", 채널=p["채널"], metric="페이싱",
                message=f"{p['채널']} 예산 집행 저조 ({p['pacing_pct']:.0f}%)",
                detail=f"전일 ₩{p['today_cost']:,.0f}  vs  7일평균 ₩{p['avg_cost']:,.0f}",
                action=f"{p['채널']} 노출 저하 원인 확인 (입찰가·타겟 범위 점검)",
                change_pct=p["pacing_pct"] - 100,
            ))
    return result
