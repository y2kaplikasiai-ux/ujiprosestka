import io
import time
import zipfile
from collections import Counter

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.figure_factory as ff
import streamlit as st

import ctt_analysis
from equating import perform_multi_session_equating, run_cached_session_irt
from excel_exporter import convert_df_to_csv_bytes, create_excel_report
from irt_analysis import run_irt_analysis
from scoring import calculate_person_fit, process_scoring
from styles import load_custom_css
from ui_components import (
    render_ctt_scatter,
    render_irt_icc,
    render_irt_tif,
    render_score_histogram,
    render_wright_map,
)
from validators import validate_7_files

# ==========================================
# 1. Konfigurasi Halaman Streamlit
# ==========================================
st.set_page_config(
    page_title="Dashboard Analisis Psikometri TKA",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 2. Memuat CSS Custom
load_custom_css()

# 3. Header Utama Aplikasi
st.markdown(
    '<div class="main-header">📊 Dashboard Pengolahan & Analisis Psikometri TKA</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-header">Sistem Pemrosesan Data Respon, CTT (Klasik), dan IRT (Rasch, 1PL, 2PL) - Performa Tinggi</div>',
    unsafe_allow_html=True,
)

# Inisialisasi Session State
if "data_processed" not in st.session_state:
    st.session_state["data_processed"] = False
if "val_result" not in st.session_state:
    st.session_state["val_result"] = None

# ==========================================
# 4. Panel Sidebar
# ==========================================
st.sidebar.markdown(
    "<h3 style='margin-bottom: 4px; font-size: 1.1rem;'>📁 Unggah Berkas</h3>",
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    '<div class="info-header-box"><b>Format:</b> ZIP, CSV, XLSX, XLS &nbsp;|&nbsp; Boleh huruf KAPITAL maupun kecil</div>',
    unsafe_allow_html=True,
)

batch_files = st.sidebar.file_uploader(
    "Unggah Semua Berkas Sekaligus di Sini:",
    type=["csv", "xlsx", "xls", "zip"],
    accept_multiple_files=True,
    key="batch_uploader",
)


def extract_zip_files(files_list):
    extracted = []
    for f in files_list:
        if f.name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(f) as z:
                    for filename in z.namelist():
                        if not filename.startswith("__MACOSX") and filename.lower().endswith(
                            (".csv", ".xlsx", ".xls")
                        ):
                            content = z.read(filename)
                            file_bytes = io.BytesIO(content)
                            file_bytes.name = filename.split("/")[-1]
                            extracted.append(file_bytes)
            except Exception as e:
                st.sidebar.error(f"Gagal membaca file ZIP {f.name}: {e}")
        else:
            extracted.append(f)
    return extracted


uploaded_files = {
    "respon": None,
    "kunci": None,
    "biodata": None,
    "sekolah": None,
    "mapel": None,
    "kompetensi": None,
    "peta_paket": None,
}

if batch_files:
    all_unpacked_files = extract_zip_files(batch_files)

    for f in all_unpacked_files:
        fname = f.name.lower()
        if "respon" in fname and uploaded_files["respon"] is None:
            uploaded_files["respon"] = f
        elif "kunci" in fname and uploaded_files["kunci"] is None:
            uploaded_files["kunci"] = f
        elif "biodata" in fname and uploaded_files["biodata"] is None:
            uploaded_files["biodata"] = f
        elif "sekolah" in fname and uploaded_files["sekolah"] is None:
            uploaded_files["sekolah"] = f
        elif "mapel" in fname and uploaded_files["mapel"] is None:
            uploaded_files["mapel"] = f
        elif ("kompetensi" in fname or "kisi" in fname) and uploaded_files["kompetensi"] is None:
            uploaded_files["kompetensi"] = f
        elif ("paket" in fname or "peta" in fname) and uploaded_files["peta_paket"] is None:
            uploaded_files["peta_paket"] = f

st.sidebar.markdown("---")
st.sidebar.markdown("#### Status Deteksi Berkas:")

configs_info = [
    ("respon", "1. Lembar Respon", True),
    ("kunci", "2. Kunci Jawaban", True),
    ("biodata", "3. Biodata Peserta", False),
    ("sekolah", "4. Master Sekolah", False),
    ("mapel", "5. Mata Pelajaran", False),
    ("kompetensi", "6. Kisi-Kisi", False),
    ("peta_paket", "7. Pemetaan Paket", False),
]

for key, label, req in configs_info:
    req_mark = " <span style='color:red;'>*</span>" if req else ""
    if uploaded_files[key] is not None:
        st.sidebar.markdown(f"✅ **{label}**: `{uploaded_files[key].name}`")
    else:
        st.sidebar.markdown(
            f"❌ <span style='color:gray;'>{label}{req_mark}: Belum terdeteksi</span>",
            unsafe_allow_html=True,
        )

st.sidebar.markdown("---")
btn_process = st.sidebar.button("🚀 Proses Data", type="primary", use_container_width=True)

has_minimal_files = (uploaded_files["respon"] is not None) and (uploaded_files["kunci"] is not None)

# ==========================================
# 5. Logika Eksekusi Tombol Proses Data
# ==========================================
if btn_process:
    if not has_minimal_files:
        st.sidebar.error("❌ Berkas Lembar Respon dan Kunci Jawaban wajib diunggah!")
    else:
        with st.status("⏳ Memproses data psikometri...", expanded=True) as status:
            progress_bar = st.progress(0)
            t0 = time.time()

            status.write("🔍 **Langkah 1/3:** Memvalidasi struktur & format berkas...")
            progress_bar.progress(15)
            val_result = validate_7_files(uploaded_files)
            st.session_state["val_result"] = val_result

            if val_result["status"]:
                status.write("💯 **Langkah 2/3:** Menjalankan Scoring Engine...")
                progress_bar.progress(50)
                dfs = val_result["dataframes"]
                df_matrix = process_scoring(dfs["respon"], dfs["kunci"])

                # --- 1. MAPPING JUMLAH SOAL PASTI DARI TABEL MAPEL ---
                map_mapel_jml = {}
                if "mapel" in dfs and dfs["mapel"] is not None and not dfs["mapel"].empty:
                    df_mapel = dfs["mapel"].copy()
                    col_mapel_code = next(
                        (c for c in df_mapel.columns if c.lower().strip() in ["kode_mapel", "kodemapel", "id_mapel"]),
                        df_mapel.columns[0]
                    )
                    col_mapel_jml = next(
                        (c for c in df_mapel.columns if c.lower().strip() in ["jumlah_soal", "jumlahsoal", "jml_soal", "n_soal"]),
                        None
                    )
                    if col_mapel_jml:
                        df_mapel["_key_mapel"] = df_mapel[col_mapel_code].astype(str).str.strip().str.lower()
                        map_mapel_jml = df_mapel.drop_duplicates("_key_mapel").set_index("_key_mapel")[col_mapel_jml].to_dict()

                # --- 2. IDENTIFIKASI KOLOM RESPON & MATRIX ---
                df_respon_raw = dfs["respon"].copy()
                user_col_respon = next(
                    (c for c in df_respon_raw.columns if c.lower().strip() in ["username", "user_id", "id_peserta"]),
                    df_respon_raw.columns[0]
                )
                mapel_col_respon = next(
                    (c for c in df_respon_raw.columns if c.lower().strip() in ["kode_mapel", "kodemapel", "id_mapel"]),
                    None
                )
                list_soal_col = next(
                    (c for c in df_respon_raw.columns if c.lower().strip() in ["list_soal", "listsoal", "daftar_soal"]),
                    None
                )

                id_col_matrix = df_matrix.columns[0]
                non_item_kw = [
                    "nama_peserta", "nama", "namasiswa", "tahun", "skor_mentah",
                    "skor_total", "nilai_persen", "nilai_konversi", "username", "jumlah_soal"
                ]
                item_cols_matrix = [
                    c for c in df_matrix.columns
                    if c != id_col_matrix and c.lower() not in non_item_kw
                ]
                matrix_col_map_lower = {c.strip().lower(): c for c in item_cols_matrix}

                df_respon_raw["_join_id"] = df_respon_raw[user_col_respon].astype(str).str.strip().str.lower()
                df_matrix["_join_id"] = df_matrix[id_col_matrix].astype(str).str.strip().str.lower()

                def parse_list_soal(val):
                    if pd.isna(val) or not str(val).strip():
                        return []
                    return [s.strip() for s in str(val).split(",") if s.strip()]

                if list_soal_col:
                    df_respon_raw["_list_soal_parsed"] = df_respon_raw[list_soal_col].apply(parse_list_soal)
                    map_list_soal = df_respon_raw.drop_duplicates(subset=["_join_id"]).set_index("_join_id")["_list_soal_parsed"].to_dict()
                else:
                    map_list_soal = {}

                if mapel_col_respon:
                    df_respon_raw["_kode_mapel_clean"] = df_respon_raw[mapel_col_respon].astype(str).str.strip().str.lower()
                    map_user_mapel = df_respon_raw.drop_duplicates(subset=["_join_id"]).set_index("_join_id")["_kode_mapel_clean"].to_dict()
                else:
                    map_user_mapel = {}

                # --- 3. HITUNG SKOR MENTAH & JUMLAH SOAL ---
                skor_mentah_list = []
                jumlah_soal_list = []

                for _, row in df_matrix.iterrows():
                    user_id = row["_join_id"]
                    user_list_soal = map_list_soal.get(user_id, [])
                    user_mapel = map_user_mapel.get(user_id, "")

                    if user_mapel in map_mapel_jml and pd.notna(map_mapel_jml[user_mapel]):
                        try:
                            jml_soal_val = int(map_mapel_jml[user_mapel])
                        except ValueError:
                            jml_soal_val = len(user_list_soal) if user_list_soal else len(item_cols_matrix)
                    else:
                        jml_soal_val = len(user_list_soal) if user_list_soal else len(item_cols_matrix)

                    if user_list_soal:
                        user_item_cols = [
                            matrix_col_map_lower[s_code.strip().lower()]
                            for s_code in user_list_soal
                            if s_code.strip().lower() in matrix_col_map_lower
                        ]
                        if user_item_cols:
                            skor_val = pd.to_numeric(row[user_item_cols], errors="coerce").fillna(0).sum()
                        else:
                            skor_val = 0
                    else:
                        skor_val = pd.to_numeric(row[item_cols_matrix], errors="coerce").fillna(0).sum()

                    skor_mentah_list.append(int(skor_val))
                    jumlah_soal_list.append(int(jml_soal_val))

                df_matrix["skor_mentah"] = skor_mentah_list
                df_matrix["Jumlah_Soal"] = jumlah_soal_list

                # Bersihkan kolom bantu
                df_matrix.drop(columns=["_join_id"], inplace=True, errors="ignore")
                df_respon_raw.drop(columns=["_join_id", "_list_soal_parsed", "_kode_mapel_clean"], inplace=True, errors="ignore")

                # --- 4. HITUNG NILAI KONVERSI (0 - 100) ---
                arr_skor = df_matrix["skor_mentah"].values
                arr_jml = df_matrix["Jumlah_Soal"].values

                with np.errstate(divide="ignore", invalid="ignore"):
                    konversi_arr = np.where(arr_jml > 0, (arr_skor / arr_jml) * 100.0, 0.0)

                df_matrix["Nilai_Konversi"] = np.round(konversi_arr, 2)
                st.session_state["df_matrix"] = df_matrix

                status.write("📈 **Langkah 3/3:** Menganalisis Psikometri Klasik (CTT)...")
                progress_bar.progress(85)
                ctt_res = ctt_analysis.run_ctt_analysis(df_matrix, dfs["respon"], dfs["kunci"])
                st.session_state["ctt_res"] = ctt_res

                # --- 5. OLAHAN ANALISIS PER SEKOLAH ---
                df_matrix_school = pd.DataFrame()
                if "sekolah" in dfs and dfs["sekolah"] is not None and not dfs["sekolah"].empty:
                    try:
                        df_sek = dfs["sekolah"].copy()
                        df_sek.columns = [str(c).strip().lower() for c in df_sek.columns]

                        col_kd_sek = next((c for c in df_sek.columns if c in ["kd_sekfull", "kode_sekolah", "kd_sekolah", "id_sekolah", "kd_sek"]), df_sek.columns[0])
                        col_nama_sek = next((c for c in df_sek.columns if c in ["nama_sekolah", "namasekolah", "nama_sek", "sekolah"]), None)
                        col_nama_kab = next((c for c in df_sek.columns if c in ["nama_kabupaten", "namakabupaten", "nama_kab", "nama_kota", "kabupaten", "kota"]), None)
                        col_kd_prov = next((c for c in df_sek.columns if c in ["kd_prop", "kode_provinsi", "kd_provinsi", "kode_prop", "kd_prov"]), None)
                        col_nama_prov = next((c for c in df_sek.columns if c in ["nama_provinsi", "namaprovinsi", "nama_prov", "provinsi"]), None)

                        df_sek["_school_key"] = df_sek[col_kd_sek].astype(str).str.strip().str.upper()

                        cols_to_keep = ["_school_key"]
                        if col_nama_sek: cols_to_keep.append(col_nama_sek)
                        if col_nama_kab: cols_to_keep.append(col_nama_kab)
                        if col_kd_prov: cols_to_keep.append(col_kd_prov)
                        if col_nama_prov: cols_to_keep.append(col_nama_prov)

                        df_sek_clean = df_sek[cols_to_keep].drop_duplicates(subset=["_school_key"]).copy()

                        rename_map = {}
                        if col_nama_sek: rename_map[col_nama_sek] = "nama_sekolah_master"
                        if col_nama_kab: rename_map[col_nama_kab] = "nama_kabupaten_master"
                        if col_kd_prov: rename_map[col_kd_prov] = "kd_prop_master"
                        if col_nama_prov: rename_map[col_nama_prov] = "nama_provinsi_master"
                        df_sek_clean.rename(columns=rename_map, inplace=True)

                        id_user_col = df_matrix.columns[0]
                        for c_u in ["username", "user_id", "id_peserta"]:
                            if c_u in df_matrix.columns:
                                id_user_col = c_u
                                break

                        df_matrix_school = df_matrix.copy()
                        df_matrix_school["_school_key"] = df_matrix_school[id_user_col].astype(str).str.strip().str[:9].str.upper()
                        df_matrix_school["_prop_key_user"] = df_matrix_school[id_user_col].astype(str).str.strip().str[1:3]

                        df_matrix_school = df_matrix_school.merge(df_sek_clean, on="_school_key", how="left")

                        df_matrix_school["nama_sekolah"] = df_matrix_school["nama_sekolah_master"].fillna(df_matrix_school["_school_key"])
                        df_matrix_school["nama_kabupaten"] = df_matrix_school["nama_kabupaten_master"].fillna("-")
                        df_matrix_school["kd_prop"] = df_matrix_school["kd_prop_master"].fillna(df_matrix_school["_prop_key_user"])
                        df_matrix_school["nama_provinsi"] = df_matrix_school["nama_provinsi_master"].fillna(df_matrix_school["kd_prop"])

                        df_matrix_school["kd_prop"] = df_matrix_school["kd_prop"].astype(str).str.strip().str.replace(".0", "", regex=False).str.rstrip(",").str.zfill(2)
                        df_matrix_school["nama_provinsi"] = df_matrix_school["nama_provinsi"].astype(str).str.strip().str.rstrip(",").str.strip().str.upper()

                    except Exception as e:
                        st.warning(f"Catatan: Pemrosesan data sekolah/provinsi mengalami kendala: {e}")

                st.session_state["df_matrix_school"] = df_matrix_school

                progress_bar.progress(100)
                t1 = time.time()
                status.update(
                    label=f"✅ Pengolahan Data Selesai dalam {t1 - t0:.2f} detik!",
                    state="complete",
                    expanded=False,
                )

                st.session_state["data_processed"] = True
                st.rerun()
            else:
                status.update(label="❌ Validasi Data Gagal!", state="error", expanded=True)
                st.session_state["data_processed"] = False

# ==========================================
# 6. Tampilan Utama Dashboard
# ==========================================
if not st.session_state.get("data_processed", False):
    st.info(
        "👋 **Petunjuk:** Unggah berkas sekaligus (CSV/XLSX/ZIP) pada wadah unggah"
        " di sebelah kiri, lalu klik tombol **🚀 Proses Data**."
    )
else:
    val_result = st.session_state["val_result"]
    dfs = val_result["dataframes"]
    df_matrix = st.session_state.get("df_matrix")
    ctt_res = st.session_state.get("ctt_res")
    df_matrix_school = st.session_state.get("df_matrix_school", pd.DataFrame())

    tab_val, tab_scoring, tab_ctt, tab_irt, tab_school = st.tabs([
        "📋 1. Validasi Data",
        "💯 2. Scoring Engine",
        "📈 3. Analisis CTT",
        "🎯 4. Analisis IRT",
        "🏫 5. Analisis Per Sekolah",
    ])

    # --- TAB 1: VALIDASI DATA ---
    with tab_val:
        st.subheader("Hasil Pemeriksaan Ingestion Data")
        for log in val_result["logs"]:
            if "❌" in log:
                st.error(log)
            elif "⚠️" in log:
                st.warning(log)
            elif "---" in log:
                st.markdown(f"**{log}**")
            else:
                st.success(log)

        if val_result["status"]:
            st.success("🎉 Data berhasil divalidasi dan siap untuk diproses!")
            st.divider()
            preview_key = st.selectbox(
                "Pilih Tabel untuk Ditinjau:", list(val_result["dataframes"].keys())
            )
            if (
                preview_key in val_result["dataframes"]
                and val_result["dataframes"][preview_key] is not None
            ):
                df_preview = val_result["dataframes"][preview_key].head(10).copy()
                df_preview = df_preview.loc[:, ~df_preview.columns.duplicated()]
                df_preview.insert(0, "No.", range(1, 1 + len(df_preview)))
                st.dataframe(df_preview, use_container_width=True, hide_index=True)

    # --- TAB 2: SCORING ENGINE ---
    with tab_scoring:
        st.subheader("Hasil Skoring Dikotomus (0 / 1)")
        id_col = df_matrix.columns[0]
        skor_col_name = "skor_mentah"

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Responden", f"{len(df_matrix):,}")

        avg_skor = df_matrix[skor_col_name].mean()
        avg_soal = df_matrix["Jumlah_Soal"].mean()
        c2.metric("Rata-rata Skor Mentah", f"{avg_skor:.2f} / {avg_soal:.1f}")

        avg_konversi = df_matrix["Nilai_Konversi"].mean()
        c3.metric("Rata-rata Nilai Konversi", f"{avg_konversi:.2f}")
        st.divider()

        df_chart = df_matrix.sample(n=50000, random_state=42) if len(df_matrix) > 50000 else df_matrix
        fig_score = render_score_histogram(df_chart)
        st.plotly_chart(fig_score, use_container_width=True)

        df_display_scoring = df_matrix.copy()

        selected_cols = []
        for col in [id_col, "tahun", "username", "Jumlah_Soal", "skor_mentah", "Nilai_Konversi"]:
            if col in df_display_scoring.columns and col not in selected_cols:
                selected_cols.append(col)

        df_display_scoring = df_display_scoring[selected_cols].head(100).copy()

        rename_map = {
            id_col: "Username",
            "username": "Username",
            "Jumlah_Soal": "Jumlah Soal",
            "skor_mentah": "Skor Mentah",
            "Nilai_Konversi": "Nilai Konversi",
        }
        df_display_scoring.rename(columns=rename_map, inplace=True)
        df_display_scoring = df_display_scoring.loc[:, ~df_display_scoring.columns.duplicated()].copy()

        if "No." not in df_display_scoring.columns:
            df_display_scoring.insert(0, "No.", range(1, 1 + len(df_display_scoring)))

        st.dataframe(df_display_scoring, use_container_width=True, hide_index=True)
        st.caption("⚡ Menampilkan 100 sampel data pertama untuk efisiensi memori UI.")

    # --- TAB 3: ANALISIS CTT ---
    with tab_ctt:
        st.subheader("Analisis Psikometri Klasik (CTT)")
        summary = ctt_res["summary"].copy()
        df_items = ctt_res["item_stats"].copy()

        if not df_items.empty and len(df_items) > 0:
            col_item_name = df_items.columns[0]
            for col_c in ["Kode_Soal", "Item", "item", "kode_soal"]:
                if col_c in df_items.columns:
                    col_item_name = col_c
                    break

            excluded_names = [
                "jumlah_soal", "jumlahsoal", "skor_mentah", "skormentah",
                "nilai_konversi", "skor_total", "username", "namapeserta"
            ]
            df_items = df_items[
                ~df_items[col_item_name].astype(str).str.strip().str.lower().isin(excluded_names)
            ].copy()

            summary["n_soal"] = len(df_items)

        skor_col_name = "skor_mentah"
        skor_vals = df_matrix[skor_col_name].dropna()
        konversi_vals = (
            df_matrix["Nilai_Konversi"].dropna() if "Nilai_Konversi" in df_matrix.columns else pd.Series()
        )

        mean_skor_total = skor_vals.mean() if not skor_vals.empty else 0.0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Jumlah Peserta (N)", f"{summary['n_peserta']:,}")
        m2.metric("Jumlah Soal (K)", summary["n_soal"])
        m3.metric("Cronbach's Alpha (α)", f"{summary['cronbach_alpha']:.3f}")
        m4.metric("Rata-Rata Skor Mentah", f"{mean_skor_total:.2f}")
        st.divider()

        st.markdown("#### 📊 Statistik Deskriptif Skor Peserta (Metode CTT)")

        desc_ctt_data = {
            "Metrik Statistik": [
                "Jumlah Peserta (N)", "Rata-rata (Mean)", "Standar Deviasi (SD)",
                "Nilai Minimum", "Kuartil 1 (Q1 - 25%)", "Median (Q2 - 50%)",
                "Kuartil 3 (Q3 - 75%)", "Nilai Maksimum", "Kemiringan (Skewness)",
                "Keruncingan (Kurtosis)"
            ],
            "Skor Mentah": [
                f"{len(skor_vals):,}", f"{skor_vals.mean():.2f}", f"{skor_vals.std():.2f}",
                f"{skor_vals.min():.2f}", f"{skor_vals.quantile(0.25):.2f}", f"{skor_vals.median():.2f}",
                f"{skor_vals.quantile(0.75):.2f}", f"{skor_vals.max():.2f}", f"{skor_vals.skew():.3f}",
                f"{skor_vals.kurtosis():.3f}"
            ],
        }

        if not konversi_vals.empty:
            desc_ctt_data["Nilai Konversi (0 - 100)"] = [
                f"{len(konversi_vals):,}", f"{konversi_vals.mean():.2f}", f"{konversi_vals.std():.2f}",
                f"{konversi_vals.min():.2f}", f"{konversi_vals.quantile(0.25):.2f}", f"{konversi_vals.median():.2f}",
                f"{konversi_vals.quantile(0.75):.2f}", f"{konversi_vals.max():.2f}", f"{konversi_vals.skew():.3f}",
                f"{konversi_vals.kurtosis():.3f}"
            ]

        df_desc_ctt = pd.DataFrame(desc_ctt_data)
        st.dataframe(df_desc_ctt, use_container_width=True, hide_index=True)
        st.divider()

        ctt_person_cols = [
            c for c in df_matrix.columns
            if c.lower() in ["username", "user_id", "id_peserta", "tahun", "jumlah_soal", "skor_mentah", "skor_total", "nilai_konversi"]
        ]
        if not ctt_person_cols:
            ctt_person_cols = df_matrix.columns[:5].tolist()

        df_ctt_person = df_matrix[ctt_person_cols].copy()
        
        rename_ctt = {
            df_matrix.columns[0]: "ID Peserta",
            "username": "Username",
            "tahun": "Tahun",
            "Jumlah_Soal": "Jumlah Soal",
            skor_col_name: "Skor Mentah",
            "Nilai_Konversi": "Nilai Konversi (0-100)"
        }
        df_ctt_person = df_ctt_person.rename(columns=rename_ctt)
        df_ctt_person = df_ctt_person.loc[:, ~df_ctt_person.columns.duplicated()]

        st.markdown("#### 📄 Unduh Data Skor & Nilai Konversi Peserta (Metode CTT)")
        csv_ctt_bytes = convert_df_to_csv_bytes(df_ctt_person)
        st.download_button(
            label="📥 Download Skor & Nilai Konversi Peserta - CTT (.csv)",
            data=csv_ctt_bytes,
            file_name="Hasil_Skor_dan_Konversi_Peserta_CTT.csv",
            mime="text/csv",
            type="primary",
            use_container_width=False,
            key="btn_dl_ctt_csv"
        )
        st.divider()

        if not df_items.empty and len(df_items) > 0:
            counts_map = {}
            if "respon" in dfs and dfs["respon"] is not None:
                df_resp = dfs["respon"]

                list_soal_col = next(
                    (c for c in df_resp.columns if c.lower().strip() in ["list_soal", "listsoal", "daftar_soal", "kode_soal"]),
                    None
                )

                if list_soal_col:
                    counter = Counter()
                    raw_list_soal = df_resp[list_soal_col].dropna().astype(str).values

                    for row in raw_list_soal:
                        items = [s.strip() for s in row.split(",") if s.strip()]
                        counter.update(items)

                    counts_map = dict(counter)

            if not counts_map:
                non_null_counts = df_matrix.notna().sum()
                counts_map = non_null_counts.to_dict()

            total_n = len(df_matrix)
            df_items["Jumlah_Peserta"] = df_items[col_item_name].map(
                lambda x: counts_map.get(x, total_n)
            )

            p_col_candidates = [
                c for c in df_items.columns
                if any(k in c.lower() for k in ["kesukaran", "p_value", "p-value", "proporsi_benar", "p_val"]) or c.lower() == "p"
            ]
            p_col = p_col_candidates[0] if len(p_col_candidates) > 0 else df_items.columns[1]

            r_col_candidates = [
                c for c in df_items.columns
                if any(k in c.lower() for k in ["daya_beda", "rit", "rbis", "r_tabel", "r_hitung", "dayabeda", "d"]) or c.lower() == "r"
            ]
            r_col = r_col_candidates[0] if len(r_col_candidates) > 0 else df_items.columns[-1]

            fig_ctt = render_ctt_scatter(df_items, p_col, r_col)
            st.plotly_chart(fig_ctt, use_container_width=True)

            cl, cr = st.columns([6, 4])
            with cl:
                st.write("**Tabel Statistik Item (CTT):**")
                df_items_display = df_items.copy()
                df_items_display = df_items_display.loc[:, ~df_items_display.columns.duplicated()]

                cols_order = [col_item_name, "Jumlah_Peserta"] + [
                    c for c in df_items_display.columns if c not in [col_item_name, "Jumlah_Peserta", "No."]
                ]
                df_items_display = df_items_display[cols_order]

                if "No." not in df_items_display.columns:
                    df_items_display.insert(0, "No.", range(1, 1 + len(df_items_display)))

                st.dataframe(df_items_display, use_container_width=True, hide_index=True)

            with cr:
                if not ctt_res["distractor_stats"].empty:
                    st.write("**Tabel Analisis Pengecoh (Distractor):**")
                    df_dist_display = ctt_res["distractor_stats"].copy()

                    df_dist_display = df_dist_display[
                        ~df_dist_display[df_dist_display.columns[0]]
                        .astype(str)
                        .str.lower()
                        .isin(["jumlah_soal", "jumlahsoal"])
                    ].copy()

                    df_dist_display = df_dist_display.loc[:, ~df_dist_display.columns.duplicated()]
                    if "No." not in df_dist_display.columns:
                        df_dist_display.insert(0, "No.", range(1, 1 + len(df_dist_display)))
                    st.dataframe(df_dist_display, use_container_width=True, hide_index=True)

    # --- TAB 4: ANALISIS IRT ---
    with tab_irt:
        st.subheader("Analisis Item Response Theory (IRT)")

        col_m1, col_m2, col_m3 = st.columns([2, 1, 1])

        with col_m1:
            selected_model = st.radio(
                "Pilih Model IRT:",
                options=["Rasch", "1PL", "2PL"],
                key="selected_model_irt_radio",
                horizontal=True,
            )

        with col_m2:
            scale_min = st.number_input("Skala Nilai Min:", value=200, step=50, key="scale_min_input")

        with col_m3:
            scale_max = st.number_input("Skala Nilai Max:", value=800, step=50, key="scale_max_input")

        # Running Jalur IRT Sesi Tunggal / Agregat
        irt_res = run_irt_analysis(df_matrix, model_type=selected_model)

        # =========================================================
        # INTEGRASI PENGOLAHAN EQUATING MULTI-SESI (OPTIMIZED)
        # =========================================================
        df_respon_raw = dfs["respon"]
        col_sesi_candidate = next(
            (c for c in df_respon_raw.columns if c.lower().strip() in ["kode_sesi", "kodesesi", "sesi", "session_id", "session"]),
            None
        )

        equating_meta = {"is_multi_session": False}

        if col_sesi_candidate:
            unique_sessions = sorted(df_respon_raw[col_sesi_candidate].dropna().unique())
            if len(unique_sessions) > 1:
                st.markdown("---")
                st.markdown("### 🔄 Penyetaraan Multi-Sesi (Multi-Session Equating)")
                
                base_sess = st.selectbox(
                    "Pilih Sesi Acuan (Base Session):",
                    options=unique_sessions,
                    index=0,
                    help="Sesi acuan dijadikan standar skala. Sesi lainnya akan diselaraskan ke skala sesi acuan ini."
                )

                # Siapkan IRT result per sesi menggunakan fungsi cached fast-lookup
                user_id_col = next(
                    (c for c in df_respon_raw.columns if c.lower().strip() in ["username", "user_id", "id_peserta"]),
                    df_respon_raw.columns[0]
                )
                
                session_irt_results = {}
                for sess in unique_sessions:
                    users_in_sess = df_respon_raw[df_respon_raw[col_sesi_candidate] == sess][user_id_col].astype(str).str.strip().str.lower().tolist()
                    id_col_m = df_matrix.columns[0]
                    df_sub_matrix = df_matrix[df_matrix[id_col_m].astype(str).str.strip().str.lower().isin(users_in_sess)].copy()
                    
                    if not df_sub_matrix.empty:
                        # PANGGIL FUNGSI TER-CACHE UNTUK MENGHINDARI SLOW RE-FITTING
                        session_irt_results[sess] = run_cached_session_irt(df_sub_matrix, model_type=selected_model)

                equated_results, equating_meta = perform_multi_session_equating(
                    df_responses=df_respon_raw,
                    session_irt_results=session_irt_results,
                    base_session_id=base_sess
                )

                if equating_meta.get("is_multi_session", False):
                    st.subheader("📊 Hasil Evaluasi Psikometri & Penyetaraan Multi-Sesi")
                    
                    for sess_id, report in equating_meta["reports"].items():
                        with st.expander(f"📌 Ringkasan Penyetaraan: Sesi {sess_id} ➔ Sesi {base_sess}", expanded=True):
                            if report['status'] == 'SUCCESS':
                                col1, col2, col3 = st.columns(3)
                                col1.metric("Soal Jangkar", f"{report['n_anchor']} Butir", f"{report['anchor_ratio']:.1f}%")
                                col2.metric("Korelasi Kesukaran (r)", f"{report['correlation']:.2f}")
                                col3.metric("Konstanta (A / B)", f"{report['A']:.3f} / {report['B']:.3f}")
                                
                                st.markdown("**Catatan Evaluasi Psikometri:**")
                                for warn in report['warnings']:
                                    st.markdown(warn)
                            else:
                                st.error(report['warnings'][0])
                st.markdown("---")

        id_col = df_matrix.columns[0]
        skor_col_name = "skor_mentah"

        df_params = irt_res["item_params"].copy()
        df_persons = irt_res["person_params"].copy()

        if not df_params.empty:
            param_item_col = df_params.columns[0]
            df_params = df_params[
                ~df_params[param_item_col].astype(str).str.lower().isin(["jumlah_soal", "jumlahsoal"])
            ].copy()

        # Tentukan kolom theta asli
        theta_col = None
        if not df_persons.empty:
            for col in df_persons.columns:
                if col.lower() in ["kemampuan (theta θ)", "theta", "theta_ability", "ability", "skor_theta"]:
                    if not df_persons[col].isna().all():
                        theta_col = col
                        break
            if theta_col is None:
                numeric_cols = df_persons.select_dtypes(include=[np.number]).columns
                theta_col = (
                    numeric_cols[0] if len(numeric_cols) > 0
                    else (df_persons.columns[1] if len(df_persons.columns) > 1 else df_persons.columns[0])
                )

        t_min = df_persons[theta_col].min() if (theta_col and not df_persons.empty) else 0
        t_max = df_persons[theta_col].max() if (theta_col and not df_persons.empty) else 0

        if (
            pd.notna(t_min)
            and pd.notna(t_max)
            and t_max != t_min
            and theta_col in df_persons.columns
        ):
            theta_arr = df_persons[theta_col].values
            df_persons["Nilai_Scaled"] = np.round(
                scale_min + ((theta_arr - t_min) / (t_max - t_min)) * (scale_max - scale_min),
                2,
            )
        else:
            df_persons["Nilai_Scaled"] = (scale_min + scale_max) / 2.0

        df_persons_display = df_persons.copy()
        if not df_persons_display.empty:
            person_id_col = df_persons_display.columns[0]
            score_map = dict(zip(df_matrix[id_col].astype(str), df_matrix[skor_col_name]))
            df_persons_display["Skor Mentah"] = df_persons_display[person_id_col].astype(str).map(score_map)

            b_candidates = [
                c for c in df_params.columns
                if c.lower() in ["b", "kesukaran", "difficulty", "b_param", "tingkat_kesukaran (b)"]
            ]
            b_col = b_candidates[0] if len(b_candidates) > 0 else (
                df_params.columns[1] if len(df_params.columns) > 1 else df_params.columns[0]
            )

            df_fit = calculate_person_fit(df_matrix, df_params, b_col=b_col)

            df_persons_display[person_id_col] = df_persons_display[person_id_col].astype(str).str.strip()
            df_fit[id_col] = df_fit[id_col].astype(str).str.strip()

            df_persons_display = df_persons_display.merge(
                df_fit, left_on=person_id_col, right_on=id_col, how="left"
            )

            rename_dict = {}
            if person_id_col != "ID Peserta":
                rename_dict[person_id_col] = "ID Peserta"
            if "Nilai_Scaled" in df_persons_display.columns:
                rename_dict["Nilai_Scaled"] = "Nilai Konversi"
            if theta_col and theta_col != "Kemampuan (Theta θ)":
                rename_dict[theta_col] = "Kemampuan (Theta θ)"

            df_persons_display = df_persons_display.rename(columns=rename_dict)
            df_persons_display = df_persons_display.loc[:, ~df_persons_display.columns.duplicated()]

            target_cols = [
                "ID Peserta", "Skor Mentah", "Kemampuan (Theta θ)",
                "Nilai Konversi", "Outfit_MSQ", "Status_Pola_Jawab",
            ]
            if "SEM" in df_persons_display.columns:
                target_cols.append("SEM")

            df_irt_final = df_persons_display[
                [c for c in target_cols if c in df_persons_display.columns]
            ].copy()
            df_irt_final = df_irt_final.loc[:, ~df_irt_final.columns.duplicated()]

            if "No." not in df_irt_final.columns:
                df_irt_final.insert(0, "No.", range(1, 1 + len(df_irt_final)))
        else:
            df_irt_final = pd.DataFrame()

        # TABEL STATISTIK DESKRIPTIF ESTIMASI ABILITY (THETA)
        if not df_persons.empty and theta_col in df_persons.columns:
            st.markdown("#### 📊 Statistik Deskriptif Estimasi Ability (Theta θ)")
            
            theta_vals = pd.to_numeric(df_persons[theta_col], errors="coerce").dropna()
            scaled_vals = (
                pd.to_numeric(df_persons["Nilai_Scaled"], errors="coerce").dropna()
                if "Nilai_Scaled" in df_persons.columns
                else pd.Series()
            )

            desc_data = {
                "Metrik Statistik": [
                    "Jumlah Peserta (N)", "Rata-rata (Mean)", "Standar Deviasi (SD)",
                    "Nilai Minimum", "Kuartil 1 (Q1 - 25%)", "Median (Q2 - 50%)",
                    "Kuartil 3 (Q3 - 75%)", "Nilai Maksimum", "Kemiringan (Skewness)",
                    "Keruncingan (Kurtosis)",
                ],
                "Skala Theta (θ)": [
                    f"{len(theta_vals):,}",
                    f"{theta_vals.mean():.3f}",
                    f"{theta_vals.std():.3f}",
                    f"{theta_vals.min():.3f}",
                    f"{theta_vals.quantile(0.25):.3f}",
                    f"{theta_vals.median():.3f}",
                    f"{theta_vals.quantile(0.75):.3f}",
                    f"{theta_vals.max():.3f}",
                    f"{theta_vals.skew():.3f}",
                    f"{theta_vals.kurtosis():.3f}",
                ],
            }

            if not scaled_vals.empty:
                desc_data[f"Skala Konversi ({scale_min} - {scale_max})"] = [
                    f"{len(scaled_vals):,}",
                    f"{scaled_vals.mean():.2f}",
                    f"{scaled_vals.std():.2f}",
                    f"{scaled_vals.min():.2f}",
                    f"{scaled_vals.quantile(0.25):.2f}",
                    f"{scaled_vals.median():.2f}",
                    f"{scaled_vals.quantile(0.75):.2f}",
                    f"{scaled_vals.max():.2f}",
                    f"{scaled_vals.skew():.3f}",
                    f"{scaled_vals.kurtosis():.3f}",
                ]

            df_desc = pd.DataFrame(desc_data)
            st.dataframe(df_desc, use_container_width=True, hide_index=True)
            st.divider()

        # GRAFIK DISTRIBUSI NILAI KONVERSI (IRT)
        if not df_persons.empty and "Nilai_Scaled" in df_persons.columns:
            st.markdown(f"#### 📈 Grafik Distribusi Nilai Konversi Peserta (Model: {selected_model})")
            
            chart_data = (
                df_persons["Nilai_Scaled"].sample(n=30000, random_state=42)
                if len(df_persons) > 30000
                else df_persons["Nilai_Scaled"]
            ).dropna()

            fig_dist_irt = px.histogram(
                chart_data,
                x="Nilai_Scaled",
                nbins=30,
                title=f"<b>Distribusi Nilai Konversi Peserta (Skala {scale_min} - {scale_max})</b>",
                labels={"Nilai_Scaled": "Nilai Konversi", "count": "Jumlah Peserta"},
                color_discrete_sequence=["#00CC96"],
                marginal="box",
            )

            fig_dist_irt.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="<b>Nilai Konversi</b>",
                yaxis_title="<b>Jumlah Peserta</b>",
                bargap=0.08,
            )

            st.plotly_chart(fig_dist_irt, use_container_width=True)
            st.divider()

        if not df_params.empty:
            b_candidates = [
                c for c in df_params.columns
                if c.lower() in ["b", "kesukaran", "difficulty", "b_param", "tingkat_kesukaran (b)"]
            ]
            b_col = b_candidates[0] if len(b_candidates) > 0 else (
                df_params.columns[1] if len(df_params.columns) > 1 else df_params.columns[0]
            )

            item_col_name = df_params.columns[0]
            all_items = df_params[item_col_name].astype(str).tolist()
            selected_items = st.multiselect(
                "Filter Soal untuk Menampilkan ICC:",
                options=all_items,
                default=all_items[:5] if len(all_items) >= 5 else all_items,
                key="icc_filter_soal",
            )

            fig_icc = render_irt_icc(df_params, selected_items, selected_model, b_col)
            st.plotly_chart(fig_icc, use_container_width=True)

            col_chart1, col_chart2 = st.columns(2)
            with col_chart1:
                fig_tif = render_irt_tif(df_params, selected_model, b_col)
                st.plotly_chart(fig_tif, use_container_width=True)
            with col_chart2:
                df_persons_wright = (
                    df_persons.sample(n=5000, random_state=42)
                    if len(df_persons) > 5000
                    else df_persons
                )
                fig_wright = render_wright_map(
                    df_persons_wright, df_params, theta_col, b_col
                )
                st.plotly_chart(fig_wright, use_container_width=True)

        st.divider()
        col_irt_item, col_irt_person = st.columns(2)
        with col_irt_item:
            st.write("**Parameter Soal (IRT):**")
            df_params_display = df_params.copy()
            df_params_display = df_params_display.loc[:, ~df_params_display.columns.duplicated()]
            if "No." not in df_params_display.columns:
                df_params_display.insert(0, "No.", range(1, 1 + len(df_params_display)))
            st.dataframe(df_params_display, use_container_width=True, hide_index=True)

        with col_irt_person:
            st.write("**Estimasi Kemampuan Peserta & Person Fit (Anomali):**")
            st.dataframe(
                df_irt_final.head(100), use_container_width=True, hide_index=True
            )
            st.caption("⚡ Menampilkan 100 sampel data pertama untuk efisiensi memori UI.")

        # UNDUH HASIL ANALISIS (SESUAIKAN ARGUMEN DENGAN EXCEL EXPORTER FIX)
        st.divider()
        st.subheader("📥 Unduh Hasil Analisis IRT & Rekap Excel")
        col_dl1, col_dl2 = st.columns(2)

        with col_dl1:
            excel_data = create_excel_report(
                df_matrix=df_matrix,
                df_items=df_items,
                df_dist=ctt_res.get("distractor_stats", pd.DataFrame()),
                df_params=df_params,
                df_persons_irt=df_irt_final,
                equating_meta=equating_meta
            )
            st.download_button(
                label="📊 Download Ringkasan Soal & Item (.xlsx)",
                data=excel_data,
                file_name=f"Laporan_Psikometri_Item_{selected_model}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="btn_dl_excel",
            )

        with col_dl2:
            csv_data_person = convert_df_to_csv_bytes(df_irt_final)
            st.download_button(
                label="📄 Download Data Lengkap Peserta IRT (.csv)",
                data=csv_data_person,
                file_name=f"Hasil_Nilai_Peserta_Lengkap_{selected_model}.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True,
                key="btn_dl_csv",
            )

    # --- TAB 5: ANALISIS PER SEKOLAH ---
    with tab_school:
        st.subheader("🏫 Hasil Analisis Statistik Per Sekolah")

        if df_matrix_school.empty or "nama_sekolah" not in df_matrix_school.columns:
            st.info(
                "💡 **Informasi:** Berkas **Master Sekolah** (`sekolah`) belum diunggah atau "
                "data `username` tidak mengandung informasi sekolah/provinsi."
            )
        else:
            st.markdown("#### 🔍 Filter Wilayah & Jumlah Peserta")

            col_f1, col_f2 = st.columns([3, 1])

            prov_dict = {}

            def clean_str(val):
                if pd.isna(val):
                    return ""
                s = str(val).strip().rstrip(",").strip()
                return s

            if "sekolah" in dfs and dfs["sekolah"] is not None and not dfs["sekolah"].empty:
                df_sek_raw = dfs["sekolah"].copy()
                df_sek_raw.columns = [str(c).strip().lower() for c in df_sek_raw.columns]

                col_kd = next((c for c in df_sek_raw.columns if c in ["kd_prop", "kode_provinsi", "kd_provinsi", "kode_prop", "kd_prov"]), None)
                col_nm = next((c for c in df_sek_raw.columns if c in ["nama_provinsi", "namaprovinsi", "nama_prov", "provinsi"]), None)

                if col_kd and col_nm:
                    df_prov_master = df_sek_raw[[col_kd, col_nm]].dropna().drop_duplicates()
                    for _, row in df_prov_master.iterrows():
                        kd_str = clean_str(row[col_kd]).replace(".0", "").zfill(2)
                        nm_str = clean_str(row[col_nm]).upper()
                        if kd_str and nm_str and kd_str not in prov_dict:
                            prov_dict[kd_str] = nm_str

            if "kd_prop" in df_matrix_school.columns and "nama_provinsi" in df_matrix_school.columns:
                df_prov_pairs = df_matrix_school[["kd_prop", "nama_provinsi"]].dropna().drop_duplicates()
                for _, row in df_prov_pairs.iterrows():
                    kd_str = clean_str(row["kd_prop"]).replace(".0", "").zfill(2)
                    nm_str = clean_str(row["nama_provinsi"]).upper()
                    if kd_str and nm_str:
                        if kd_str not in prov_dict or prov_dict[kd_str] in ["", "-", kd_str]:
                            prov_dict[kd_str] = nm_str

            prov_options = [f"{k} - {v}" for k, v in sorted(prov_dict.items())]

            with col_f1:
                selected_prov_options = st.multiselect(
                    "Filter Berdasarkan Provinsi (Kode - Nama Provinsi):",
                    options=prov_options,
                    default=[],
                    key="filter_provinsi_single",
                    placeholder="Semua Provinsi",
                )

            with col_f2:
                min_peserta = st.number_input(
                    "Minimal Jumlah Peserta:",
                    min_value=1,
                    value=1,
                    step=1,
                    key="filter_min_peserta",
                    help="Tampilkan hanya sekolah yang memiliki jumlah peserta minimal sejumlah angka ini.",
                )

            df_filtered_school = df_matrix_school.copy()
            if selected_prov_options:
                selected_codes = [opt.split(" - ")[0].strip() for opt in selected_prov_options]
                
                df_filtered_school["_kd_prop_clean"] = (
                    df_filtered_school["kd_prop"]
                    .astype(str)
                    .str.strip()
                    .str.replace(".0", "", regex=False)
                    .str.rstrip(",")
                    .str.zfill(2)
                )
                df_filtered_school = df_filtered_school[
                    df_filtered_school["_kd_prop_clean"].isin(selected_codes)
                ]

            if df_filtered_school.empty:
                st.warning("⚠️ Tidak ada data sekolah yang memenuhi kriteria filter provinsi yang dipilih.")
            else:
                id_user_col = df_filtered_school.columns[0]
                for c_u in ["username", "user_id", "id_peserta"]:
                    if c_u in df_filtered_school.columns:
                        id_user_col = c_u
                        break

                df_school_summary = df_filtered_school.groupby(
                    ["_school_key", "nama_sekolah", "nama_kabupaten", "nama_provinsi"],
                    as_index=False
                ).agg(
                    Jumlah_Peserta=(id_user_col, "count"),
                    Rata_Skor_Mentah=("skor_mentah", "mean"),
                    Rata_Nilai_Konversi=("Nilai_Konversi", "mean"),
                    Nilai_Min=("Nilai_Konversi", "min"),
                    Nilai_Max=("Nilai_Konversi", "max"),
                    Std_Deviasi=("Nilai_Konversi", "std")
                )

                df_school_summary = df_school_summary[
                    df_school_summary["Jumlah_Peserta"] >= min_peserta
                ].copy()

                if df_school_summary.empty:
                    st.warning(f"⚠️ Tidak ada sekolah yang memiliki jumlah peserta minimal {min_peserta}.")
                else:
                    df_school_summary.rename(
                        columns={
                            "_school_key": "Kode_Sekolah_9_Digit",
                            "nama_sekolah": "Nama_Sekolah",
                            "nama_kabupaten": "Nama_Kabupaten",
                            "nama_provinsi": "Nama_Provinsi"
                        },
                        inplace=True
                    )
                    df_school_summary = df_school_summary.round(2)
                    df_school_summary["Std_Deviasi"] = df_school_summary["Std_Deviasi"].fillna(0.0)

                    st.divider()

                    s_c1, s_c2, s_c3, s_c4 = st.columns(4)
                    s_c1.metric("Total Sekolah Terdata", f"{len(df_school_summary):,}")
                    s_c2.metric("Total Peserta Terfilter", f"{df_school_summary['Jumlah_Peserta'].sum():,}")
                    s_c3.metric("Rata-rata Konversi Tertinggi", f"{df_school_summary['Rata_Nilai_Konversi'].max():.2f}")
                    s_c4.metric("Rata-rata Konversi Terendah", f"{df_school_summary['Rata_Nilai_Konversi'].min():.2f}")
                    st.divider()

                    top_schools = df_school_summary.sort_values(by="Rata_Nilai_Konversi", ascending=True).tail(15)

                    fig_school_bar = px.bar(
                        top_schools,
                        x="Rata_Nilai_Konversi",
                        y="Nama_Sekolah",
                        orientation="h",
                        text="Rata_Nilai_Konversi",
                        title=f"<b>15 Sekolah Teratas (Min. {min_peserta} Peserta) berdasarkan Rata-Rata Nilai Konversi</b>",
                        labels={
                            "Rata_Nilai_Konversi": "Rata-rata Nilai Konversi",
                            "Nama_Sekolah": "Nama Sekolah",
                        },
                        color="Rata_Nilai_Konversi",
                        color_continuous_scale="Blues",
                        hover_data=["Nama_Provinsi", "Nama_Kabupaten", "Jumlah_Peserta"]
                    )

                    fig_school_bar.update_layout(
                        template="plotly_dark",
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        xaxis_title="<b>Rata-rata Nilai Konversi (0 - 100)</b>",
                        yaxis_title="<b>Sekolah</b>",
                        margin=dict(l=20, r=20, t=50, b=40),
                    )

                    st.plotly_chart(fig_school_bar, use_container_width=True)
                    st.divider()

                    st.markdown("#### 📋 Tabel Rincian Ringkasan Per Sekolah")

                    df_school_display = df_school_summary.sort_values(by="Rata_Nilai_Konversi", ascending=False).copy()

                    cols_order = [
                        "Kode_Sekolah_9_Digit", "Nama_Sekolah", "Nama_Kabupaten", "Nama_Provinsi",
                        "Jumlah_Peserta", "Rata_Skor_Mentah", "Rata_Nilai_Konversi", "Nilai_Min", "Nilai_Max", "Std_Deviasi"
                    ]
                    cols_order = [c for c in cols_order if c in df_school_display.columns]
                    df_school_display = df_school_display[cols_order]

                    if "No." not in df_school_display.columns:
                        df_school_display.insert(0, "No.", range(1, 1 + len(df_school_display)))

                    st.dataframe(df_school_display, use_container_width=True, hide_index=True)

                    csv_school_bytes = convert_df_to_csv_bytes(df_school_display)
                    st.download_button(
                        label="📥 Download Ringkasan Rekap Per Sekolah (.csv)",
                        data=csv_school_bytes,
                        file_name="Rekap_Analisis_Hasil_Per_Sekolah.csv",
                        mime="text/csv",
                        type="primary",
                        key="btn_dl_school_csv"
                    )