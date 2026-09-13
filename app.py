# app.py
import io
import time
import zipfile

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import ctt_analysis
from db_helper import get_db_connection, prepare_and_save_analysis
from irt_analysis import run_irt_analysis
from scoring import extract_active_soal_from_respon, process_scoring
from styles import load_custom_css
from validators import validate_7_files

# Import modul UI dari folder views
from views.tab_ctt import render_tab_ctt
from views.tab_irt import render_tab_irt
from views.tab_region import render_tab_region
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
    '<div class="sub-header">Sistem Pemrosesan Data Respon, CTT (Klasik), dan IRT (Rasch, 1PL, 2PL, 3PL)</div>',
    unsafe_allow_html=True,
)

# Inisialisasi Session State
if "data_processed" not in st.session_state:
    st.session_state["data_processed"] = False
if "val_result" not in st.session_state:
    st.session_state["val_result"] = None
if "irt_results" not in st.session_state:
    st.session_state["irt_results"] = {}


# --- AUTO-LOAD DARI DATABASE MYSQL SAAT REFRESH ---
def load_data_from_db():
    """Membaca hasil analisis terakhir dari MySQL jika session_state kosong."""
    try:
        engine = get_db_connection()
        if engine is None:
            return False

        df_summary = pd.read_sql("SELECT * FROM tb_model_summary", engine)
        if df_summary.empty:
            return False

        df_peserta = pd.read_sql("SELECT * FROM tb_peserta_skor", engine)
        df_soal = pd.read_sql("SELECT * FROM tb_soal_parameter", engine)

        # Konversi kolom numerik
        for num_col in [
            "tingkat_kesukaran_ctt",
            "daya_beda_ctt",
            "b_rasch",
            "b_1pl",
            "a_2pl",
            "b_2pl",
            "a_3pl",
            "b_3pl",
            "c_3pl",
        ]:
            if num_col in df_soal.columns:
                df_soal[num_col] = pd.to_numeric(df_soal[num_col], errors="coerce")

        if "skor_mentah" not in df_peserta.columns:
            if "skor_konversi_ctt" in df_peserta.columns:
                df_peserta["skor_mentah"] = pd.to_numeric(
                    df_peserta["skor_konversi_ctt"], errors="coerce"
                )

        if "Jumlah_Soal" not in df_peserta.columns:
            df_peserta["Jumlah_Soal"] = len(df_soal) if not df_soal.empty else 0

        ctt_summary = df_summary[df_summary["metode_model"].str.upper() == "CTT"]
        ctt_rel = (
            float(ctt_summary["reliabilitas"].values[0])
            if not ctt_summary.empty
            and pd.notna(ctt_summary["reliabilitas"].values[0])
            else 0.0
        )

        st.session_state["df_matrix"] = df_peserta
        st.session_state["df_matrix_school"] = df_peserta
        st.session_state["val_result"] = {
            "status": True,
            "dataframes": {
                "respon": df_peserta,
                "kunci": df_soal,
            },
        }
        st.session_state["ctt_res"] = {
            "item_stats": df_soal,
            "person_stats": df_peserta,
            "reliability": ctt_rel,
            "cronbach_alpha": ctt_rel,
        }

        irt_dict = {}
        for m in ["rasch", "1pl", "2pl", "3pl"]:
            row = df_summary[df_summary["metode_model"].str.lower() == m]
            fit_stat = row.to_dict(orient="records")[0] if not row.empty else {}

            df_person_m = df_peserta.copy()
            col_target = f"skor_konversi_{m}"

            if (
                col_target in df_person_m.columns
                and not df_person_m[col_target].isna().all()
            ):
                df_person_m["Nilai_Scaled"] = pd.to_numeric(
                    df_person_m[col_target], errors="coerce"
                )
                df_person_m["Theta"] = df_person_m["Nilai_Scaled"]
            elif "skor_konversi_ctt" in df_person_m.columns:
                df_person_m["Nilai_Scaled"] = pd.to_numeric(
                    df_person_m["skor_konversi_ctt"], errors="coerce"
                )
                df_person_m["Theta"] = df_person_m["Nilai_Scaled"]

            irt_dict[m] = {
                "df_person": df_person_m,
                "item_params": df_soal,
                "fit_stats": fit_stat,
            }

        st.session_state["irt_results"] = irt_dict
        st.session_state["data_processed"] = True
        return True
    except Exception:
        return False


if not st.session_state.get("data_processed", False):
    load_data_from_db()

if not st.session_state.get("data_processed", False):
    inject_header_timer(running=False, total_seconds=0)

# 4. Panel Sidebar
st.sidebar.markdown(
    "<h3 style='margin-bottom: 4px; font-size: 1.1rem;'>📁 Unggah Berkas</h3>",
    unsafe_allow_html=True,
)

