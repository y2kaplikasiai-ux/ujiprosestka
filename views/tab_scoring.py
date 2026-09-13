# views/tab_scoring.py
import streamlit as st
from ui_components import render_score_histogram


def render_tab_scoring(df_matrix):
    if df_matrix is None or df_matrix.empty:
        st.info("Belum ada data hasil skoring yang tersedia.")
        return

    st.subheader("Hasil Skoring Dikotomus (0 / 1)")
    
    usr_col = "username" if "username" in df_matrix.columns else df_matrix.columns[0]
    skor_col_name = "skor_mentah" if "skor_mentah" in df_matrix.columns else None

    # --- FALLBACK HANDLING SAAT REFRESH ---
    # 1. Menghitung Rata-rata Jumlah Soal
    if "Jumlah_Soal" in df_matrix.columns:
        avg_soal = df_matrix["Jumlah_Soal"].mean()
    else:
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
        item_cols = [c for c in df_matrix.columns if c not in meta_cols]
        avg_soal = float(len(item_cols)) if item_cols else 0.0

    # 2. Menghitung Rata-rata Skor Mentah
    avg_skor = df_matrix[skor_col_name].mean() if skor_col_name else 0.0

    # 3. Menghitung Rata-rata Nilai Konversi CTT Murni
    if "Nilai_Konversi" in df_matrix.columns:
        avg_konversi = df_matrix["Nilai_Konversi"].mean()
    elif "skor_konversi_ctt" in df_matrix.columns:
        avg_konversi = df_matrix["skor_konversi_ctt"].mean()
    else:
        avg_konversi = (avg_skor / avg_soal * 100.0) if avg_soal > 0 else 0.0

    # --- DISPLAY METRICS ---
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Responden", f"{len(df_matrix):,}")
    c2.metric("Rata-rata Skor Mentah", f"{avg_skor:.2f} / {avg_soal:.1f}")
    c3.metric("Rata-rata Nilai Konversi Klasik", f"{avg_konversi:.2f}")
    st.divider()

    # --- HISTOGRAM CHART ---
    df_chart = (
        df_matrix.sample(n=50000, random_state=42)
        if len(df_matrix) > 50000
        else df_matrix
    )
    fig_score = render_score_histogram(df_chart)
    st.plotly_chart(fig_score, use_container_width=True)

    # --- TABLE DISPLAY ---
    df_display_scoring = df_matrix.copy()

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
    st.caption("⚡ Menampilkan 100 sampel data pertama untuk efisiensi memori UI.")