# app.py
import io
import os
import re
import time
import zipfile

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import ctt_analysis
from db_helper import (
    get_db_connection,
    prepare_and_save_analysis,
    check_db_status,
    get_active_config,
    get_database_status,
    reset_database,
    load_master_data_from_db,
    save_master_data_to_db,
)
from irt_analysis import run_irt_analysis
from scoring import extract_active_soal_from_respon, process_scoring
from styles import load_custom_css
from validators import validate_7_files, get_mapel_lookup_dict

# Import modul UI dari folder views
from sqlalchemy import text
from views.tab_ctt import render_tab_ctt
from views.tab_irt import render_tab_irt
from views.tab_region import (
    render_tab_region,
    resolve_province_info,
    extract_region_codes,
    get_kode_kabupaten_map,
)
from views.tab_school import render_tab_school
from views.tab_scoring import render_tab_scoring
from views.tab_student_scores import render_tab_student_scores
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


# --- 2.5. SISTEM AUTENTIKASI LOGIN (PASSWORD GATE) ---
APP_PASSWORD = "pusmendikjaya"

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False


def render_login_gate():
    """Menampilkan antarmuka login yang elegan sebelum memuat dashboard."""
    if st.session_state.get("authenticated", False):
        return True

    login_slot = st.empty()
    with login_slot.container():
        col_pad1, col_box, col_pad2 = st.columns([1, 1.4, 1])
        with col_box:
            st.markdown(
                """
                <div style="background: #1e293b; border: 1px solid #334155; padding: 36px 32px; border-radius: 14px; margin-top: 50px; margin-bottom: 20px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); text-align: center;">
                    <div style="font-size: 3.5rem; margin-bottom: 12px; line-height: 1;">🔐</div>
                    <h2 style="color: #f8fafc; margin: 0; font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em;">Dashboard Psikometri TKA</h2>
                    <p style="color: #94a3b8; font-size: 0.95rem; margin-top: 8px; margin-bottom: 0;">Silakan masukkan password untuk mengakses dashboard pengolahan.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.form("login_form", clear_on_submit=False):
                entered_pw = st.text_input(
                    "Password Akses:",
                    type="password",
                    placeholder="Masukkan password...",
                    help="Silakan masukkan password untuk membuka akses dashboard.",
                )
                submit_btn = st.form_submit_button("🚀 Masuk ke Dashboard", use_container_width=True)

                if submit_btn:
                    if entered_pw == APP_PASSWORD:
                        st.session_state["authenticated"] = True
                        login_slot.empty()
                        st.rerun()
                    elif not entered_pw.strip():
                        st.warning("⚠️ Mohon masukkan password terlebih dahulu.")
                    else:
                        st.error("❌ Password salah. Silakan coba kembali.")

            st.markdown(
                '<div style="text-align: center; color: #64748b; font-size: 0.82rem; margin-top: 14px;">'
                '🔒 Akses terbatas untuk staf dan pengolah data resmi Puspendik/Pusmendik.'
                '</div>',
                unsafe_allow_html=True,
            )

    return False


# Jika belum login, hentikan proses eksekusi dashboard
if not render_login_gate():
    st.stop()


# Inisialisasi Session State
if "data_processed" not in st.session_state:
    st.session_state["data_processed"] = False
if "val_result" not in st.session_state:
    st.session_state["val_result"] = None
if "irt_results" not in st.session_state:
    st.session_state["irt_results"] = {}


# --- SISTEM PENYIMPANAN CADANGAN LOKAL (PARQUET FALLBACK) ---
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache")


def save_local_cache(df_peserta=None, df_soal=None, df_summary=None, df_sekolah=None):
    """Menyimpan data hasil analisis ke disk lokal dalam format Parquet secara inkremental per mapel."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        if df_peserta is not None and not df_peserta.empty:
            p_path = os.path.join(CACHE_DIR, "tb_peserta_skor.parquet")
            df_to_save = df_peserta.copy()
            if os.path.exists(p_path) and "mapel" in df_to_save.columns:
                try:
                    df_old = pd.read_parquet(p_path)
                    new_mapels = set(df_to_save["mapel"].dropna().astype(str).str.strip().str.upper())
                    if "mapel" in df_old.columns:
                        old_mapels = df_old["mapel"].astype(str).str.strip().str.upper()
                        df_old = df_old[~old_mapels.isin(new_mapels)]
                    df_to_save = pd.concat([df_old, df_to_save], ignore_index=True)
                except Exception:
                    pass
            df_to_save.to_parquet(p_path, index=False)

        if df_soal is not None and not df_soal.empty:
            p_soal_path = os.path.join(CACHE_DIR, "tb_soal_parameter.parquet")
            df_soal_to_save = df_soal.copy()
            if os.path.exists(p_soal_path) and "mapel" in df_soal_to_save.columns:
                try:
                    df_soal_old = pd.read_parquet(p_soal_path)
                    new_soal_mapels = set(df_soal_to_save["mapel"].dropna().astype(str).str.strip().str.upper())
                    if "mapel" in df_soal_old.columns:
                        old_s_mapels = df_soal_old["mapel"].astype(str).str.strip().str.upper()
                        df_soal_old = df_soal_old[~old_s_mapels.isin(new_soal_mapels)]
                    df_soal_to_save = pd.concat([df_soal_old, df_soal_to_save], ignore_index=True)
                except Exception:
                    pass
            df_soal_to_save.to_parquet(p_soal_path, index=False)

        if df_summary is not None and not df_summary.empty:
            df_summary.to_parquet(os.path.join(CACHE_DIR, "tb_model_summary.parquet"), index=False)
        if df_sekolah is not None and not df_sekolah.empty:
            df_sekolah.to_parquet(os.path.join(CACHE_DIR, "tb_sekolah_agregasi.parquet"), index=False)
        return True
    except Exception as e:
        print(f"Gagal simpan local cache: {e}")
        return False


def load_from_local_cache():
    """Membaca hasil analisis dari disk lokal jika database belum terhubung."""
    try:
        p_peserta = os.path.join(CACHE_DIR, "tb_peserta_skor.parquet")
        p_soal = os.path.join(CACHE_DIR, "tb_soal_parameter.parquet")
        p_summary = os.path.join(CACHE_DIR, "tb_model_summary.parquet")
        p_sekolah = os.path.join(CACHE_DIR, "tb_sekolah_agregasi.parquet")

        if not os.path.exists(p_summary) or not os.path.exists(p_peserta):
            return None

        df_summary = pd.read_parquet(p_summary)
        df_peserta = pd.read_parquet(p_peserta)
        df_soal = pd.read_parquet(p_soal) if os.path.exists(p_soal) else pd.DataFrame()
        df_sekolah = pd.read_parquet(p_sekolah) if os.path.exists(p_sekolah) else pd.DataFrame()
        return df_summary, df_peserta, df_soal, df_sekolah
    except Exception:
        return None


# --- AUTO-LOAD DARI DATABASE MYSQL / LOCAL CACHE SAAT REFRESH ---
def load_data_from_db():
    """Membaca hasil analisis terakhir dari MySQL (atau local cache) jika session_state kosong."""
    df_summary = None
    df_peserta = None
    df_soal = None
    df_sekolah = None
    loaded_source = None

    # Muat kamus mapel dari master jika ada
    mpl_lookup = st.session_state.get("mapel_dict")

    # 1. Coba baca dari MySQL Server
    try:
        engine = get_db_connection()
        if engine is not None:
            # Baca tb_master_mapel terlebih dahulu
            try:
                df_m_master = pd.read_sql("SELECT * FROM tb_master_mapel", engine)
                if not df_m_master.empty:
                    st.session_state["df_mapel"] = df_m_master
                    mpl_lookup = get_mapel_lookup_dict(df_m_master)
                    st.session_state["mapel_dict"] = mpl_lookup
            except Exception:
                pass

            if not mpl_lookup:
                mpl_lookup = get_mapel_lookup_dict(None)
                st.session_state["mapel_dict"] = mpl_lookup

            # Sinkronisasi nama mapel di MySQL jika masih berupa kode seperti ABIOP atau berakhiran Pilihan
            try:
                if mpl_lookup:
                    with engine.begin() as conn:
                        for k_c, n_c in mpl_lookup.items():
                            if k_c and n_c and str(k_c).strip().upper() != str(n_c).strip().upper():
                                conn.execute(
                                    text("UPDATE tb_peserta_skor SET mapel = :n WHERE UPPER(TRIM(mapel)) = :k;"),
                                    {"n": str(n_c).strip(), "k": str(k_c).strip().upper()},
                                )
                                conn.execute(
                                    text("UPDATE tb_soal_parameter SET mapel = :n WHERE UPPER(TRIM(mapel)) = :k;"),
                                    {"n": str(n_c).strip(), "k": str(k_c).strip().upper()},
                                )
                        # Penyelarasan agar nama mapel persis sesuai tabel master mapel resmi (tanpa kata 'Pilihan')
                        conn.execute(text("UPDATE tb_peserta_skor SET mapel = 'Biologi' WHERE UPPER(TRIM(mapel)) IN ('ABIOP', 'BIOLOGI PILIHAN');"))
                        conn.execute(text("UPDATE tb_soal_parameter SET mapel = 'Biologi' WHERE UPPER(TRIM(mapel)) IN ('ABIOP', 'BIOLOGI PILIHAN');"))
                        conn.execute(text("UPDATE tb_peserta_skor SET mapel = 'Kimia' WHERE UPPER(TRIM(mapel)) IN ('AKIMP', 'KIMIA PILIHAN');"))
                        conn.execute(text("UPDATE tb_soal_parameter SET mapel = 'Kimia' WHERE UPPER(TRIM(mapel)) IN ('AKIMP', 'KIMIA PILIHAN');"))
                        conn.execute(text("UPDATE tb_peserta_skor SET mapel = 'Fisika' WHERE UPPER(TRIM(mapel)) IN ('AFISP', 'FISIKA PILIHAN');"))
                        conn.execute(text("UPDATE tb_soal_parameter SET mapel = 'Fisika' WHERE UPPER(TRIM(mapel)) IN ('AFISP', 'FISIKA PILIHAN');"))
                        conn.execute(text("UPDATE tb_peserta_skor SET mapel = 'Ekonomi' WHERE UPPER(TRIM(mapel)) IN ('AEKOP', 'EKONOMI PILIHAN');"))
                        conn.execute(text("UPDATE tb_soal_parameter SET mapel = 'Ekonomi' WHERE UPPER(TRIM(mapel)) IN ('AEKOP', 'EKONOMI PILIHAN');"))
                        conn.execute(text("UPDATE tb_peserta_skor SET mapel = 'Geografi' WHERE UPPER(TRIM(mapel)) IN ('AGEOP', 'GEOGRAFI PILIHAN');"))
                        conn.execute(text("UPDATE tb_soal_parameter SET mapel = 'Geografi' WHERE UPPER(TRIM(mapel)) IN ('AGEOP', 'GEOGRAFI PILIHAN');"))
                        conn.execute(text("UPDATE tb_peserta_skor SET mapel = 'Sosiologi' WHERE UPPER(TRIM(mapel)) IN ('ASOSP', 'SOSIOLOGI PILIHAN');"))
                        conn.execute(text("UPDATE tb_soal_parameter SET mapel = 'Sosiologi' WHERE UPPER(TRIM(mapel)) IN ('ASOSP', 'SOSIOLOGI PILIHAN');"))
                        conn.execute(text("UPDATE tb_peserta_skor SET mapel = 'Sejarah' WHERE UPPER(TRIM(mapel)) IN ('ASEJP', 'SEJARAH PILIHAN');"))
                        conn.execute(text("UPDATE tb_soal_parameter SET mapel = 'Sejarah' WHERE UPPER(TRIM(mapel)) IN ('ASEJP', 'SEJARAH PILIHAN');"))
                        conn.execute(text("UPDATE tb_peserta_skor SET mapel = 'Antropologi' WHERE UPPER(TRIM(mapel)) IN ('AANTP', 'ANTROP', 'ANTROPOLOGI PILIHAN');"))
                        conn.execute(text("UPDATE tb_soal_parameter SET mapel = 'Antropologi' WHERE UPPER(TRIM(mapel)) IN ('AANTP', 'ANTROP', 'ANTROPOLOGI PILIHAN');"))
            except Exception:
                pass

            df_sum_test = pd.read_sql("SELECT * FROM tb_model_summary", engine)
            if not df_sum_test.empty:
                df_summary = df_sum_test
                df_peserta = pd.read_sql("SELECT * FROM tb_peserta_skor", engine)
                df_soal = pd.read_sql("SELECT * FROM tb_soal_parameter", engine)
                try:
                    df_sekolah = pd.read_sql("SELECT * FROM tb_sekolah_agregasi", engine)
                except Exception:
                    df_sekolah = pd.DataFrame()
                loaded_source = "MySQL Server"
    except Exception:
        pass

    # 2. Fallback: Coba baca dari Local Parquet Cache jika MySQL belum tersedia
    if df_summary is None or df_summary.empty or df_peserta is None or df_peserta.empty:
        cached = load_from_local_cache()
        if cached is not None:
            df_summary, df_peserta, df_soal, df_sekolah = cached
            loaded_source = "Penyimpanan Lokal (Cache Disk)"

    if df_summary is None or df_summary.empty or df_peserta is None or df_peserta.empty:
        return False

    try:
        if not mpl_lookup:
            mpl_lookup = st.session_state.get("mapel_dict") or get_mapel_lookup_dict(None)
            st.session_state["mapel_dict"] = mpl_lookup

        # Normalisasi nama mapel pada df_peserta dan df_soal
        if df_peserta is not None and "mapel" in df_peserta.columns and mpl_lookup:
            df_peserta["mapel"] = df_peserta["mapel"].map(
                lambda x: mpl_lookup.get(str(x).strip().upper(), mpl_lookup.get(str(x).strip(), str(x).strip()))
            )
        if df_soal is not None and "mapel" in df_soal.columns and mpl_lookup:
            df_soal["mapel"] = df_soal["mapel"].map(
                lambda x: mpl_lookup.get(str(x).strip().upper(), mpl_lookup.get(str(x).strip(), str(x).strip()))
            )

        # Konversi kolom numerik soal
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
            if df_soal is not None and num_col in df_soal.columns:
                df_soal[num_col] = pd.to_numeric(df_soal[num_col], errors="coerce")

        # Normalisasi kolom soal untuk tampilan CTT
        if df_soal is not None and not df_soal.empty:
            if "kode_soal" in df_soal.columns and "Kode_Soal" not in df_soal.columns:
                df_soal["Kode_Soal"] = df_soal["kode_soal"]
            if "tingkat_kesukaran_ctt" in df_soal.columns and "Tingkat_Kesukaran_p" not in df_soal.columns:
                df_soal["Tingkat_Kesukaran_p"] = df_soal["tingkat_kesukaran_ctt"]
            if "daya_beda_ctt" in df_soal.columns and "Daya_Beda_r" not in df_soal.columns:
                df_soal["Daya_Beda_r"] = df_soal["daya_beda_ctt"]
            if "rekomendasi" in df_soal.columns and "Rekomendasi" not in df_soal.columns:
                df_soal["Rekomendasi"] = df_soal["rekomendasi"]

        if "skor_mentah" not in df_peserta.columns:
            if "skor_konversi_ctt" in df_peserta.columns:
                df_peserta["skor_mentah"] = pd.to_numeric(
                    df_peserta["skor_konversi_ctt"], errors="coerce"
                )

        if "Jumlah_Soal" not in df_peserta.columns:
            df_peserta["Jumlah_Soal"] = len(df_soal) if df_soal is not None and not df_soal.empty else 0

        ctt_summary = df_summary[df_summary["metode_model"].str.upper() == "CTT"]
        ctt_rel = (
            float(ctt_summary["reliabilitas"].values[0])
            if not ctt_summary.empty
            and pd.notna(ctt_summary["reliabilitas"].values[0])
            else 0.0
        )

        # Standarisasi data provinsi dan kabupaten (optimasi: hanya jalankan loop jika data belum terisi)
        need_region_norm = True
        if "nama_provinsi" in df_peserta.columns and "nama_kabupaten" in df_peserta.columns:
            non_empty_p = df_peserta["nama_provinsi"].dropna()
            if len(non_empty_p) > 0 and not non_empty_p.iloc[:100].astype(str).str.upper().isin(["", "-", "NAN", "NONE", "NULL", "TIDAK TERDEFINISI"]).all():
                need_region_norm = False

        if need_region_norm:
            col_u_pes = next(
                (c for c in df_peserta.columns if str(c).lower().strip() in ["username", "user_id", "id_peserta"]),
                df_peserta.columns[0]
            )
            prov_norm = []
            kd_norm = []
            kab_norm = []
            kd_ray_norm = []
            p_series = df_peserta["nama_provinsi"] if "nama_provinsi" in df_peserta.columns else pd.Series([None] * len(df_peserta))
            k_series = df_peserta["kode_provinsi"] if "kode_provinsi" in df_peserta.columns else pd.Series([None] * len(df_peserta))
            kb_series = df_peserta["nama_kabupaten"] if "nama_kabupaten" in df_peserta.columns else pd.Series([None] * len(df_peserta))
            u_series = df_peserta[col_u_pes]

            kab_map = get_kode_kabupaten_map()
            for p_v, k_v, u_v, kb_v in zip(p_series, k_series, u_series, kb_series):
                c_p, n_p = resolve_province_info(p_v, k_v, u_v)
                kd_norm.append(c_p)
                prov_norm.append(n_p)
                _, kd_ray, _ = extract_region_codes(u_v)
                kd_ray_norm.append(kd_ray)
                kb_str = str(kb_v).strip() if pd.notna(kb_v) else ""
                if kb_str and kb_str.upper() not in ["", "-", "NAN", "NONE", "NULL", "TIDAK TERDEFINISI"]:
                    kab_norm.append(kb_str)
                elif kd_ray and kd_ray in kab_map:
                    kab_norm.append(kab_map[kd_ray])
                elif kd_ray:
                    kab_norm.append(f"KAB/KOTA {kd_ray}")
                else:
                    kab_norm.append("TIDAK TERDEFINISI")

            df_peserta["nama_provinsi"] = prov_norm
            df_peserta["kode_provinsi"] = kd_norm
            df_peserta["kode_kabupaten"] = kd_ray_norm
            df_peserta["nama_kabupaten"] = kab_norm

        st.session_state["df_peserta_skor"] = df_peserta
        st.session_state["df_matrix"] = df_peserta
        st.session_state["df_matrix_school"] = df_peserta
        if df_sekolah is not None and not df_sekolah.empty:
            st.session_state["df_sekolah_agregasi"] = df_sekolah
        db_masters = load_master_data_from_db()
        st.session_state["val_result"] = {
            "status": True,
            "dataframes": {
                "respon": df_peserta,
                "kunci": db_masters.get("kunci", df_soal),
                "biodata": db_masters.get("biodata"),
                "sekolah": db_masters.get("sekolah", df_sekolah),
                "mapel": db_masters.get("mapel"),
                "kompetensi": db_masters.get("kompetensi"),
                "peta_paket": db_masters.get("peta_paket"),
            },
        }
        st.session_state["ctt_res"] = {
            "item_stats": df_soal,
            "person_stats": df_peserta,
            "reliability": ctt_rel,
            "cronbach_alpha": ctt_rel,
            "summary": {
                "cronbach_alpha": ctt_rel,
                "n_peserta": len(df_peserta),
                "n_soal": len(df_soal) if df_soal is not None else 0,
            },
        }

        irt_dict = {}
        m_scale_def = float(st.session_state.get("cfg_mean_scale", 500.0))
        s_scale_def = float(st.session_state.get("cfg_sd_scale", 100.0))
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
                df_person_m["Theta"] = np.round((df_person_m["Nilai_Scaled"] - m_scale_def) / max(s_scale_def, 1e-5), 3)
            elif "skor_konversi_ctt" in df_person_m.columns:
                df_person_m["Nilai_Scaled"] = pd.to_numeric(
                    df_person_m["skor_konversi_ctt"], errors="coerce"
                )
                df_person_m["Theta"] = np.round((df_person_m["Nilai_Scaled"] - m_scale_def) / max(s_scale_def, 1e-5), 3)

            # Salin parameter butir spesifik model
            df_soal_m = df_soal.copy() if df_soal is not None else pd.DataFrame()
            if not df_soal_m.empty:
                df_soal_m["Item"] = df_soal_m.get("kode_soal", df_soal_m.columns[0])
                if f"b_{m}" in df_soal_m.columns:
                    df_soal_m["b"] = df_soal_m[f"b_{m}"]
                if f"a_{m}" in df_soal_m.columns:
                    df_soal_m["a"] = df_soal_m[f"a_{m}"]
                if f"c_{m}" in df_soal_m.columns:
                    df_soal_m["c"] = df_soal_m[f"c_{m}"]

            irt_dict[m] = {
                "df_person": df_person_m,
                "item_params": df_soal_m,
                "fit_stats": fit_stat,
            }

        st.session_state["irt_results"] = irt_dict
        st.session_state["data_processed"] = True
        st.session_state["loaded_source"] = loaded_source

        # Set config key agar tidak memicu reset cache tab_irt
        min_s = float(st.session_state.get("cfg_min_scale", 200.0))
        max_s = float(st.session_state.get("cfg_max_scale", 800.0))
        st.session_state["last_irt_scale_key"] = f"{min_s}_{max_s}"
        return True
    except Exception as e:
        print(f"Error memproses load_data_from_db: {e}")
        return False


# 3. Header Utama Aplikasi
col_hdr_title, col_hdr_logout = st.columns([8.6, 1.4])
with col_hdr_title:
    st.markdown(
        '<div class="main-header">📊 Dashboard Pengolahan & Analisis Psikometri TKA (v.4)</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="sub-header">Sistem Pemrosesan Data Respon, CTT (Klasik), dan IRT (Rasch, 1PL, 2PL, 3PL)</div>',
        unsafe_allow_html=True,
    )
with col_hdr_logout:
    st.write("")
    st.write("")
    if st.button("🔒 Logout", key="btn_auth_logout", use_container_width=True, help="Keluar dari sesi dashboard"):
        st.session_state["authenticated"] = False
        st.session_state["data_processed"] = False
        st.rerun()

if not st.session_state.get("data_processed", False):
    inject_header_timer(running=False, total_seconds=0)

# 4. Panel Sidebar
st.sidebar.markdown(
    "<h3 style='margin-bottom: 4px; font-size: 1.1rem;'>📁 Unggah Berkas</h3>",
    unsafe_allow_html=True,
)

# Indikator status koneksi Database MySQL
db_ok, db_msg = check_db_status()
if db_ok:
    st.sidebar.success(f"🟢 **Database:** {db_msg}")
else:
    st.sidebar.warning(f"🟡 **Database:** {db_msg}")
    with st.sidebar.expander("⚙️ Konfigurasi Koneksi MySQL", expanded=False):
        st.caption("Jika MySQL berada di host/port atau password berbeda:")
        curr_cfg = get_active_config()
        c_host = st.text_input("Host MySQL", value=curr_cfg["host"], key="cfg_in_host")
        c_port = st.number_input("Port", value=int(curr_cfg["port"]), key="cfg_in_port")
        c_user = st.text_input("User", value=curr_cfg["user"], key="cfg_in_user")
        c_pass = st.text_input("Password", value=curr_cfg["password"], type="password", key="cfg_in_pass")
        c_name = st.text_input("Database", value=curr_cfg["database"], key="cfg_in_name")
        if st.button("🔌 Simpan & Sambungkan", key="btn_apply_db_cfg", use_container_width=True):
            st.session_state["custom_db_host"] = c_host
            st.session_state["custom_db_port"] = c_port
            st.session_state["custom_db_user"] = c_user
            st.session_state["custom_db_pass"] = c_pass
            st.session_state["custom_db_name"] = c_name
            st.cache_data.clear()
            get_db_connection(force_reconnect=True)
            st.rerun()

if st.session_state.get("data_processed", False):
    source_label = st.session_state.get("loaded_source", "Database MySQL")
    st.sidebar.success(f"✅ Data aktif dimuat dari: **{source_label}**")

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

# Penggabungan seluruh file sejenis menjadi 1 DataFrame utuh dengan dukungan multi-mapel
uploaded_files = {}
for key, files_list in raw_file_collections.items():
    if not files_list:
        uploaded_files[key] = None
    else:
        df_list = []
        for idx_fl, fl in enumerate(files_list):
            df_temp = read_file_to_df(fl)
            if df_temp is not None and not df_temp.empty:
                if key == "respon":
                    col_m = next((c for c in df_temp.columns if str(c).strip().lower() in ["mapel", "mata_pelajaran", "mata pelajaran", "subject", "kode_mapel", "nama_mapel"]), None)
                    if col_m:
                        df_temp["mapel"] = df_temp[col_m].astype(str).str.strip().str.upper()
                    else:
                        raw_fn = os.path.splitext(fl.name)[0]
                        clean_fn = re.sub(r'^(tabel[_\s]+respon|lembar[_\s]+respon|respon|response)[_\s\-]*', '', raw_fn, flags=re.IGNORECASE).strip()
                        clean_fn = re.sub(r'^[_\-\s]+|[_\-\s]+$', '', clean_fn)
                        if clean_fn:
                            df_temp["mapel"] = clean_fn.replace('_', ' ').replace('-', ' ').upper()
                        else:
                            df_temp["mapel"] = f"MAPEL {idx_fl+1}" if len(files_list) > 1 else "UMUM"
                elif key == "kunci":
                    col_m = next((c for c in df_temp.columns if str(c).strip().lower() in ["mapel", "mata_pelajaran", "mata pelajaran", "subject", "kode_mapel", "nama_mapel"]), None)
                    if col_m:
                        df_temp["mapel"] = df_temp[col_m].astype(str).str.strip().str.upper()
                    else:
                        raw_fn = os.path.splitext(fl.name)[0]
                        clean_fn = re.sub(r'^(kunci[_\s]+jawaban|kunci|kunci_soal)[_\s\-]*', '', raw_fn, flags=re.IGNORECASE).strip()
                        clean_fn = re.sub(r'^[_\-\s]+|[_\-\s]+$', '', clean_fn)
                        if clean_fn:
                            df_temp["mapel"] = clean_fn.replace('_', ' ').replace('-', ' ').upper()
                        elif len(files_list) > 1:
                            df_temp["mapel"] = f"MAPEL {idx_fl+1}"
                        else:
                            df_temp["mapel"] = "UMUM"
                df_list.append(df_temp)
        
        if df_list:
            if len(df_list) == 1:
                df_merged = df_list[0]
            else:
                df_merged = pd.concat(df_list, ignore_index=True)
                # Deduplikasi dengan aman: jika ada username dan mapel, deduplikasi pada (username, mapel)
                if key == "respon" and "mapel" in df_merged.columns:
                    u_col = next((c for c in df_merged.columns if str(c).lower().strip() in ["username", "user_id", "id_peserta"]), None)
                    if u_col:
                        df_merged = df_merged.drop_duplicates(subset=[u_col, "mapel"])
                    else:
                        df_merged = df_merged.drop_duplicates()
                else:
                    df_merged = df_merged.drop_duplicates()
            
            df_merged = df_merged.reset_index(drop=True)
            df_merged.name = f"Gabungan_{key.upper()}_({len(df_list)}_files)"
            uploaded_files[key] = df_merged
        else:
            uploaded_files[key] = None

# Selaraskan nama mapel pada respon dan kunci menggunakan tabel master mapel atau kamus kurikulum resmi
mapel_dict_lookup = None
if uploaded_files.get("mapel") is not None and not uploaded_files["mapel"].empty:
    mapel_dict_lookup = get_mapel_lookup_dict(uploaded_files["mapel"])
    st.session_state["mapel_dict"] = mapel_dict_lookup
    st.session_state["df_mapel"] = uploaded_files["mapel"]

if not mapel_dict_lookup:
    mapel_dict_lookup = st.session_state.get("mapel_dict") or get_mapel_lookup_dict(None)
    st.session_state["mapel_dict"] = mapel_dict_lookup

if mapel_dict_lookup:
    for t_k in ["respon", "kunci"]:
        if uploaded_files.get(t_k) is not None and "mapel" in uploaded_files[t_k].columns:
            uploaded_files[t_k]["mapel"] = uploaded_files[t_k]["mapel"].map(
                lambda x: mapel_dict_lookup.get(str(x).strip().upper(), mapel_dict_lookup.get(str(x).strip(), str(x).strip()))
            )

st.sidebar.markdown("---")
st.sidebar.markdown("#### Status Deteksi Berkas:")

# Cek ketersediaan tabel master di database MySQL
db_stat = get_database_status()

configs_info = [
    ("respon", "1. Data Respon"),
    ("kunci", "2. Kunci Jawaban"),
    ("biodata", "3. Biodata Peserta"),
    ("sekolah", "4. Master Sekolah"),
    ("mapel", "5. Mata Pelajaran"),
    ("kompetensi", "6. Kisi-Kisi"),
    ("peta_paket", "7. Pemetaan Paket"),
]

for key, label in configs_info:
    obj = uploaded_files[key]
    count_files = len(raw_file_collections[key])

    if obj is not None and not obj.empty:
        file_desc = getattr(obj, "name", f"Gabungan_{key.upper()}_({count_files}_files)")
        num_rows = len(obj)
        st.sidebar.markdown(f"✅ **{label}**: `{file_desc}` — **{num_rows:,} baris**".replace(",", "."))
    else:
        has_in_db = False
        db_desc = ""
        if key == "respon" and db_stat.get("n_peserta_skor", 0) > 0:
            has_in_db = True
            db_desc = f"Tersimpan di Database ({db_stat['n_peserta_skor']:,} peserta)".replace(",", ".")
        elif key == "kunci" and db_stat.get("n_master_kunci", 0) > 0:
            has_in_db = True
            db_desc = f"Tersimpan di Database ({db_stat['n_master_kunci']:,} butir)".replace(",", ".")
        elif key == "biodata" and db_stat.get("n_master_biodata", 0) > 0:
            has_in_db = True
            db_desc = f"Tersimpan di Database ({db_stat['n_master_biodata']:,} siswa)".replace(",", ".")
        elif key == "sekolah" and db_stat.get("n_master_sekolah", 0) > 0:
            has_in_db = True
            db_desc = f"Tersimpan di Database ({db_stat['n_master_sekolah']:,} sekolah)".replace(",", ".")
        elif key == "mapel" and db_stat.get("n_master_mapel", 0) > 0:
            has_in_db = True
            db_desc = f"Tersimpan di Database ({db_stat['n_master_mapel']:,} mapel)".replace(",", ".")
        elif key == "kompetensi" and db_stat.get("n_master_kompetensi", 0) > 0:
            has_in_db = True
            db_desc = f"Tersimpan di Database ({db_stat['n_master_kompetensi']:,} butir)".replace(",", ".")
        elif key == "peta_paket" and db_stat.get("n_master_peta_paket", 0) > 0:
            has_in_db = True
            db_desc = f"Tersimpan di Database ({db_stat['n_master_peta_paket']:,} data)".replace(",", ".")

        if has_in_db:
            st.sidebar.markdown(f"💾 **{label}**: <span style='color:#38bdf8;'>*{db_desc}*</span>", unsafe_allow_html=True)
        else:
            st.sidebar.markdown(
                f"❌ <span style='color:gray;'>{label}: Belum terdeteksi</span>",
                unsafe_allow_html=True,
            )

st.sidebar.markdown("---")
btn_process = st.sidebar.button(
    "🚀 Proses Data", type="primary", use_container_width=True, help="Mulai validasi dan pemrosesan data respon"
)
btn_load_db = st.sidebar.button(
    "📥 Load Data dari DB", use_container_width=True, help="Muat data dan hasil analisis yang tersimpan di database MySQL"
)

if btn_load_db:
    with st.spinner("⏳ Menghubungkan ke MySQL & memuat data psikometri..."):
        ok_load = load_data_from_db()
        if ok_load:
            st.toast("✅ Data berhasil dimuat dari database MySQL!")
            st.rerun()
        else:
            st.sidebar.warning("⚠️ Tidak ada data pengolahan di database atau belum tersimpan.")

# Fitur Reset Database (2 Opsi: Hapus Respon Saja atau Reset Total)
with st.sidebar.expander("🗑️ Kelola & Reset Database", expanded=False):
    st.caption("Gunakan opsi ini jika ingin memulai pengolahan baru dari awal:")
    reset_choice = st.radio(
        "Pilihan Mode Reset:",
        options=[
            "Hapus Respon & Hasil Saja (Master Siswa/Sekolah Tetap Tersimpan)",
            "Reset Total Database (Hapus Semua Tabel & Master)"
        ],
        key="radio_reset_db_choice"
    )
    is_total_reset = "Reset Total" in reset_choice
    chk_confirm_reset = st.checkbox("Konfirmasi: Saya yakin ingin menghapus data", key="chk_confirm_reset_action")
    btn_style = "primary" if is_total_reset else "secondary"
    
    if st.button("⚠️ Eksekusi Reset Database", type=btn_style, use_container_width=True, disabled=not chk_confirm_reset):
        mode_arg = "full" if is_total_reset else "response_only"
        ok_rst, msg_rst = reset_database(mode=mode_arg)
        if ok_rst:
            for k in list(st.session_state.keys()):
                if k not in ["authenticated"]:
                    del st.session_state[k]
            st.sidebar.success(msg_rst)
            time.sleep(1)
            st.rerun()
        else:
            st.sidebar.error(msg_rst)

has_kunci_available = (uploaded_files["kunci"] is not None and not uploaded_files["kunci"].empty) or (db_stat.get("n_master_kunci", 0) > 0)
has_minimal_files = (uploaded_files["respon"] is not None and not uploaded_files["respon"].empty) and has_kunci_available


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
    has_kunci_ready = (uploaded_files.get("kunci") is not None and not uploaded_files["kunci"].empty) or (db_stat.get("n_master_kunci", 0) > 0)
    has_respon_ready = (uploaded_files.get("respon") is not None and not uploaded_files["respon"].empty)

    if not (has_respon_ready and has_kunci_ready):
        st.sidebar.error("❌ Berkas Lembar Respon dan Kunci Jawaban wajib tersedia (diunggah atau dari database)!")
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
                "Memvalidasi struktur & kelengkapan berkas",
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

            # --- LANGKAH 1: VALIDASI & SINKRONISASI DATA MASTER ---
            update_step(0, "running")
            t1_start = time.time()
            progress_bar.progress(10)

            # Sinkronisasi Master Data: Ambil dari Database jika tidak diunggah pengguna pada sesi ini
            db_masters = load_master_data_from_db()
            for m_key in ["kunci", "biodata", "sekolah", "mapel", "kompetensi", "peta_paket"]:
                if uploaded_files.get(m_key) is None or uploaded_files[m_key].empty:
                    if m_key in db_masters and db_masters[m_key] is not None and not db_masters[m_key].empty:
                        uploaded_files[m_key] = db_masters[m_key]

            # Simpan berkas master yang diunggah ke database MySQL agar tersimpan permanen
            try:
                save_master_data_to_db(uploaded_files)
            except Exception as ex_m1:
                print(f"Catatan simpan master langkah 1: {ex_m1}")

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
                if "mapel" in dfs and dfs["mapel"] is not None and not dfs["mapel"].empty:
                    st.session_state["mapel_dict"] = get_mapel_lookup_dict(dfs["mapel"])
                    st.session_state["df_mapel"] = dfs["mapel"]

                df_kunci_filtered = filter_kunci_by_respon_kode(
                    dfs["respon"], dfs["kunci"]
                )
                dfs["kunci"] = df_kunci_filtered
                df_matrix = process_scoring(dfs["respon"], df_kunci_filtered)
                if hasattr(df_matrix, "attrs") and "sample_items_matrix" in df_matrix.attrs:
                    st.session_state["df_matrix_sample"] = df_matrix.attrs["sample_items_matrix"]

                mpl_lookup_active = st.session_state.get("mapel_dict") or get_mapel_lookup_dict(dfs.get("mapel"))
                if "mapel" in df_matrix.columns and mpl_lookup_active:
                    df_matrix["mapel"] = df_matrix["mapel"].map(
                        lambda x: mpl_lookup_active.get(str(x).strip().upper(), mpl_lookup_active.get(str(x).strip(), str(x).strip()))
                    )

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

                # --- LANGKAH 4: PROSES MODEL IRT (ESTIMASI TEROPTIMASI) ---
                update_step(3, "running")
                t4_start = time.time()
                progress_bar.progress(65)

                if hasattr(df_matrix, "attrs") and "sample_items_matrix" in df_matrix.attrs:
                    df_irt_input = df_matrix.attrs["sample_items_matrix"].copy()
                elif "df_matrix_sample" in st.session_state and st.session_state["df_matrix_sample"] is not None:
                    df_irt_input = st.session_state["df_matrix_sample"].copy()
                else:
                    df_irt_input = df_matrix.copy()

                if len(df_irt_input) > 50000:
                    df_irt_input = df_irt_input.sample(n=50000, random_state=42).copy()

                mapel_samples = getattr(df_matrix, "attrs", {}).get("mapel_samples")
                irt_dict = {}

                for m_type in ["Rasch", "1PL", "2PL", "3PL"]:
                    m_key = m_type.lower()
                    if mapel_samples and isinstance(mapel_samples, dict) and len(mapel_samples) > 0:
                        all_p = []
                        all_items = []
                        combined_fit = {}
                        for mpl_name, df_mpl in mapel_samples.items():
                            try:
                                res_m = run_irt_analysis(
                                    df_mpl,
                                    model_type=m_type,
                                    min_scale=scale_config["min"],
                                    max_scale=scale_config["max"],
                                    mean_scale=scale_config["mean"],
                                    sd_scale=scale_config["sd"],
                                )
                                df_p = res_m.get("person_params", pd.DataFrame())
                                df_i = res_m.get("item_params", pd.DataFrame())
                                if not df_p.empty:
                                    df_p["mapel"] = mpl_name
                                    all_p.append(df_p)
                                if not df_i.empty:
                                    df_i["mapel"] = mpl_name
                                    all_items.append(df_i)
                                combined_fit[mpl_name] = res_m.get("fit_stats", {})
                            except Exception:
                                pass
                        
                        df_p_mod = pd.concat(all_p, ignore_index=True) if all_p else pd.DataFrame()
                        df_i_mod = pd.concat(all_items, ignore_index=True) if all_items else pd.DataFrame()
                        irt_dict[m_key] = {
                            "df_person": df_p_mod,
                            "item_params": df_i_mod,
                            "fit_stats": combined_fit,
                        }
                    else:
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

                df_matrix_school = df_matrix.copy()
                usr_user_col = "username" if "username" in df_matrix.columns else df_matrix.columns[0]
                df_matrix_school["_school_key"] = (
                    df_matrix_school[usr_user_col]
                    .astype(str)
                    .str.strip()
                    .str[:9]
                    .str.upper()
                )

                # 1. Integrasi Master Biodata Siswa jika tersedia
                if (
                    "biodata" in dfs
                    and dfs["biodata"] is not None
                    and not dfs["biodata"].empty
                ):
                    try:
                        df_bio = dfs["biodata"].copy()
                        df_bio.columns = [str(c).strip().lower() for c in df_bio.columns]
                        col_u_bio = next(
                            (c for c in df_bio.columns if str(c) in ["username", "usernames", "id_peserta", "idpeserta", "nisn", "id"]),
                            df_bio.columns[0]
                        )
                        df_bio["_u_clean"] = df_bio[col_u_bio].astype(str).str.strip().str.lower()
                        
                        col_nisn_bio = next((c for c in df_bio.columns if "nisn" in c), None)
                        col_nama_bio = next((c for c in df_bio.columns if "nama" in c and "sekolah" not in c and "kabupaten" not in c and "provinsi" not in c), None)
                        col_jk_bio = next((c for c in df_bio.columns if any(kw in c for kw in ["jenis_kelamin", "jeniskelamin", "jk", "gender", "sex", "kelamin", "l/p", "lp"])), None)
                        col_sek_bio = next((c for c in df_bio.columns if "sekolah" in c), None)
                        col_kab_bio = next((c for c in df_bio.columns if "kabupaten" in c or "kota" in c), None)
                        col_prov_bio = next((c for c in df_bio.columns if "provinsi" in c or "propinsi" in c or "prov" in c), None)
                        col_kd_bio = next((c for c in df_bio.columns if "kd_prop" in c or "kode_prov" in c), None)

                        bio_keep = ["_u_clean"]
                        bio_ren = {}
                        if col_nisn_bio:
                            bio_keep.append(col_nisn_bio)
                            bio_ren[col_nisn_bio] = "nisn"
                        if col_nama_bio:
                            bio_keep.append(col_nama_bio)
                            bio_ren[col_nama_bio] = "nama"
                        if col_jk_bio:
                            bio_keep.append(col_jk_bio)
                            bio_ren[col_jk_bio] = "jenis_kelamin"
                        if col_sek_bio:
                            bio_keep.append(col_sek_bio)
                            bio_ren[col_sek_bio] = "nama_sekolah_bio"
                        if col_kab_bio:
                            bio_keep.append(col_kab_bio)
                            bio_ren[col_kab_bio] = "nama_kabupaten_bio"
                        if col_prov_bio:
                            bio_keep.append(col_prov_bio)
                            bio_ren[col_prov_bio] = "nama_provinsi_bio"
                        if col_kd_bio:
                            bio_keep.append(col_kd_bio)
                            bio_ren[col_kd_bio] = "kd_prop_bio"

                        df_bio_clean = df_bio[bio_keep].drop_duplicates(subset=["_u_clean"]).rename(columns=bio_ren)
                        df_matrix_school["_u_clean"] = df_matrix_school[usr_user_col].astype(str).str.strip().str.lower()
                        df_matrix_school = df_matrix_school.merge(df_bio_clean, on="_u_clean", how="left")
                        df_matrix_school = df_matrix_school.drop(columns=["_u_clean"], errors="ignore")
                    except Exception:
                        pass

                # 2. Integrasi Master Sekolah jika tersedia
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
                                    "npsn",
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

                        df_matrix_school = df_matrix_school.merge(
                            df_sek_clean, on="_school_key", how="left"
                        )

                    except Exception as e:
                        st.warning(
                            f"Catatan: Pemrosesan data master sekolah mengalami kendala: {e}"
                        )

                # 3. Konsolidasi Data Nama Sekolah & Kabupaten
                sek_cand = df_matrix_school.get("nama_sekolah_master")
                if sek_cand is None:
                    sek_cand = df_matrix_school.get("nama_sekolah_bio")
                df_matrix_school["nama_sekolah"] = sek_cand.fillna(df_matrix_school["_school_key"]) if sek_cand is not None else df_matrix_school["_school_key"]

                kab_cand = df_matrix_school.get("nama_kabupaten_master")
                if kab_cand is None:
                    kab_cand = df_matrix_school.get("nama_kabupaten_bio")
                raw_kab_init = kab_cand.fillna("-") if kab_cand is not None else pd.Series(["-"] * len(df_matrix_school))

                # 4. Resolusi Akurat Kode & Nama Provinsi (Kolom 2-3) dan Kode Rayon/Kabupaten (Kolom 2-5)
                prov_cand = df_matrix_school.get("nama_provinsi_master")
                if prov_cand is None:
                    prov_cand = df_matrix_school.get("nama_provinsi_bio")
                
                kd_cand = df_matrix_school.get("kd_prop_master")
                if kd_cand is None:
                    kd_cand = df_matrix_school.get("kd_prop_bio")

                raw_prov = prov_cand if prov_cand is not None else pd.Series([None] * len(df_matrix_school))
                raw_kd = kd_cand if kd_cand is not None else pd.Series([None] * len(df_matrix_school))
                raw_user = df_matrix_school[usr_user_col]

                clean_prov_names = []
                clean_kd_props = []
                clean_kd_rayons = []
                clean_kabs = []

                kab_map = get_kode_kabupaten_map()
                for p_v, k_v, u_v, kb_v in zip(raw_prov, raw_kd, raw_user, raw_kab_init):
                    c_code, c_name = resolve_province_info(p_v, k_v, u_v)
                    _, kd_ray, _ = extract_region_codes(u_v)
                    clean_kd_props.append(c_code)
                    clean_prov_names.append(c_name)
                    clean_kd_rayons.append(kd_ray)

                    # Jika nama kabupaten kosong / '-', fallback ke kode rayon (kolom 2-5)
                    kb_str = str(kb_v).strip() if pd.notna(kb_v) else ""
                    if kb_str and kb_str not in ["-", "NAN", "NONE", "NULL", "TIDAK TERDEFINISI"]:
                        clean_kabs.append(kb_str)
                    elif kd_ray and kd_ray in kab_map:
                        clean_kabs.append(kab_map[kd_ray])
                    elif kd_ray:
                        clean_kabs.append(f"KAB/KOTA {kd_ray}")
                    else:
                        clean_kabs.append("TIDAK TERDEFINISI")

                df_matrix_school["kd_prop"] = clean_kd_props
                df_matrix_school["kode_provinsi"] = clean_kd_props
                df_matrix_school["nama_provinsi"] = clean_prov_names
                df_matrix_school["kode_kabupaten"] = clean_kd_rayons
                df_matrix_school["nama_kabupaten"] = clean_kabs

                mpl_lookup_active = st.session_state.get("mapel_dict") or get_mapel_lookup_dict(dfs.get("mapel") if "dfs" in locals() else None)
                if "mapel" in df_matrix_school.columns and mpl_lookup_active:
                    df_matrix_school["mapel"] = df_matrix_school["mapel"].map(
                        lambda x: mpl_lookup_active.get(str(x).strip().upper(), mpl_lookup_active.get(str(x).strip(), str(x).strip()))
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
                    df_peserta_save["nisn"] = df_base["nisn"].astype(str).str.strip() if "nisn" in df_base.columns else "-"
                    df_peserta_save["nama"] = df_base["nama"].astype(str).str.strip() if "nama" in df_base.columns else "-"
                    df_peserta_save["jenis_kelamin"] = df_base["jenis_kelamin"].astype(str).str.strip() if "jenis_kelamin" in df_base.columns else "-"
                    if "mapel" in df_base.columns and mpl_lookup_active:
                        df_peserta_save["mapel"] = df_base["mapel"].fillna("UMUM").map(
                            lambda x: mpl_lookup_active.get(str(x).strip().upper(), mpl_lookup_active.get(str(x).strip(), str(x).strip()))
                        )
                    elif "mapel" in df_base.columns:
                        df_peserta_save["mapel"] = df_base["mapel"].fillna("UMUM").astype(str).str.strip()
                    else:
                        df_peserta_save["mapel"] = "UMUM"
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
                        if "mapel" in df_item_ctt.columns:
                            df_soal_save["mapel"] = df_item_ctt["mapel"].fillna("UMUM").astype(str).str.strip().str.upper()
                        elif "mapel" in df_matrix.columns:
                            m_vals = df_matrix["mapel"].dropna().unique()
                            df_soal_save["mapel"] = str(m_vals[0]).upper() if len(m_vals) == 1 else "UMUM"
                        else:
                            df_soal_save["mapel"] = "UMUM"

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
                                jumlah_peserta=("username", "nunique"),
                                rata_skor_mentah=("skor_mentah", "mean"),
                                rata_skor_ctt=("skor_konversi_ctt", "mean"),
                                rata_skor_rasch=("skor_konversi_rasch", "mean"),
                                rata_skor_2pl=("skor_konversi_2pl", "mean"),
                                rata_skor_3pl=("skor_konversi_3pl", "mean"),
                            )
                            .reset_index()
                        )

                    # Pastikan kolom-kolom skor konversi CTT dan IRT tersinkronisasi ke df_matrix_school & df_matrix
                    for col_skor in [
                        "skor_mentah",
                        "Jumlah_Soal",
                        "skor_konversi_ctt",
                        "skor_konversi_rasch",
                        "skor_konversi_1pl",
                        "skor_konversi_2pl",
                        "skor_konversi_3pl",
                    ]:
                        if col_skor in df_peserta_save.columns:
                            df_matrix_school[col_skor] = df_peserta_save[col_skor].values
                            if df_matrix is not None and len(df_matrix) == len(df_peserta_save):
                                df_matrix[col_skor] = df_peserta_save[col_skor].values

                    # Simpan data siap saji langsung ke session_state agar tab lain instan tanpa query database
                    st.session_state["df_peserta_skor"] = df_peserta_save
                    st.session_state["df_matrix_school"] = df_matrix_school
                    st.session_state["df_sekolah_save"] = df_sekolah_save
                    st.session_state["df_soal_save"] = df_soal_save
                    st.session_state["df_summary_save"] = df_summary_save

                    # Eksekusi Penyimpanan ke Database MySQL & Cache Lokal
                    saved_ok, msg_db = prepare_and_save_analysis(
                        df_peserta=df_peserta_save,
                        df_soal=df_soal_save,
                        df_summary=df_summary_save,
                        df_sekolah=df_sekolah_save,
                    )

                    # Selalu simpan juga ke cache lokal Parquet untuk jaminan ketersediaan data saat refresh
                    save_local_cache(
                        df_peserta=df_peserta_save,
                        df_soal=df_soal_save,
                        df_summary=df_summary_save,
                        df_sekolah=df_sekolah_save,
                    )

                    if not saved_ok:
                        st.session_state["db_save_status"] = f"⚠️ {msg_db} (Data tersimpan di cadangan lokal)"
                    else:
                        st.session_state["db_save_status"] = "✅ Berhasil tersimpan ke MySQL Server & Cadangan Lokal"
                        st.cache_data.clear()

                    # Simpan juga berkas master (sekolah, biodata, kunci, mapel, dsb) jika diunggah
                    try:
                        save_master_data_to_db(uploaded_files)
                    except Exception as ex_m:
                        print(f"Catatan simpan master: {ex_m}")

                    # Muat kembali seluruh data kumulatif dari database MySQL / cache lokal
                    # agar seluruh tab (Scoring, CTT, IRT, Wilayah, Sekolah) langsung menyajikan semua mata pelajaran!
                    load_data_from_db()

                except Exception as ex_mysql:
                    st.session_state["db_save_status"] = f"⚠️ Kendala DB: {ex_mysql} (Data tersimpan di cadangan lokal)"

                t5_dur = time.time() - t5_start
                update_step(4, "complete", t5_dur)

                # --- LANGKAH 6: FINISH UI ---
                update_step(5, "running")
                t6_start = time.time()
                progress_bar.progress(95)

                # Optimasi: Garbage collection dan pra-penyiapan memori agar visualisasi responsif
                import gc
                gc.collect()

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
if not st.session_state.get("data_processed", False) and not btn_process:
    st.info(
        "👋 **Petunjuk Alur Pengolahan:**\n\n"
        "1. **Buka Hasil Tersimpan:** Klik tombol **📥 Load Data dari DB** pada panel menu kiri untuk membuka data & hasil analisis dari MySQL.\n"
        "2. **Pengolahan Berkas Baru:** Unggah berkas respon & master pada panel menu kiri, lalu klik **🚀 Proses Data**.\n"
        "3. **Reset Database:** Jika ingin membersihkan data lama sebelum mengolah baru, gunakan menu **🗑️ Kelola & Reset Database** di panel kiri."
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

    tab_val, tab_scoring, tab_ctt, tab_irt, tab_school, tab_region, tab_student_scores = st.tabs(
        [
            "📋 1. Validasi Data",
            "💯 2. Scoring Engine",
            "📈 3. Analisis CTT",
            "🎯 4. Analisis IRT",
            "🏫 5. Analisis Per Sekolah",
            "🗺️ 6. Analisis Wilayah",
            "👨‍🎓 7. Rekap Nilai Siswa",
        ]
    )

    with tab_val:
        try:
            if val_result:
                render_tab_validation(val_result)
            else:
                st.info("Data dimuat langsung dari database.")
        except Exception as e_val:
            st.error(f"⚠️ Terjadi kendala saat menampilkan Tab Validasi Data: {e_val}")

    with tab_scoring:
        try:
            render_tab_scoring(df_matrix, dfs)
        except Exception as e_score:
            st.error(f"⚠️ Terjadi kendala saat menampilkan Tab Scoring Engine: {e_score}")

    with tab_ctt:
        try:
            render_tab_ctt(ctt_res, df_matrix, dfs)
        except Exception as e_ctt:
            st.error(f"⚠️ Terjadi kendala saat menampilkan Tab Analisis CTT: {e_ctt}")

    with tab_irt:
        try:
            res_irt = render_tab_irt(df_matrix, dfs, ctt_res)
        except Exception as e_irt:
            st.error(f"⚠️ Terjadi kendala saat menampilkan Tab Analisis IRT: {e_irt}")

    with tab_school:
        try:
            current_irt_results = st.session_state.get("irt_results", {})
            render_tab_school(df_matrix_school, dfs, irt_results=current_irt_results)
        except Exception as e_sch:
            st.error(f"⚠️ Terjadi kendala saat menampilkan Tab Analisis Sekolah: {e_sch}")

    with tab_region:
        try:
            render_tab_region(df_matrix_school if not df_matrix_school.empty else df_matrix, dfs)
        except Exception as e_reg:
            st.error(f"⚠️ Terjadi kendala saat menampilkan Tab Analisis Wilayah: {e_reg}")

    with tab_student_scores:
        try:
            render_tab_student_scores(df_matrix_school if not df_matrix_school.empty else df_matrix, dfs)
        except Exception as e_stu:
            st.error(f"⚠️ Terjadi kendala saat menampilkan Tab Rekap Nilai Siswa: {e_stu}")