if st.session_state.get("data_processed", False):
    st.sidebar.success("✅ Data tersimpan dimuat dari Database MySQL.")

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

# --- PANEL REGISTRASI SKALA KONVERSI SKOR ---
st.sidebar.markdown("---")
st.sidebar.markdown("#### ⚙️ Pengaturan Skala Konversi (IRT)")
with st.sidebar.expander("Atur Rentang Skala Konversi", expanded=True):
    col_min, col_max = st.columns(2)
    with col_min:
        min_scale = st.number_input("Skor Min", value=200.0, step=10.0, key="cfg_min_scale")
    with col_max:
        max_scale = st.number_input("Skor Maks", value=800.0, step=10.0, key="cfg_max_scale")
    
    col_mean, col_sd = st.columns(2)
    with col_mean:
        mean_scale = st.number_input("Rata-Rata (Mean)", value=500.0, step=10.0, key="cfg_mean_scale")
    with col_sd:
        sd_scale = st.number_input("Deviasi (SD)", value=100.0, step=10.0, key="cfg_sd_scale")


def read_file_to_df(file_item):
    """Fungsi helper membaca file / BytesIO menjadi DataFrame.
    Menggunakan file_item.seek(0) di setiap siklus pembacaan agar stream tidak habis.
    """
    try:
        fname = getattr(file_item, "name", "").lower()
        if fname.endswith(".csv"):
            # Opsi 1: Coba baca dengan delimiter titik koma ';'
            try:
                if hasattr(file_item, "seek"):
                    file_item.seek(0)
                df = pd.read_csv(
                    file_item,
                    sep=";",
                    quotechar='"',
                    on_bad_lines="skip",
                    low_memory=False,
                )
                if df.shape[1] > 1:
                    return df
            except Exception:
                pass

            # Opsi 2: Fallback ke delimiter koma ','
            if hasattr(file_item, "seek"):
                file_item.seek(0)
                
            return pd.read_csv(
                file_item,
                sep=",",
                quotechar='"',
                escapechar="\\",
                engine="python",
                on_bad_lines="skip",
            )

        elif fname.endswith((".xlsx", ".xls")):
            if hasattr(file_item, "seek"):
                file_item.seek(0)
            return pd.read_excel(file_item)
    except Exception as e:
        st.sidebar.warning(
            f"Gagal membaca file {getattr(file_item, 'name', 'data')}: {e}"
        )
    return None


def extract_zip_files(files_list):
    """Mengekstrak seluruh file CSV/XLSX dari file ZIP dan mengembalikannya sebagai list stream file."""
    extracted = []
    for f in files_list:
        if f.name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(f) as z:
                    for filename in z.namelist():
                        if not filename.startswith(
                            "__MACOSX"
                        ) and filename.lower().endswith((".csv", ".xlsx", ".xls")):
                            content = z.read(filename)
                            file_bytes = io.BytesIO(content)
                            file_bytes.name = filename.split("/")[-1]
                            extracted.append(file_bytes)
            except Exception as e:
                st.sidebar.error(f"Gagal membaca file ZIP {f.name}: {e}")
        else:
            extracted.append(f)
    return extracted


# Penampung list file/DataFrame berdasarkan kategori
raw_file_collections = {
    "respon": [],
    "kunci": [],
    "biodata": [],
    "sekolah": [],
    "mapel": [],
    "kompetensi": [],
    "peta_paket": [],
}

if batch_files:
    all_unpacked_files = extract_zip_files(batch_files)

    # Pengelompokan seluruh file yang berhasil diekstrak ke kategori masing-masing
    for f in all_unpacked_files:
        fname = f.name.lower()
        if "respon" in fname:
            raw_file_collections["respon"].append(f)
        elif "kunci" in fname:
            raw_file_collections["kunci"].append(f)
        elif "biodata" in fname:
            raw_file_collections["biodata"].append(f)
        elif "sekolah" in fname:
            raw_file_collections["sekolah"].append(f)
        elif "mapel" in fname:
            raw_file_collections["mapel"].append(f)
        elif "kompetensi" in fname or "kisi" in fname:
            raw_file_collections["kompetensi"].append(f)
        elif "paket" in fname or "peta" in fname:
            raw_file_collections["peta_paket"].append(f)

