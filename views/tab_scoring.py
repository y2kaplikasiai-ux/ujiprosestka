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
    df_target = None
    df_sess = st.session_state.get("df_peserta_skor")
    if df_sess is not None and not df_sess.empty:
        df_target = df_sess.copy()
        is_mysql = False
    elif df_matrix is not None and not df_matrix.empty and "skor_konversi_ctt" in df_matrix.columns:
        df_target = df_matrix.copy()
        is_mysql = False
    else:
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

    mapel_cols = [
        c
        for c in df_target.columns
        if str(c).strip().lower()
        in ["mapel", "mata_pelajaran", "mata pelajaran", "subject", "paket"]
    ]
    if not mapel_cols and df_matrix is not None and not df_matrix.empty:
        m_col_mat = next(
            (
                c
                for c in df_matrix.columns
                if str(c).strip().lower()
                in ["mapel", "mata_pelajaran", "mata pelajaran", "subject", "paket"]
            ),
            None,
        )
        if m_col_mat:
            usr_mat = df_matrix.columns[0]
            usr_t = "username" if "username" in df_target.columns else df_target.columns[0]
            u_map = dict(
                zip(
                    df_matrix[usr_mat].astype(str).str.strip(),
                    df_matrix[m_col_mat].astype(str).str.strip(),
                )
            )
            df_target["mapel"] = df_target[usr_t].astype(str).str.strip().map(u_map)
            mapel_cols = ["mapel"]

    if mapel_cols:
        mapel_col = mapel_cols[0]
        df_target[mapel_col] = df_target[mapel_col].map(
            lambda x: mapel_lookup.get(
                str(x).strip().upper(),
                mapel_lookup.get(str(x).strip(), str(x).strip()),
            )
        )
        list_mapel = sorted(
            [
                str(x)
                for x in df_target[mapel_col].dropna().unique().tolist()
                if str(x).strip() not in ["", "nan", "None", "-"]
            ]
        )
        if list_mapel:
            selected_mapel = st.selectbox(
                "Pilih Mata Pelajaran:",
                options=list_mapel,
                key="filter_scoring_mapel",
            )
            df_target = df_target[df_target[mapel_col] == selected_mapel].copy()

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
            "user_id",
            "nama",
            "mapel",
            "mata_pelajaran",
            "subject",
            "kode_paket",
            "kd_paket",
            "paket",
            "skor_mentah",
            "Nilai_Konversi",
            "nilai_konversi",
            "skor_konversi_ctt",
            "skor_konversi_rasch",
            "skor_konversi_1pl",
            "skor_konversi_2pl",
            "skor_konversi_3pl",
            "Jumlah_Soal",
            "jumlah_soal",
            "_school_key",
            "_prop_key_user",
            "kd_prop",
            "kode_provinsi",
        ]
        item_cols = [
            c for c in df_target.columns
            if c not in meta_cols and (df_target[c].dtype != object or pd.to_numeric(df_target[c], errors="coerce").notna().sum() > 0)
        ]
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
    fig_score = render_score_histogram(df_chart, col_type="skor_mentah")
    st.plotly_chart(fig_score, use_container_width=True)

    # --- TABLE DISPLAY ---
    df_display_scoring = df_target.copy()

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
        if col in df_display_scoring.columns and col not in selected_cols:
            selected_cols.append(col)

    if not selected_cols:
        selected_cols = list(df_display_scoring.columns[:6])

    df_display_scoring = df_display_scoring[selected_cols].head(100).copy()

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