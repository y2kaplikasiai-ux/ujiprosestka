import io
import time
import zipfile

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import ctt_analysis
from scoring import process_scoring
from styles import load_custom_css
from validators import validate_7_files

# Import modul UI dari folder views
from views.tab_ctt import render_tab_ctt
from views.tab_irt import render_tab_irt
from views.tab_school import render_tab_school
from views.tab_scoring import render_tab_scoring
from views.tab_validation import render_tab_validation

# 1. Konfigurasi Halaman Streamlit
st.set_page_config(
    page_title="Dashboard Analisis Psikometri TKA",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 2. Memuat CSS Custom
load_custom_css()


def inject_header_timer(running=False, total_seconds=0):
    """Injects a single live floating timer directly into Streamlit's top header bar."""
    if running:
        js_code = """
        <script>
            var parentDoc = window.parent.document;
            var header = parentDoc.querySelector('header[data-testid="stHeader"]');
            
            if (header) {
                var existingTimer = parentDoc.getElementById("top_header_timer");
                if (existingTimer) {
                    existingTimer.remove();
                }
                
                if (!parentDoc.getElementById("timer_spin_style")) {
                    var styleEl = parentDoc.createElement("style");
                    styleEl.id = "timer_spin_style";
                    styleEl.innerHTML = `
                        @keyframes spinIcon {
                            0% { transform: rotate(0deg); }
                            100% { transform: rotate(360deg); }
                        }
                        .timer-spinning-icon {
                            display: inline-block;
                            animation: spinIcon 2s linear infinite;
                        }
                    `;
                    parentDoc.head.appendChild(styleEl);
                }
                
                var timerDiv = parentDoc.createElement("div");
                timerDiv.id = "top_header_timer";
                timerDiv.style.cssText = "position: absolute; right: 240px; top: 10px; z-index: 999999; display: flex; align-items: center; gap: 8px; background: #1e293b; padding: 4px 12px; border-radius: 6px; border: 1px solid #334155; font-family: monospace; color: #f8fafc;";
                timerDiv.innerHTML = '<span class="timer-spinning-icon" style="font-size:0.9rem;">⏳</span> <span id="st_top_clock" style="font-size:1.1rem; font-weight:bold;">00:00:00</span>';
                
                header.appendChild(timerDiv);
                
                if (window.parent.liveTimerInterval) {
                    clearInterval(window.parent.liveTimerInterval);
                }
                
                var startTimestamp = Date.now();
                window.parent.liveTimerInterval = setInterval(function() {
                    var elapsedMs = Date.now() - startTimestamp;
                    var totalSecs = Math.floor(elapsedMs / 1000);
                    var hrs = Math.floor(totalSecs / 3600);
                    var mins = Math.floor((totalSecs % 3600) / 60);
                    var secs = totalSecs % 60;
                    
                    var hStr = String(hrs).padStart(2, '0');
                    var mStr = String(mins).padStart(2, '0');
                    var sStr = String(secs).padStart(2, '0');
                    
                    var el = parentDoc.getElementById("st_top_clock");
                    if (el) {
                        el.innerText = hStr + ":" + mStr + ":" + sStr;
                    }
                }, 1000);
            }
        </script>
        """
        components.html(js_code, height=0, width=0)
    else:
        hrs = int(total_seconds // 3600)
        mins = int((total_seconds % 3600) // 60)
        secs = int(total_seconds % 60)
        time_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"
        status_txt = "✅" if total_seconds > 0 else "⏱️"

        js_code = f"""
        <script>
            var parentDoc = window.parent.document;
            if (window.parent.liveTimerInterval) {{
                clearInterval(window.parent.liveTimerInterval);
            }}
            var header = parentDoc.querySelector('header[data-testid="stHeader"]');
            if (header) {{
                var existingTimer = parentDoc.getElementById("top_header_timer");
                if (existingTimer) {{
                    existingTimer.remove();
                }}
                
                var timerDiv = parentDoc.createElement("div");
                timerDiv.id = "top_header_timer";
                timerDiv.style.cssText = "position: absolute; right: 240px; top: 10px; z-index: 999999; display: flex; align-items: center; gap: 8px; background: #1e293b; padding: 4px 12px; border-radius: 6px; border: 1px solid #334155; font-family: monospace; color: #f8fafc;";
                timerDiv.innerHTML = '<span style="font-size:0.9rem; font-weight:bold;">{status_txt}</span> <span style="font-size:1.1rem; font-weight:bold;">{time_str}</span>';
                
                header.appendChild(timerDiv);
            }}
        </script>
        """
        components.html(js_code, height=0, width=0)


def format_duration(seconds):
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


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

# Tampilkan state awal timer di top header
if not st.session_state.get("data_processed", False):
    inject_header_timer(running=False, total_seconds=0)

# 4. Panel Sidebar
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

# 5. Logika Eksekusi Tombol Proses Data
if btn_process:
    if not has_minimal_files:
        st.sidebar.error("❌ Berkas Lembar Respon dan Kunci Jawaban wajib diunggah!")
    else:
        # Reset state sebelum pemrosesan baru
        st.session_state["data_processed"] = False
        st.session_state["val_result"] = None
        st.session_state["df_matrix"] = None
        st.session_state["ctt_res"] = None
        st.session_state["df_matrix_school"] = None

        # Jalankan Live Timer di Top Header Bar
        inject_header_timer(running=True)

        with st.status("⏳ Memproses data psikometri...", expanded=True) as status:
            progress_bar = st.progress(0)
            t_start = time.time()

            step_logs = []
            log_container = st.empty()

            def log_step(step_num, step_name, status_type="running", duration=None):
                if status_type == "running":
                    icon = "⏳"
                    dur_str = "*sedang memproses...*"
                elif status_type == "complete":
                    icon = "✅"
                    dur_str = f"*(selesai dalam `{duration:.2f} dtk`)*"
                elif status_type == "error":
                    icon = "❌"
                    dur_str = "*(gagal)*"

                msg = f"{icon} **Langkah {step_num}/4:** {step_name} {dur_str}"

                if len(step_logs) < step_num:
                    step_logs.append(msg)
                else:
                    step_logs[step_num - 1] = msg

                log_container.markdown("\n\n".join(step_logs))

            # --- LANGKAH 1: VALIDASI ---
            log_step(1, "Memvalidasi struktur & format berkas...", "running")
            t1_start = time.time()
            progress_bar.progress(10)

            val_result = validate_7_files(uploaded_files)
            st.session_state["val_result"] = val_result
            t1_dur = time.time() - t1_start

            if val_result["status"]:
                log_step(1, "Memvalidasi struktur & format berkas", "complete", t1_dur)

                # --- LANGKAH 2: SCORING ENGINE ---
                log_step(2, "Menjalankan Scoring Engine & Pemetaan Skor...", "running")
                t2_start = time.time()
                progress_bar.progress(35)

                dfs = val_result["dataframes"]
                df_matrix = process_scoring(dfs["respon"], dfs["kunci"])

                # Mapping jumlah soal dari tabel mapel
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

                df_matrix.drop(columns=["_join_id"], inplace=True, errors="ignore")
                df_respon_raw.drop(columns=["_join_id", "_list_soal_parsed", "_kode_mapel_clean"], inplace=True, errors="ignore")

                arr_skor = df_matrix["skor_mentah"].values
                arr_jml = df_matrix["Jumlah_Soal"].values

                with np.errstate(divide="ignore", invalid="ignore"):
                    konversi_arr = np.where(arr_jml > 0, (arr_skor / arr_jml) * 100.0, 0.0)

                df_matrix["Nilai_Konversi"] = np.round(konversi_arr, 2)
                st.session_state["df_matrix"] = df_matrix
                t2_dur = time.time() - t2_start
                log_step(2, "Menjalankan Scoring Engine & Pemetaan Skor", "complete", t2_dur)

                # --- LANGKAH 3: ANALISIS CTT ---
                log_step(3, "Menganalisis Psikometri Klasik (CTT)...", "running")
                t3_start = time.time()
                progress_bar.progress(70)

                ctt_res = ctt_analysis.run_ctt_analysis(df_matrix, dfs["respon"], dfs["kunci"])
                st.session_state["ctt_res"] = ctt_res
                t3_dur = time.time() - t3_start
                log_step(3, "Menganalisis Psikometri Klasik (CTT)", "complete", t3_dur)

                # --- LANGKAH 4: OLAHAN ANALISIS PER SEKOLAH & PROVINSI ---
                log_step(4, "Mengolah Agregasi Data Per Sekolah & Wilayah...", "running")
                t4_start = time.time()
                progress_bar.progress(90)

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
                t4_dur = time.time() - t4_start
                log_step(4, "Mengolah Agregasi Data Per Sekolah & Wilayah", "complete", t4_dur)

                # --- FINISH ---
                progress_bar.progress(100)
                t_total = time.time() - t_start

                status.update(
                    label=f"🎉 Pengolahan Data Selesai dalam **{format_duration(t_total)}** ({t_total:.2f} dtk)!",
                    state="complete",
                    expanded=False,
                )

                st.session_state["data_processed"] = True
                st.session_state["last_execution_time"] = round(t_total, 2)
                st.rerun()
            else:
                log_step(1, "Memvalidasi struktur & format berkas", "error")
                status.update(label="❌ Validasi Data Gagal!", state="error", expanded=True)
                st.session_state["data_processed"] = False

# 6. Tampilan Utama Dashboard (Panggilan Modul Views)
if not st.session_state.get("data_processed", False):
    st.info(
        "👋 **Petunjuk:** Unggah berkas sekaligus (CSV/XLSX/ZIP) pada wadah unggah"
        " di sebelah kiri, lalu klik tombol **🚀 Proses Data**."
    )
else:
    # Tampilkan durasi akhir setelah selesai di top header bar
    last_sec = st.session_state.get("last_execution_time", 0)
    inject_header_timer(running=False, total_seconds=last_sec)

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

    with tab_val:
        render_tab_validation(val_result)

    with tab_scoring:
        render_tab_scoring(df_matrix)

    with tab_ctt:
        render_tab_ctt(ctt_res, df_matrix, dfs)

    with tab_irt:
        render_tab_irt(df_matrix, dfs, ctt_res)

    with tab_school:
        render_tab_school(df_matrix_school, dfs)