# Penggabungan seluruh file sejenis menjadi 1 DataFrame utuh
uploaded_files = {}
for key, files_list in raw_file_collections.items():
    if not files_list:
        uploaded_files[key] = None
    else:
        df_list = []
        for fl in files_list:
            df_temp = read_file_to_df(fl)
            if df_temp is not None and not df_temp.empty:
                df_list.append(df_temp)
        
        if df_list:
            if len(df_list) == 1:
                df_merged = df_list[0]
            else:
                df_merged = pd.concat(df_list, ignore_index=True).drop_duplicates()
            
            df_merged.name = f"Gabungan_{key.upper()}_({len(df_list)}_files)"
            uploaded_files[key] = df_merged
        else:
            uploaded_files[key] = None

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
    obj = uploaded_files[key]
    count_files = len(raw_file_collections[key])
    
    if obj is not None and not obj.empty:
        file_desc = getattr(obj, "name", f"Gabungan_{key.upper()}_({count_files}_files)")
        num_rows = len(obj)
        st.sidebar.markdown(f"✅ **{label}**: `{file_desc}` — **{num_rows:,} baris**".replace(",", "."))
    else:
        st.sidebar.markdown(
            f"❌ <span style='color:gray;'>{label}{req_mark}: Belum terdeteksi</span>",
            unsafe_allow_html=True,
        )

st.sidebar.markdown("---")
btn_process = st.sidebar.button(
    "🚀 Proses Data", type="primary", use_container_width=True
)

has_minimal_files = (uploaded_files["respon"] is not None) and (
    uploaded_files["kunci"] is not None
)


def filter_kunci_by_respon_kode(df_respon, df_kunci):
    if df_respon is None or df_kunci is None:
        return df_kunci

    active_soal = extract_active_soal_from_respon(df_respon)
    col_kode_kunci = next(
        (
            c
            for c in df_kunci.columns
            if c.lower()
            in ["kd_soal", "kode_soal", "kodesoal", "kode_paket", "paket"]
        ),
        df_kunci.columns[0],
    )

    if active_soal:
        df_kunci_filtered = df_kunci[
            df_kunci[col_kode_kunci].astype(str).str.strip().isin(active_soal)
        ].copy()
        if not df_kunci_filtered.empty:
            return df_kunci_filtered

    col_kode_resp = next(
        (
            c
            for c in df_respon.columns
            if c.lower()
            in ["kd_soal", "kode_soal", "kodesoal", "kode_paket", "paket"]
        ),
        None,
    )

    if col_kode_resp and col_kode_kunci:
        used_kodes = df_respon[col_kode_resp].dropna().astype(str).str.strip().unique()
        df_kunci_filtered = df_kunci[
            df_kunci[col_kode_kunci].astype(str).str.strip().isin(used_kodes)
        ].copy()
        if not df_kunci_filtered.empty:
            return df_kunci_filtered

    return df_kunci


