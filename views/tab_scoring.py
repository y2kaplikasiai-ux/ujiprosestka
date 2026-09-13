# views/tab_scoring.py
import streamlit as st
import pandas as pd
from ui_components import render_score_histogram
from db_helper import get_db_connection


@st.cache_data(ttl=60)
def load_scoring_from_mysql():
    """Membaca hasil skoring terpusat dari MySQL agar konsisten dengan tab wilayah & sekolah."""
    try:
        engine = get_db_connection()
        if engine is None:
            return None
        return pd.read_sql_query("SELECT * FROM tb_peserta_skor", con=engine)
    except Exception:
        return None


def render_tab_scoring(df_matrix):
    # Prioritaskan Single Source of Truth dari MySQL
    df_db = load_scoring_from_mysql()

    if df_db is not None and not df_db.empty:
        df_target = df_db.copy()
        is_mysql = True
    elif df_matrix is not None and not df_matrix.empty:
        df_target = df_matrix.copy()
        is_mysql = False
    else:
        st.info("Belum ada data hasil skoring yang tersedia.")
        return

    st.subheader("Hasil Skoring Dikotomus (0 / 1)")

    usr_col = (
        "username" if "username" in df_target.columns else df_target.columns[0]
    )

    if is_mysql:
        avg_soal = (
            float(df_target["Jumlah_Soal"].mean())
            if "Jumlah_Soal" in df_target.columns and df_target["Jumlah_Soal"].notna().any()
            else 25.0
        )
        avg_skor = (
            float(df_target["skor_mentah"].mean())
            if "skor_mentah" in df_target.columns
            else 0.0
        )
        avg_konversi = (
            float(df_target["skor_konversi_ctt"].mean())
            if "skor_konversi_ctt" in df_target.columns
            else 0.0
        )

        df_chart_source = df_target.copy()
        if "skor_konversi_ctt" in df_chart_source.columns:
            df_chart_source["Nilai_Konversi"] = df_chart_source[
                "skor_konversi_ctt"
            ]
        elif (
            "skor_mentah" in df_chart_source.columns and avg_soal > 0
        ):
            df_chart_source["Nilai_Konversi"] = (
                df_chart_source["skor_mentah"] / avg_soal
            ) * 100.0
    else:
        skor_col_name = (
            "skor_mentah" if "skor_mentah" in df_target.columns else None
        )
        meta_cols = [
            usr_col,
            "tahun",
            "username",
            "nama",
            "skor_mentah",
            "Nilai_Konversi",
            "skor_konversi_ctt",
            "skor_konversi_rasch",
            "skor_konversi_1pl",
            "skor_konversi_2pl",
            "skor_konversi_3pl",
            "_school_key",
            "_prop_key_user",
        ]
        item_cols = [c for c in df_target.columns if c not in meta_cols]
        avg_soal = (
            float(len(item_cols))
            if item_cols
            else float(
                df_target["Jumlah_Soal"].mean()
                if "Jumlah_Soal" in df_target.columns
                else 25.0
            )
        )
        avg_skor = (
            float(df_target[skor_col_name].mean()) if skor_col_name else 0.0
        )
        if "Nilai_Konversi" in df_target.columns:
            avg_konversi = float(df_target["Nilai_Konversi"].mean())
        elif "skor_konversi_ctt" in df_target.columns:
            avg_konversi = float(df_target["skor_konversi_ctt"].mean())
        else:
            avg_konversi = (
                (avg_skor / avg_soal * 100.0) if avg_soal > 0 else 0.0
            )
        df_chart_source = df_target.copy()

    # --- DISPLAY METRICS ---
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Responden", f"{len(df_target):,}")
    c2.metric("Rata-rata Skor Mentah", f"{avg_skor:.2f} / {avg_soal:.1f}")
    c3.metric("Rata-rata Nilai Konversi Klasik", f"{avg_konversi:.2f}")
    st.divider()

    # --- HISTOGRAM CHART ---
    df_chart = (
        df_chart_source.sample(n=50000, random_state=42)
        if len(df_chart_source) > 50000
        else df_chart_source
    )
    fig_score = render_score_histogram(df_chart)
    st.plotly_chart(fig_score, use_container_width=True)

    # --- TABLE DISPLAY ---
    df_display_scoring = df_target.copy()

    selected_cols = []
    for col in [
        "username",
        "tahun",
        "Jumlah_Soal",
        "skor_mentah",
        "Nilai_Konversi",
        "skor_konversi_ctt",
        "skor_konversi_rasch",
        "skor_konversi_2pl",
        "skor_konversi_3pl",
    ]:
        if col in df_display_scoring.columns and col not in selected_cols:
            selected_cols.append(col)

    if not selected_cols:
        selected_cols = list(df_display_scoring.columns[:6])

    df_display_scoring = df_display_scoring[selected_cols].head(100).copy()

    rename_map = {
        "username": "Username",
        "Jumlah_Soal": "Jumlah Soal",
        "skor_mentah": "Skor Mentah",
        "Nilai_Konversi": "Nilai Konversi Klasik",
        "skor_konversi_ctt": "Nilai Konversi Klasik",
        "skor_konversi_rasch": "Konversi Rasch (200-800)",
        "skor_konversi_2pl": "Konversi 2PL (200-800)",
        "skor_konversi_3pl": "Konversi 3PL (200-800)",
    }
    df_display_scoring.rename(columns=rename_map, inplace=True)
    df_display_scoring = df_display_scoring.loc[
        :, ~df_display_scoring.columns.duplicated()
    ].copy()

    if "No." not in df_display_scoring.columns:
        df_display_scoring.insert(0, "No.", range(1, 1 + len(df_display_scoring)))

    st.dataframe(df_display_scoring, use_container_width=True, hide_index=True)
    st.caption("⚡ Sumber data tersinkronisasi dari Single Source of Truth SQL (`tb_peserta_skor`).")