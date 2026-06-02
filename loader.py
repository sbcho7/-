"""
데이터 로더: 폴더 내 모든 CSV 자동 수집 → concat → join
컬럼 구조:
  채널:       일, 채널, 채널분류, 캠페인, 캠페인목적, 그룹, 소재, 노출, 클릭, 비용, 회원가입, 구매, 구매매출
  앱스플라이어: 일, 미디어소스, 캠페인, 그룹, 소재, 클릭, 회원가입, 구매, 구매매출
"""
from __future__ import annotations

import glob
import os
from pathlib import Path

import pandas as pd
import streamlit as st

# ── 컬럼 정의 ─────────────────────────────────────────────────────────────
JOIN_KEYS       = ["일", "캠페인", "그룹", "소재"]
CH_METRIC_COLS  = ["노출", "클릭", "비용", "회원가입", "구매", "구매매출"]
AF_METRIC_COLS  = ["클릭", "회원가입", "구매", "구매매출"]   # AF에서 이름 충돌 방지용
NUMERIC_COLS    = ["노출", "클릭", "비용", "회원가입", "구매", "구매매출"]

# 인코딩 우선순위 (한글 CSV 환경 대응)
_ENCODINGS = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]


def _safe_read_csv(fp: str) -> pd.DataFrame | None:
    """인코딩 자동 감지로 CSV 읽기 — 표준 numpy dtype 사용 (Streamlit 호환)"""
    for enc in _ENCODINGS:
        try:
            # dtype_backend 제거: 명시적 _parse_numerics 에서 int64 변환
            df = pd.read_csv(fp, encoding=enc)
            return df
        except (UnicodeDecodeError, Exception):
            continue
    return None


def _read_folder(folder: str, label: str) -> pd.DataFrame:
    """폴더 내 CSV/Excel 파일을 모두 읽어 concat"""
    if not folder or not os.path.isdir(folder):
        return pd.DataFrame()

    files: list[str] = []
    for pat in [
        os.path.join(folder, "*.csv"),
        os.path.join(folder, "*.xlsx"),
        os.path.join(folder, "**", "*.csv"),
        os.path.join(folder, "**", "*.xlsx"),
    ]:
        files.extend(glob.glob(pat, recursive=True))
    files = sorted(set(files))

    if not files:
        return pd.DataFrame()

    dfs: list[pd.DataFrame] = []
    for fp in files:
        try:
            ext = Path(fp).suffix.lower()
            if ext in (".xlsx", ".xls"):
                df = pd.read_excel(fp)   # dtype_backend 제거
            else:
                df = _safe_read_csv(fp)
            if df is not None and not df.empty:
                dfs.append(df)
        except Exception as e:
            st.warning(f"[{label}] {Path(fp).name} 읽기 실패: {e}")

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def _parse_date(df: pd.DataFrame) -> pd.DataFrame:
    """'일' 컬럼을 datetime으로 안전하게 변환"""
    if "일" not in df.columns:
        return df
    # str로 캐스팅 후 to_datetime (어떤 dtype이든 안전)
    df["일"] = pd.to_datetime(
        df["일"].astype(str).str.strip(), errors="coerce"
    )
    df = df.dropna(subset=["일"])
    return df


def _parse_numerics(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """숫자 컬럼을 int64로 안전하게 변환 (쉼표, 공백 제거 포함)"""
    for col in cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace(" ", "", regex=False)
                .pipe(pd.to_numeric, errors="coerce")
                .fillna(0)
                .astype("int64")
            )
    return df