# 5. Logika Eksekusi Tombol Proses Data
if btn_process:
    if not has_minimal_files:
        st.sidebar.error("❌ Berkas Lembar Respon dan Kunci Jawaban wajib diunggah!")
    else:
        st.session_state["data_processed"] = False
        st.session_state["val_result"] = None
        st.session_state["df_matrix"] = None
        st.session_state["ctt_res"] = None
        st.session_state["df_matrix_school"] = None
        st.session_state["irt_results"] = {}
        st.session_state["process_logs"] = []

        # Ambil konfigurasi skala dari input pengguna di sidebar
        scale_config = {
            "min": float(st.session_state.get("cfg_min_scale", 200.0)),
            "max": float(st.session_state.get("cfg_max_scale", 800.0)),
            "mean": float(st.session_state.get("cfg_mean_scale", 500.0)),
            "sd": float(st.session_state.get("cfg_sd_scale", 100.0)),
        }

        inject_header_timer(running=True)

        with st.status("⏳ Memproses data psikometri...", expanded=True) as status:
            t_start = time.time()

            step_names = [
                "Memvalidasi struktur & format berkas",
                "Menjalankan Scoring Engine & Pemetaan Skor",
                "Menganalisis Psikometri Klasik (CTT)",
                "Menganalisis Model IRT (Rasch, 1PL, 2PL, 3PL) Seluruh Peserta",
                "Mengolah Agregasi Data & Menyimpan ke MySQL Server",
                "Memuat Antarmuka Visualisasi & Penyiapan Berkas Unduhan",
            ]
            total_steps = len(step_names)
            step_states = [
                {"status": "pending", "duration": None} for _ in range(total_steps)
            ]

            progress_bar = st.progress(0)
            log_container = st.empty()

            def render_step_logs():
                lines = []
                for idx, name in enumerate(step_names):
                    step_num = idx + 1
                    st_item = step_states[idx]
                    st_type = st_item["status"]
                    dur = st_item["duration"]

                    if st_type == "complete":
                        dur_str = (
                            f"*(selesai dalam `{dur:.2f} dtk`)*"
                            if dur is not None
                            else ""
                        )
                        line = (
                            f"✅ **Langkah {step_num}/{total_steps}:** {name} {dur_str}"
                        )
                    elif st_type == "running":
                        line = f"⏳ **Langkah {step_num}/{total_steps}:** {name}... *sedang memproses...*"
                    elif st_type == "error":
                        line = f"❌ **Langkah {step_num}/{total_steps}:** {name} *(gagal)*"
                    else:
                        line = f"<span style='color: #64748b;'>⚪ Langkah {step_num}/{total_steps}: {name} *(menunggu)*</span>"

                    lines.append(line)

                log_container.markdown("\n\n".join(lines), unsafe_allow_html=True)

            def update_step(step_idx, status_type, duration=None):
                step_states[step_idx]["status"] = status_type
                step_states[step_idx]["duration"] = duration
                render_step_logs()

            render_step_logs()

            # --- LANGKAH 1: VALIDASI ---
            update_step(0, "running")
            t1_start = time.time()
            progress_bar.progress(10)

            val_result = validate_7_files(uploaded_files)
            st.session_state["val_result"] = val_result
            t1_dur = time.time() - t1_start

            if val_result["status"]:
                update_step(0, "complete", t1_dur)

                # --- LANGKAH 2: SCORING ENGINE ---
                update_step(1, "running")
                t2_start = time.time()
                progress_bar.progress(25)

                dfs = val_result["dataframes"]
                df_kunci_filtered = filter_kunci_by_respon_kode(
                    dfs["respon"], dfs["kunci"]
                )
                dfs["kunci"] = df_kunci_filtered
                df_matrix = process_scoring(dfs["respon"], df_kunci_filtered)

                st.session_state["df_matrix"] = df_matrix
                t2_dur = time.time() - t2_start
                update_step(1, "complete", t2_dur)

                # --- LANGKAH 3: ANALISIS CTT ---
                update_step(2, "running")
                t3_start = time.time()
                progress_bar.progress(45)

                ctt_res = ctt_analysis.run_ctt_analysis(
                    df_matrix, dfs["respon"], dfs["kunci"]
                )
                st.session_state["ctt_res"] = ctt_res
                t3_dur = time.time() - t3_start
                update_step(2, "complete", t3_dur)

                # --- LANGKAH 4: PROSES MODEL IRT (SELURUH PESERTA) ---
                update_step(3, "running")
                t4_start = time.time()
                progress_bar.progress(65)

                df_irt_input = df_matrix.copy()

                non_item_cols = [
                    c
                    for c in df_irt_input.columns
                    if c.lower()
                    in [
                        "username",
                        "user_id",
                        "nama",
                        "kode_soal",
                        "kode_paket",
                        "total_skor",
                        "skor",
                        "skor_mentah",
                        "nilai_konversi",
                        "jumlah_soal",
                    ]
                ]
                item_cols = [
                    c for c in df_irt_input.columns if c not in non_item_cols
                ]

                # MEMORY OPTIMIZATION: Chunks processing to avoid ArrayMemoryError for huge datasets (~3.4M rows)
                if item_cols:
                    chunk_size = 500000
                    if len(df_irt_input) > chunk_size:
                        processed_chunks = []
                        for start_idx in range(0, len(df_irt_input), chunk_size):
                            chunk = df_irt_input.iloc[start_idx : start_idx + chunk_size].copy()
                            chunk[item_cols] = (
                                chunk[item_cols]
                                .apply(pd.to_numeric, errors="coerce")
                                .fillna(0)
                                .astype(np.float32)
                            )
                            processed_chunks.append(chunk)
                        df_irt_input = pd.concat(processed_chunks, ignore_index=True)
                        del processed_chunks
                    else:
                        df_irt_input[item_cols] = (
                            df_irt_input[item_cols]
                            .apply(pd.to_numeric, errors="coerce")
                            .fillna(0)
                            .astype(np.float32)
                        )

                irt_dict = {}
                for m_type in ["Rasch", "1PL", "2PL", "3PL"]:
                    try:
                        res = run_irt_analysis(
                            df_irt_input,
                            model_type=m_type,
                            min_scale=scale_config["min"],
                            max_scale=scale_config["max"],
                            mean_scale=scale_config["mean"],
                            sd_scale=scale_config["sd"],
                        )
                        
                        df_p_mod = res.get("person_params", pd.DataFrame())

                        m_key = m_type.lower()
                        irt_dict[m_key] = {
                            "df_person": df_p_mod,
                            "item_params": res.get("item_params", pd.DataFrame()),
                            "fit_stats": res.get("fit_stats", {}),
                        }
                    except Exception as ex_irt:
                        st.warning(
                            f"Catatan: Analisis IRT {m_type} dilewati/mengalami kendala: {ex_irt}"
                        )

                st.session_state["irt_results"] = irt_dict
                t4_dur = time.time() - t4_start
                update_step(3, "complete", t4_dur)

                # --- LANGKAH 5: AGREGASI & PENYIMPANAN KE MYSQL SERVER ---
                update_step(4, "running")
                t5_start = time.time()
                progress_bar.progress(85)

                df_matrix_school = pd.DataFrame()
                if (
                    "sekolah" in dfs
                    and dfs["sekolah"] is not None
                    and not dfs["sekolah"].empty
                ):
                    try:
                        df_sek = dfs["sekolah"].copy()
                        df_sek.columns = [
                            str(c).strip().lower() for c in df_sek.columns
                        ]

                        col_kd_sek = next(
                            (
                                c
                                for c in df_sek.columns
                                if c
                                in [
                                    "kd_sekfull",
                                    "kode_sekolah",
                                    "kd_sekolah",
                                    "id_sekolah",
                                    "kd_sek",
                                ]
                            ),
                            df_sek.columns[0],
                        )
                        col_nama_sek = next(
                            (
                                c
                                for c in df_sek.columns
                                if c
                                in [
                                    "nama_sekolah",
                                    "namasekolah",
                                    "nama_sek",
                                    "sekolah",
                                ]
                            ),
                            None,
                        )
                        col_nama_kab = next(
                            (
                                c
                                for c in df_sek.columns
                                if c
                                in [
                                    "nama_kabupaten",
                                    "namakabupaten",
                                    "nama_kab",
                                    "nama_kota",
                                    "kabupaten",
                                    "kota",
                                ]
                            ),
                            None,
                        )
                        col_kd_prov = next(
                            (
                                c
                                for c in df_sek.columns
                                if c
                                in [
                                    "kd_prop",
                                    "kode_provinsi",
                                    "kd_provinsi",
                                    "kode_prop",
                                    "kd_prov",
                                ]
                            ),
                            None,
                        )
                        col_nama_prov = next(
                            (
                                c
                                for c in df_sek.columns
                                if c
                                in [
                                    "nama_provinsi",
                                    "namaprovinsi",
                                    "nama_prov",
                                    "provinsi",
                                ]
                            ),
                            None,
                        )

                        df_sek["_school_key"] = (
                            df_sek[col_kd_sek].astype(str).str.strip().str.upper()
                        )

                        cols_to_keep = ["_school_key"]
                        if col_nama_sek:
                            cols_to_keep.append(col_nama_sek)
                        if col_nama_kab:
                            cols_to_keep.append(col_nama_kab)
                        if col_kd_prov:
                            cols_to_keep.append(col_kd_prov)
                        if col_nama_prov:
                            cols_to_keep.append(col_nama_prov)

                        df_sek_clean = (
                            df_sek[cols_to_keep]
                            .drop_duplicates(subset=["_school_key"])
                            .copy()
                        )

                        rename_map = {}
                        if col_nama_sek:
                            rename_map[col_nama_sek] = "nama_sekolah_master"
                        if col_nama_kab:
                            rename_map[col_nama_kab] = "nama_kabupaten_master"
                        if col_kd_prov:
                            rename_map[col_kd_prov] = "kd_prop_master"
                        if col_nama_prov:
                            rename_map[col_nama_prov] = "nama_provinsi_master"
                        df_sek_clean.rename(columns=rename_map, inplace=True)

                        usr_user_col = "username" if "username" in df_matrix.columns else df_matrix.columns[0]

                        df_matrix_school = df_matrix.copy()
                        df_matrix_school["_school_key"] = (
                            df_matrix_school[usr_user_col]
                            .astype(str)
                            .str.strip()
                            .str[:9]
                            .str.upper()
                        )
                        df_matrix_school["_prop_key_user"] = (
                            df_matrix_school[usr_user_col]
                            .astype(str)
                            .str.strip()
                            .str[1:3]
                        )

                        df_matrix_school = df_matrix_school.merge(
                            df_sek_clean, on="_school_key", how="left"
                        )

                        df_matrix_school["nama_sekolah"] = df_matrix_school[
                            "nama_sekolah_master"
                        ].fillna(df_matrix_school["_school_key"])
                        df_matrix_school["nama_kabupaten"] = df_matrix_school[
                            "nama_kabupaten_master"
                        ].fillna("-")
                        df_matrix_school["kd_prop"] = df_matrix_school[
                            "kd_prop_master"
                        ].fillna(df_matrix_school["_prop_key_user"])
                        df_matrix_school["nama_provinsi"] = df_matrix_school[
                            "nama_provinsi_master"
                        ].fillna(df_matrix_school["kd_prop"])

                        df_matrix_school["kd_prop"] = (
                            df_matrix_school["kd_prop"]
                            .astype(str)
                            .str.strip()
                            .str.replace(".0", "", regex=False)
                            .str.rstrip(",")
                            .str.zfill(2)
                        )
                        df_matrix_school["nama_provinsi"] = (
                            df_matrix_school["nama_provinsi"]
                            .astype(str)
                            .str.strip()
                            .str.rstrip(",")
                            .str.strip()
                            .str.upper()
                        )

                    except Exception as e:
                        st.warning(
                            f"Catatan: Pemrosesan data sekolah/provinsi mengalami kendala: {e}"
                        )

                st.session_state["df_matrix_school"] = df_matrix_school

                # --- PENYUSUNAN DATAFRAME UNTUK PENYIMPANAN MYSQL ---
                try:
                    df_base = (
                        df_matrix_school
                        if not df_matrix_school.empty
                        else df_matrix
                    )
                    df_peserta_save = pd.DataFrame()

                    usr_col_src = "username" if "username" in df_base.columns else df_base.columns[0]
                    df_peserta_save["username"] = df_base[usr_col_src].astype(str).str.strip()
                    df_peserta_save["nama_sekolah"] = (
                        df_base["nama_sekolah"]
                        if "nama_sekolah" in df_base.columns
                        else None
                    )
                    df_peserta_save["kode_sekolah"] = (
                        df_base["_school_key"]
                        if "_school_key" in df_base.columns
                        else None
                    )
                    df_peserta_save["nama_kabupaten"] = (
                        df_base["nama_kabupaten"]
                        if "nama_kabupaten" in df_base.columns
                        else None
                    )
                    df_peserta_save["nama_provinsi"] = (
                        df_base["nama_provinsi"]
                        if "nama_provinsi" in df_base.columns
                        else None
                    )
                    df_peserta_save["kode_provinsi"] = (
                        df_base["kd_prop"] if "kd_prop" in df_base.columns else None
                    )

                    df_peserta_save["skor_mentah"] = pd.to_numeric(
                        df_base["skor_mentah"], errors="coerce"
                    ).fillna(0)
                    df_peserta_save["Jumlah_Soal"] = pd.to_numeric(
                        df_base["Jumlah_Soal"], errors="coerce"
                    ).fillna(1)

                    # 1. Skor CTT KLASIK
                    df_peserta_save["skor_konversi_ctt"] = np.where(
                        df_peserta_save["Jumlah_Soal"] > 0,
                        (df_peserta_save["skor_mentah"] / df_peserta_save["Jumlah_Soal"]) * 100.0,
                        0.0
                    ).round(2)

                    # 2. Pemetaan Skor IRT
                    def extract_and_map_irt(model_key, target_df):
                        if model_key not in irt_dict or not isinstance(irt_dict[model_key], dict):
                            return np.nan

                        df_p = irt_dict[model_key].get("df_person")
                        if df_p is None or df_p.empty:
                            return np.nan

                        df_p = df_p.copy()

                        # A. Cari kolom skor yang sudah jadi
                        target_col = None
                        for c in df_p.columns:
                            col_str = str(c).lower().strip()
                            if col_str in ["nilai_scaled", "nilai konversi", "nilai_konversi", "score", "scaled_score", "skor_konversi"]:
                                target_col = c
                                break

                        # B. Jika tidak ditemukan, cari kolom Theta
                        if not target_col:
                            for c in df_p.columns:
                                col_str = str(c).lower().strip()
                                if any(k in col_str for k in ["theta", "ability", "z_score", "zscore", "kemampuan"]):
                                    target_col = c
                                    break

                        # C. Fallback numerik terakhir
                        if target_col is None:
                            num_cols = df_p.select_dtypes(include=[np.number]).columns
                            if len(num_cols) > 0:
                                target_col = num_cols[-1]

                        if target_col is None:
                            return np.nan

                        vals = pd.to_numeric(df_p[target_col], errors="coerce")

                        # Konversi dari Theta jika nilainya masih skala Z
                        if vals.dropna().abs().max() < 20.0:  
                            vals = np.clip(
                                scale_config["mean"] + (scale_config["sd"] * vals),
                                scale_config["min"],
                                scale_config["max"]
                            ).round(2)

                        # D. Pemetaan berdasarkan Username
                        u_col_irt = next((c for c in df_p.columns if str(c).lower() in ["username", "user_id", "id_peserta", "id"]), None)
                        
                        if u_col_irt:
                            df_p["_clean_user"] = df_p[u_col_irt].astype(str).str.strip().str.lower()
                            irt_map = dict(zip(df_p["_clean_user"], vals))
                            
                            target_users = target_df["username"].astype(str).str.strip().str.lower()
                            mapped = target_users.map(irt_map)
                            
                            if mapped.isna().all() and len(vals) == len(target_df):
                                return vals.values
                            return mapped
                        
                        if len(vals) == len(target_df):
                            return vals.values
                        
                        return vals.reindex(target_df.index).values

                    df_peserta_save["skor_konversi_rasch"] = extract_and_map_irt("rasch", df_peserta_save)
                    df_peserta_save["skor_konversi_1pl"]   = extract_and_map_irt("1pl", df_peserta_save)
                    df_peserta_save["skor_konversi_2pl"]   = extract_and_map_irt("2pl", df_peserta_save)
                    df_peserta_save["skor_konversi_3pl"]   = extract_and_map_irt("3pl", df_peserta_save)

                    # Table Parameter Soal
                    df_soal_save = pd.DataFrame()
                    if ctt_res and "item_stats" in ctt_res:
                        df_item_ctt = ctt_res["item_stats"].copy()
                        col_soal = df_item_ctt.columns[0]
                        df_soal_save["kode_soal"] = df_item_ctt[col_soal].astype(str)

                        col_diff = next(
                            (
                                c
                                for c in df_item_ctt.columns
                                if "tingkat kesukaran" in c.lower()
                                or "p_value" in c.lower()
                                or "diff" in c.lower()
                                or "kesukaran" in c.lower()
                            ),
                            None,
                        )
                        col_disc = next(
                            (
                                c
                                for c in df_item_ctt.columns
                                if "daya beda" in c.lower()
                                or "disc" in c.lower()
                                or "biserial" in c.lower()
                                or "daya_beda" in c.lower()
                            ),
                            None,
                        )
                        col_rekom = next(
                            (
                                c
                                for c in df_item_ctt.columns
                                if "rekomendasi" in c.lower()
                                or "status" in c.lower()
                            ),
                            None,
                        )

                        df_soal_save["tingkat_kesukaran_ctt"] = (
                            df_item_ctt[col_diff] if col_diff else None
                        )
                        df_soal_save["daya_beda_ctt"] = (
                            df_item_ctt[col_disc] if col_disc else None
                        )
                        df_soal_save["rekomendasi"] = (
                            df_item_ctt[col_rekom] if col_rekom else None
                        )

                        for m_key in ["rasch", "1pl", "2pl", "3pl"]:
                            if (
                                m_key in irt_dict
                                and "item_params" in irt_dict[m_key]
                            ):
                                df_i = irt_dict[m_key]["item_params"]
                                if df_i is not None and not df_i.empty:
                                    if m_key == "rasch":
                                        df_soal_save["b_rasch"] = (
                                            df_i["b"].values
                                            if "b" in df_i.columns
                                            else None
                                        )
                                    elif m_key == "1pl":
                                        df_soal_save["b_1pl"] = (
                                            df_i["b"].values
                                            if "b" in df_i.columns
                                            else None
                                        )
                                    elif m_key == "2pl":
                                        df_soal_save["a_2pl"] = (
                                            df_i["a"].values
                                            if "a" in df_i.columns
                                            else None
                                        )
                                        df_soal_save["b_2pl"] = (
                                            df_i["b"].values
                                            if "b" in df_i.columns
                                            else None
                                        )
                                    elif m_key == "3pl":
                                        df_soal_save["a_3pl"] = (
                                            df_i["a"].values
                                            if "a" in df_i.columns
                                            else None
                                        )
                                        df_soal_save["b_3pl"] = (
                                            df_i["b"].values
                                            if "b" in df_i.columns
                                            else None
                                        )
                                        df_soal_save["c_3pl"] = (
                                            df_i["c"].values
                                            if "c" in df_i.columns
                                            else None
                                        )

                    # Table Model Summary
                    summary_rows = []
                    rel_ctt = (
                        ctt_res.get("reliability", ctt_res.get("cronbach_alpha"))
                        if ctt_res
                        else None
                    )
                    summary_rows.append(
                        {
                            "metode_model": "CTT",
                            "reliabilitas": rel_ctt,
                            "log_likelihood": None,
                            "aic": None,
                            "bic": None,
                        }
                    )
                    for m_key in ["rasch", "1pl", "2pl", "3pl"]:
                        if m_key in irt_dict and "fit_stats" in irt_dict[m_key]:
                            f_stat = irt_dict[m_key]["fit_stats"]
                            summary_rows.append(
                                {
                                    "metode_model": m_key.upper(),
                                    "reliabilitas": f_stat.get("reliability"),
                                    "log_likelihood": f_stat.get("log_likelihood"),
                                    "aic": f_stat.get("aic"),
                                    "bic": f_stat.get("bic"),
                                }
                            )
                    df_summary_save = pd.DataFrame(summary_rows)

                    # Table Agregasi Sekolah
                    df_sekolah_save = pd.DataFrame()
                    if (
                        not df_peserta_save.empty
                        and "kode_sekolah" in df_peserta_save.columns
                    ):
                        df_sekolah_save = (
                            df_peserta_save.groupby("kode_sekolah")
                            .agg(
                                nama_sekolah=("nama_sekolah", "first"),
                                nama_kabupaten=("nama_kabupaten", "first"),
                                nama_provinsi=("nama_provinsi", "first"),
                                jumlah_peserta=("username", "count"),
                                rata_skor_mentah=("skor_mentah", "mean"),
                                rata_skor_ctt=("skor_konversi_ctt", "mean"),
                                rata_skor_rasch=("skor_konversi_rasch", "mean"),
                                rata_skor_2pl=("skor_konversi_2pl", "mean"),
                                rata_skor_3pl=("skor_konversi_3pl", "mean"),
                            )
                            .reset_index()
                        )

                    # Eksekusi Penyimpanan ke Database MySQL
                    saved_ok, msg_db = prepare_and_save_analysis(
                        df_peserta=df_peserta_save,
                        df_soal=df_soal_save,
                        df_summary=df_summary_save,
                        df_sekolah=df_sekolah_save,
                    )
                    if not saved_ok:
                        st.warning(f"Catatan DB: {msg_db}")
                    else:
                        st.cache_data.clear()

                except Exception as ex_mysql:
                    st.warning(
                        f"Catatan: Penyimpanan ke MySQL mengalami kendala: {ex_mysql}"
                    )

                t5_dur = time.time() - t5_start
                update_step(4, "complete", t5_dur)

                # --- LANGKAH 6: FINISH UI ---
                update_step(5, "running")
                t6_start = time.time()
                progress_bar.progress(95)

                time.sleep(0.3)

                t6_dur = time.time() - t6_start
                update_step(5, "complete", t6_dur)

                progress_bar.progress(100)
                t_total = time.time() - t_start

                status.update(
                    label=f"🎉 Pengolahan Data Selesai dalam **{format_duration(t_total)}** ({t_total:.2f} dtk)!",
                    state="complete",
                    expanded=False,
                )

                st.session_state["data_processed"] = True
                st.session_state["last_execution_time"] = round(t_total, 2)
                st.session_state["total_process_time_str"] = format_duration(t_total)
                st.session_state["total_process_time_sec"] = round(t_total, 2)

                logs_to_save = []
                for idx, name in enumerate(step_names):
                    logs_to_save.append(
                        {
                            "step_num": idx + 1,
                            "total_steps": total_steps,
                            "name": name,
                            "dur": step_states[idx]["duration"] or 0.0,
                        }
                    )
                st.session_state["process_logs"] = logs_to_save

                st.rerun()
            else:
                update_step(0, "error")
                status.update(
                    label="❌ Validasi Data Gagal!", state="error", expanded=True
                )
                st.session_state["data_processed"] = False

