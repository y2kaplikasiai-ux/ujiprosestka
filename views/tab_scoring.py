# views/tab_scoring.py
import streamlit as st
import pandas as pd
from ui_components import render_score_histogram
from db_helper import get_db_connection
from validators import get_mapel_lookup_dict


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


def render_tab_scoring(df_matrix, dfs=None):
    # Prioritaskan data di memory session agar proses instan tanpa query ulang MySQL
    df_sess = st.session_state.get("df_peserta_skor")
    if df_sess is not None and not df_sess.empty:
        df_target = df_sess
        is_mysql = False
    elif df_matrix is not None and not df_matrix.empty and "skor_konversi_ctt" in df_matrix.columns:
        df_target = df_matrix
        is_mysql = False
    else:
        df_db = load_scoring_from_mysql()
        if df_db is not None and not df_db.empty:
            df_target = df_db
            is_mysql = True
        elif df_matrix is not None and not df_matrix.empty:
            df_target = df_matrix
            is_mysql = False
        else:
            st.info("Belum ada data hasil skoring yang tersedia.")
            return

    st.subheader("Hasil Skoring Dikotomus (0 / 1)")

    # Mapping nama mata pelajaran mengacu ke master mapel
    mapel_lookup = {}
    if dfs and isinstance(dfs, dict) and "mapel" in dfs and dfs["mapel"] is not None and not dfs["mapel"].empty:
        mapel_lookup = get_mapel_lookup_dict(dfs["mapel"])
    if not mapel_lookup:
        mapel_lookup = st.session_state.get("mapel_dict", {})
    if not mapel_lookup and "val_result" in st.session_state:
        df_mpl_sess = st.session_state["val_result"].get("dataframes", {}).get("mapel")
        if df_mpl_sess is not None and not df_mpl_sess.empty:
            mapel_lookup = get_mapel_lookup_dict(df_mpl_sess)
    if not mapel_lookup:
        mapel_lookup = get_mapel_lookup_dict(None)

    # Deteksi kolom mapel
    mapel_col = next(
        (c for c in df_target.columns if str(c).strip().lower() in ["mapel", "mata_pelajaran", "mata pelajaran", "subject", "paket"]),
        None
    )

    # Ambil list mapel dari cache precomputed CTT jika tersedia
    ctt_cache = st.session_state.get("ctt_summary_precomputed", {})
    if ctt_cache and isinstance(ctt_cache, dict):
        list_mapel = [m for m in sorted(ctt_cache.keys()) if m != "ALL"]
    elif mapel_col:
        list_mapel = sorted([
            mapel_lookup.get(str(x).strip().upper(), str(x).strip())
            for x in df_target[mapel_col].dropna().unique()
            if str(x).strip() not in ["", "nan", "None", "-"]
        ])
    else:
        list_mapel = []

    selected_mapel = None
    if list_mapel:
        selected_mapel = st.selectbox(
            "Pilih Mata Pelajaran:",
            options=list_mapel,
            key="filter_scoring_mapel",
        )

    # Slice data untuk mapel terpilih (tanpa copy seluruh 3.34M rows)
    if mapel_col and selected_mapel:
        if selected_mapel in df_target[mapel_col].values:
            df_active = df_target[df_target[mapel_col] == selected_mapel]
        else:
            # Mapel di df_target mungkin belum dinormalisasi
            df_active = df_target[
                df_target[mapel_col].astype(str).str.strip().str.upper() == selected_mapel.upper()
            ]
    else:
        df_active = df_target

    # Cek metrik dari precomputed cache untuk respon sub-milidetik
    used_cache = False
    if ctt_cache and selected_mapel and selected_mapel in ctt_cache:
        c_info = ctt_cache[selected_mapel]
        total_resp = c_info.get("N", len(df_active))
        avg_skor = c_info.get("mean_skor_mentah", 0.0)
        avg_soal = float(c_info.get("k", 25))
        avg_konversi = c_info.get("mean", 0.0)
        used_cache = True
    elif ctt_cache and "ALL" in ctt_cache and not selected_mapel:
        c_info = ctt_cache["ALL"]
        total_resp = c_info.get("N", len(df_active))
        avg_skor = c_info.get("mean_skor_mentah", 0.0)
        avg_soal = float(c_info.get("k", 25))
        avg_konversi = c_info.get("mean", 0.0)
        used_cache = True
    else:
        total_resp = len(df_active)
        avg_soal = float(df_active["Jumlah_Soal"].mean()) if "Jumlah_Soal" in df_active.columns else 25.0
        avg_skor = float(df_active["skor_mentah"].mean()) if "skor_mentah" in df_active.columns else 0.0
        if "skor_konversi_ctt" in df_active.columns:
            avg_konversi = float(df_active["skor_konversi_ctt"].mean())
        elif "Nilai_Konversi" in df_active.columns:
            avg_konversi = float(df_active["Nilai_Konversi"].mean())
        else:
            avg_konversi = (avg_skor / avg_soal * 100.0) if avg_soal > 0 else 0.0

    # --- DISPLAY METRICS ---
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Responden", f"{total_resp:,}")
    c2.metric("Rata-rata Skor Mentah", f"{avg_skor:.2f} / {avg_soal:.1f}")
    c3.metric("Rata-rata Nilai Konversi Klasik", f"{avg_konversi:.2f}")
    st.divider()

    # --- HISTOGRAM CHART (Sampel cepat 20k rows) ---
    sample_size = min(len(df_active), 25000)
    df_chart = df_active.sample(n=sample_size, random_state=42) if len(df_active) > sample_size else df_active
    fig_score = render_score_histogram(df_chart, col_type="skor_mentah")
    st.plotly_chart(fig_score, use_container_width=True)

    # --- TABLE DISPLAY ---
    selected_cols = []
    for col in [
        "username",
        "mapel",
        "tahun",
        "Jumlah_Soal",
        "skor_mentah",
        "Nilai_Konversi",
        "skor_konversi_ctt",
        "skor_konversi_rasch",
        "skor_konversi_2pl",
        "skor_konversi_3pl",
    ]:
        if col in df_active.columns and col not in selected_cols:
            selected_cols.append(col)

    if not selected_cols:
        selected_cols = list(df_active.columns[:6])

    df_display_scoring = df_active[selected_cols].head(100).copy()

    rename_map = {
        "username": "Username",
        "mapel": "Mata Pelajaran",
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