def _strip_strings(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """문자열 컬럼 앞뒤 공백 제거"""
    for col in cols:
        if col in df.columns and col != "일":
            df[col] = df[col].astype(str).str.strip()
    return df


def _clean_channel(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    df = raw.copy()
    df = _parse_date(df)
    df = _parse_numerics(df, CH_METRIC_COLS)
    df = _strip_strings(df, ["채널", "채널분류", "캠페인", "캠페인목적", "그룹", "소재"])
    # 같은 날짜+채널+캠페인+그룹+소재 조합이 완전히 중복된 경우만 제거
    key_with_ch = [k for k in ["일", "채널", "캠페인", "그룹", "소재"] if k in df.columns]
    df = df.drop_duplicates(subset=key_with_ch, keep="last")
    return df.reset_index(drop=True)


def _clean_appsflyer(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    df = raw.copy()
    df = _parse_date(df)
    df = _parse_numerics(df, AF_METRIC_COLS)
    df = _strip_strings(df, ["미디어소스", "캠페인", "그룹", "소재"])
    # 같은 날짜+미디어소스+캠페인+그룹+소재 완전 중복만 제거
    key_with_src = [k for k in ["일", "미디어소스", "캠페인", "그룹", "소재"] if k in df.columns]
    df = df.drop_duplicates(subset=key_with_src, keep="last")
    return df.reset_index(drop=True)


@st.cache_data(ttl="5m", show_spinner="채널 데이터 로드 중...")
def load_channel_data(folder: str) -> pd.DataFrame:
    return _clean_channel(_read_folder(folder, "채널"))


@st.cache_data(ttl="5m", show_spinner="앱스플라이어 데이터 로드 중...")
def load_appsflyer_data(folder: str) -> pd.DataFrame:
    return _clean_appsflyer(_read_folder(folder, "앱스플라이어"))


@st.cache_data(ttl="5m", show_spinner="데이터 조인 중...")
def load_and_join(channel_folder: str, appsflyer_folder: str) -> pd.DataFrame:
    """
    채널 + 앱스플라이어 LEFT JOIN
    - JOIN 키: 일 / 캠페인 / 그룹 / 소재
    - AF 메트릭은 AF_ 접두사로 구분
    """
    ch_df = load_channel_data(channel_folder)
    af_df = load_appsflyer_data(appsflyer_folder)

    if ch_df.empty and af_df.empty:
        return pd.DataFrame()
    if ch_df.empty:
        return af_df
    if af_df.empty:
        return ch_df

    # AF 메트릭 컬럼명에 AF_ 접두사
    af_rename = {col: f"AF_{col}" for col in AF_METRIC_COLS if col in af_df.columns}
    af_ready = af_df.rename(columns=af_rename)

    # 조인에 사용할 AF 컬럼만 선택 (키 + AF 메트릭 + 미디어소스)
    af_cols = JOIN_KEYS + list(af_rename.values())
    if "미디어소스" in af_ready.columns:
        af_cols.append("미디어소스")
    af_cols = [c for c in af_cols if c in af_ready.columns]

    common_keys = [k for k in JOIN_KEYS if k in ch_df.columns and k in af_ready.columns]

    merged = pd.merge(
        ch_df,
        af_ready[af_cols],
        on=common_keys,
        how="left",
    )

    # AF 메트릭 NaN → 0
    for col in af_rename.values():
        if col in merged.columns:
            merged[col] = merged[col].fillna(0).astype("int64")

    # 날짜 내림차순 정렬
    if "일" in merged.columns:
        merged = merged.sort_values("일", ascending=False).reset_index(drop=True)

    return merged


def compute_kpis(df: pd.DataFrame) -> dict:
    """주요 KPI 딕셔너리 반환"""
    def _s(col: str) -> float:
        return float(df[col].sum()) if col in df.columns else 0.0

    노출  = _s("노출")
    클릭  = _s("클릭")
    비용  = _s("비용")
    가입  = _s("회원가입")
    구매  = _s("구매")
    매출  = _s("구매매출")

    has_af = "AF_구매" in df.columns
    return dict(
        노출=노출, 클릭=클릭, 비용=비용,
        회원가입=가입, 구매=구매, 구매매출=매출,
        CTR =클릭 / 노출 * 100 if 노출  > 0 else 0.0,
        CPC =비용 / 클릭       if 클릭  > 0 else 0.0,
        CPA =비용 / 구매       if 구매  > 0 else 0.0,
        ROAS=매출 / 비용 * 100 if 비용  > 0 else 0.0,
        af_가입  = _s("AF_회원가입") if has_af else None,
        af_구매  = _s("AF_구매")     if has_af else None,
        af_매출  = _s("AF_구매매출") if has_af else None,
        has_af   = has_af,
    )