# 6. Tampilan Utama Dashboard
if not st.session_state.get("data_processed", False):
    st.info(
        "👋 **Petunjuk:** Unggah berkas sekaligus (CSV/XLSX/ZIP) pada wadah unggah"
        " di sebelah kiri, sesuaikan skala skor jika perlu, lalu klik tombol **🚀 Proses Data**."
    )

    if st.session_state.get("val_result"):
        render_tab_validation(st.session_state["val_result"])
else:
    last_sec = st.session_state.get("last_execution_time", 0)
    inject_header_timer(running=False, total_seconds=last_sec)

    val_result = st.session_state.get("val_result", {})
    dfs = val_result.get("dataframes", {})
    df_matrix = st.session_state.get("df_matrix")
    ctt_res = st.session_state.get("ctt_res")
    df_matrix_school = st.session_state.get("df_matrix_school", pd.DataFrame())

    tab_val, tab_scoring, tab_ctt, tab_irt, tab_school, tab_region = st.tabs(
        [
            "📋 1. Validasi Data",
            "💯 2. Scoring Engine",
            "📈 3. Analisis CTT",
            "🎯 4. Analisis IRT",
            "🏫 5. Analisis Per Sekolah",
            "🗺️ 6. Analisis Wilayah",
        ]
    )

    with tab_val:
        if val_result:
            render_tab_validation(val_result)
        else:
            st.info("Data dimuat langsung dari database.")

    with tab_scoring:
        render_tab_scoring(df_matrix)

    with tab_ctt:
        render_tab_ctt(ctt_res, df_matrix, dfs)

    with tab_irt:
        res_irt = render_tab_irt(df_matrix, dfs, ctt_res)

    with tab_school:
        current_irt_results = st.session_state.get("irt_results", {})
        render_tab_school(df_matrix_school, dfs, irt_results=current_irt_results)

    with tab_region:
        render_tab_region(df_matrix_school if not df_matrix_school.empty else df_matrix, dfs)