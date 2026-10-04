import json
import os
import re
import urllib.request
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from db_helper import get_db_connection
from excel_exporter import convert_df_to_csv_bytes
from validators import get_mapel_lookup_dict

# Mapping Kode Provinsi BPS/Kemendagri ke Nama Provinsi Standard
KODE_PROVINSI_MAP = {
    "11": "ACEH",
    "12": "SUMATERA UTARA",
    "13": "SUMATERA BARAT",
    "14": "RIAU",
    "15": "JAMBI",
    "16": "SUMATERA SELATAN",
    "17": "BENGKULU",
    "18": "LAMPUNG",
    "19": "KEPULAUAN BANGKA BELITUNG",
    "21": "KEPULAUAN RIAU",
    "31": "DKI JAKARTA",
    "32": "JAWA BARAT",
    "33": "JAWA TENGAH",
    "34": "DI YOGYAKARTA",
    "35": "JAWA TIMUR",
    "36": "BANTEN",
    "51": "BALI",
    "52": "NUSA TENGGARA BARAT",
    "53": "NUSA TENGGARA TIMUR",
    "61": "KALIMANTAN BARAT",
    "62": "KALIMANTAN TENGAH",
    "63": "KALIMANTAN SELATAN",
    "64": "KALIMANTAN TIMUR",
    "65": "KALIMANTAN UTARA",
    "71": "SULAWESI UTARA",
    "72": "SULAWESI TENGAH",
    "73": "SULAWESI SELATAN",
    "74": "SULAWESI TENGGARA",
    "75": "GORONTALO",
    "76": "SULAWESI BARAT",
    "81": "MALUKU",
    "82": "MALUKU UTARA",
    "91": "PAPUA BARAT",
    "92": "PAPUA",
    "93": "PAPUA SELATAN",
    "94": "PAPUA TENGAH",
    "95": "PAPUA PEGUNUNGAN",
    "96": "PAPUA BARAT DAYA",
}

# Kamus Nama Singkat Standar 38 Provinsi Indonesia
PROVINSI_SINGKAT_MAP = {
    "ACEH": "ACEH",
    "SUMATERA UTARA": "SUMUT",
    "SUMATERA BARAT": "SUMBAR",
    "RIAU": "RIAU",
    "JAMBI": "JAMBI",
    "SUMATERA SELATAN": "SUMSEL",
    "BENGKULU": "BENGKULU",
    "LAMPUNG": "LAMPUNG",
    "KEPULAUAN BANGKA BELITUNG": "BABEL",
    "KEPULAUAN RIAU": "KEPRI",
    "DKI JAKARTA": "DKI",
    "JAWA BARAT": "JABAR",
    "JAWA TENGAH": "JATENG",
    "DI YOGYAKARTA": "DIY",
    "JAWA TIMUR": "JATIM",
    "BANTEN": "BANTEN",
    "BALI": "BALI",
    "NUSA TENGGARA BARAT": "NTB",
    "NUSA TENGGARA TIMUR": "NTT",
    "KALIMANTAN BARAT": "KALBAR",
    "KALIMANTAN TENGAH": "KALTENG",
    "KALIMANTAN SELATAN": "KALSEL",
    "KALIMANTAN TIMUR": "KALTIM",
    "KALIMANTAN UTARA": "KALTARA",
    "SULAWESI UTARA": "SULUT",
    "SULAWESI TENGAH": "SULTENG",
    "SULAWESI SELATAN": "SULSEL",
    "SULAWESI TENGGARA": "SULTRA",
    "GORONTALO": "GORONTALO",
    "SULAWESI BARAT": "SULBAR",
    "MALUKU": "MALUKU",
    "MALUKU UTARA": "MALUT",
    "PAPUA": "PAPUA",
    "PAPUA BARAT": "PAPBAR",
    "PAPUA SELATAN": "PAPSEL",
    "PAPUA TENGAH": "PAPTENG",
    "PAPUA PEGUNUNGAN": "PAPPEG",
    "PAPUA BARAT DAYA": "PAPBD",
}


def _clean_province_name(name_str):
    """Membersihkan dan menyelaraskan penamaan provinsi secara agresif."""
    if not name_str or pd.isna(name_str):
        return "TIDAK TERDEFINISI"

    val = str(name_str).strip().upper()
    if val in ["", "NAN", "NONE", "NULL", "-", "TIDAK TERDEFINISI"]:
        return "TIDAK TERDEFINISI"

    val = re.sub(
        r"^(PROVINSI|PROPINSI|PROV\.|PROV|DAERAH KHUSUS IBUKOTA|DAERAH ISTIMEWA)\s+",
        "",
        val,
    )
    val = re.sub(r"[^A-Z0-9\s]", " ", val)
    val = re.sub(r"\s+", " ", val).strip()

    alias_map = {
        "D I YOGYAKARTA": "DI YOGYAKARTA",
        "DIYOGYAKARTA": "DI YOGYAKARTA",
        "DIY": "DI YOGYAKARTA",
        "YOGYAKARTA": "DI YOGYAKARTA",
        "DAERAH ISTIMEWA YOGYAKARTA": "DI YOGYAKARTA",
        "DKI": "DKI JAKARTA",
        "JAKARTA": "DKI JAKARTA",
        "JAKARTA RAYA": "DKI JAKARTA",
        "KEP BANGKA BELITUNG": "KEPULAUAN BANGKA BELITUNG",
        "BANGKA BELITUNG": "KEPULAUAN BANGKA BELITUNG",
        "BANGKABELITUNG": "KEPULAUAN BANGKA BELITUNG",
        "KEP RIAU": "KEPULAUAN RIAU",
        "NTB": "NUSA TENGGARA BARAT",
        "NTT": "NUSA TENGGARA TIMUR",
        "IRIAN JAYA BARAT": "PAPUA BARAT",
        "IRIAN JAYA TIMUR": "PAPUA",
    }
    return alias_map.get(val, val)


def _clean_kabupaten_name(name_str):
    """Membersihkan penamaan kabupaten/kota secara agresif agar cocok dengan geojson."""
    if not name_str or pd.isna(name_str):
        return "TIDAK TERDEFINISI"
    val = str(name_str).strip().upper()
    if val in ["", "NAN", "NONE", "NULL", "-", "TIDAK TERDEFINISI"]:
        return "TIDAK TERDEFINISI"
    val = re.sub(r"^(KABUPATEN|KAB\.|KAB|KOTA ADMINISTRASI|KOTA ADM\.|KOTA ADM|KOTA|ADM\.|ADM)\s+", "", val)
    val = re.sub(r"[^A-Z0-9\s]", " ", val)
    val = re.sub(r"\s+", " ", val).strip()
    return val if val else "TIDAK TERDEFINISI"


def _get_feature_centroid(geom):
    """Menghitung koordinat centroid (lat, lon) dari polygon/multipolygon GeoJSON."""
    if not geom or "coordinates" not in geom:
        return None, None
    coords = geom.get("coordinates", [])
    t = geom.get("type", "")
    try:
        if t == "Polygon":
            if not coords:
                return None, None
            pts = sorted(coords, key=lambda r: len(r), reverse=True)[0]
        elif t == "MultiPolygon":
            if not coords:
                return None, None
            pts = sorted(coords, key=lambda p: len(p[0]) if p else 0, reverse=True)[0][0]
        else:
            return None, None
        if not pts:
            return None, None
        mean_lon = sum(p[0] for p in pts) / len(pts)
        mean_lat = sum(p[1] for p in pts) / len(pts)
        return mean_lat, mean_lon
    except Exception:
        return None, None


@st.cache_data(ttl=3600, show_spinner=False)
def _load_geojson_indonesia():
    """Memuat GeoJSON Wilayah Provinsi Indonesia dengan offline fallback lokal."""
    # 1. Coba baca dari file lokal data/indonesia_prov.geojson
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_path = os.path.join(base_dir, "data", "indonesia_prov.geojson")
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and "features" in data:
                    return data
    except Exception:
        pass

    # 2. Fallback remote URLs (38 Provinsi terkini)
    urls = [
        "https://raw.githubusercontent.com/ardian28/GeoJson-Indonesia-38-Provinsi/main/Provinsi/38%20Provinsi%20Indonesia%20-%20Provinsi.json",
        "https://raw.githubusercontent.com/superpikar/indonesia-geojson/master/indonesia-province-simple.json",
        "https://raw.githubusercontent.com/ans-4175/indonesia-geojson/master/indonesia-province.geojson",
        "https://raw.githubusercontent.com/superpikar/indonesia-geojson/master/indonesia.geojson",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                if data and "features" in data:
                    return data
        except Exception:
            continue
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _load_geojson_kabupaten():
    """Memuat GeoJSON Wilayah Kabupaten/Kota Indonesia dengan prioritas file lokal."""
    # 1. Coba baca dari file lokal data/indonesia_kab.geojson
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_path = os.path.join(base_dir, "data", "indonesia_kab.geojson")
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and "features" in data:
                    return data
    except Exception:
        pass

    # 2. Remote fallback (URL valid)
    urls = [
        "https://raw.githubusercontent.com/TheMaggieSimpson/IndonesiaGeoJSON/main/kota-kabupaten.json",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                if data and "features" in data:
                    return data
        except Exception:
            continue
    return None


@st.cache_data(ttl=86400, show_spinner=False)
def get_kode_kabupaten_map():
    """Membangun pemetaan kode rayon 4 digit (kolom 2-5) ke nama kabupaten/kota resmi."""
    geo = _load_geojson_kabupaten()
    if not geo:
        return {}
    res = {}
    for feat in geo.get("features", []):
        p = feat.get("properties", {})
        cc = str(p.get("CC_2", "")).strip()
        nm = str(p.get("NAME_2", "")).strip()
        if cc and nm:
            res[cc] = _clean_kabupaten_name(nm)

    # Tambahan alias kode rayon Puspendik/Kemendikbud (kolom 2-5)
    puspendik_aliases = {
        "3101": "JAKARTA PUSAT",
        "3102": "JAKARTA UTARA",
        "3103": "JAKARTA BARAT",
        "3104": "JAKARTA SELATAN",
        "3105": "JAKARTA TIMUR",
        "3106": "KEPULAUAN SERIBU",
    }
    for k, v in puspendik_aliases.items():
        if k not in res or res[k] == "KEPULAUAN SERIBU":
            res[k] = v

    return res


REV_KODE_PROVINSI_MAP = {v: k for k, v in KODE_PROVINSI_MAP.items()}


def resolve_province_info(prov_val=None, kd_val=None, username_val=None):
    """
    Mengonversi berbagai representasi provinsi (nama, kode BPS, atau username)
    menjadi tuple terstandar: (kode_provinsi_2digit, nama_provinsi_standard).
    """
    # 1. Cek dari nama_provinsi
    if prov_val is not None and not pd.isna(prov_val):
        p_str = str(prov_val).strip()
        if p_str.upper() not in ["", "NAN", "NONE", "NULL", "-", "TIDAK TERDEFINISI"]:
            # Jika p_str berupa kode angka BPS misal "32" atau "32.0"
            cand_code = p_str.replace(".0", "").strip().zfill(2)
            if cand_code in KODE_PROVINSI_MAP:
                return cand_code, KODE_PROVINSI_MAP[cand_code]
            
            cleaned = _clean_province_name(p_str)
            if cleaned not in ["TIDAK TERDEFINISI", "", "NAN", "NONE", "NULL"] and not cleaned.isdigit():
                code_found = REV_KODE_PROVINSI_MAP.get(cleaned)
                return code_found, cleaned

    # 2. Cek dari kode_provinsi / kd_prop
    if kd_val is not None and not pd.isna(kd_val):
        k_str = str(kd_val).strip().replace(".0", "")
        if k_str.upper() not in ["", "NAN", "NONE", "NULL", "-"]:
            k_code = k_str.zfill(2)
            if k_code in KODE_PROVINSI_MAP:
                return k_code, KODE_PROVINSI_MAP[k_code]

    # 3. Cek dari username peserta (Sesuai konfirmasi spesifikasi: Kolom 2-3 = Kode Provinsi)
    if username_val is not None and not pd.isna(username_val):
        u_str = str(username_val).strip()
        if u_str.upper() not in ["", "NAN", "NONE", "NULL", "-"]:
            # Aturan Utama: Kolom 2-3 (index 1:3)
            if len(u_str) >= 3:
                cand_k23 = u_str[1:3]
                if cand_k23 in KODE_PROVINSI_MAP:
                    return cand_k23, KODE_PROVINSI_MAP[cand_k23]
            
            # Pola diawali huruf prefix panjang (misal PESERTA_32...)
            m1 = re.match(r"^[A-Za-z_-]+(\d{2})", u_str)
            if m1 and m1.group(1) in KODE_PROVINSI_MAP:
                return m1.group(1), KODE_PROVINSI_MAP[m1.group(1)]
            
            # Fallback jika digit langsung di awal (kolom 1-2)
            if len(u_str) >= 2:
                cand_k02 = u_str[:2]
                if cand_k02 in KODE_PROVINSI_MAP:
                    return cand_k02, KODE_PROVINSI_MAP[cand_k02]

    return None, "TIDAK TERDEFINISI"


def extract_region_codes(username_val):
    """
    Mengekstrak kode wilayah dari username sesuai konfirmasi spesifikasi:
    - Kolom 2-3: Kode Provinsi (2 digit)
    - Kolom 2-5: Kode Rayon / Kab / Kota (4 digit)
    - Kolom 4-5: Kode Rayon Lokal (2 digit)
    """
    if not username_val or pd.isna(username_val):
        return None, None, None
    u = str(username_val).strip()
    kd_prov = None
    kd_rayon_full = None
    kd_rayon_local = None

    if len(u) >= 3:
        if u[1:3] in KODE_PROVINSI_MAP:
            kd_prov = u[1:3]
        elif len(u) >= 2 and u[:2] in KODE_PROVINSI_MAP:
            kd_prov = u[:2]

    if len(u) >= 5:
        kd_rayon_full = u[1:5]   # Kolom 2-5 (Kode Rayon / Kab / Kota)
        kd_rayon_local = u[3:5]  # Kolom 4-5 (Kode Rayon Lokal)
    elif len(u) >= 4 and u[:2] in KODE_PROVINSI_MAP:
        kd_rayon_full = u[:4]
        kd_rayon_local = u[2:4]

    return kd_prov, kd_rayon_full, kd_rayon_local


def _resolve_province_name(prov_val, kd_val=None, username_val=None):
    """Fungsi helper mengembalikan hanya nama provinsi standar."""
    return resolve_province_info(prov_val, kd_val, username_val)[1]


def _get_region_df(df_matrix_school, dfs):
    """Mengekstrak dan mencocokkan DataFrame Peserta dengan data Wilayah secara konsisten."""
    df_base = None
    if st.session_state.get("df_peserta_skor") is not None and not st.session_state["df_peserta_skor"].empty:
        df_base = st.session_state["df_peserta_skor"]
    elif df_matrix_school is not None and not df_matrix_school.empty:
        df_base = df_matrix_school
    elif st.session_state.get("df_matrix_school") is not None and not st.session_state["df_matrix_school"].empty:
        df_base = st.session_state["df_matrix_school"]
    elif st.session_state.get("df_matrix") is not None and not st.session_state["df_matrix"].empty:
        df_base = st.session_state["df_matrix"]
    elif isinstance(dfs, dict) and "respon" in dfs:
        df_base = dfs["respon"]
    else:
        # Coba ambil langsung dari MySQL tb_peserta_skor jika sesi kosong
        try:
            from db_helper import load_data_from_mysql
            df_from_db = load_data_from_mysql()
            if df_from_db is not None and not df_from_db.empty:
                df_base = df_from_db
        except Exception:
            pass

    if df_base is None or df_base.empty:
        return pd.DataFrame()

    df_res = df_base.copy()
    col_user = next(
        (c for c in df_res.columns if str(c).lower().strip() in ["username", "user_id", "id_peserta", "id"]),
        df_res.columns[0]
    )
    df_res["username_clean"] = df_res[col_user].astype(str).str.strip().str.lower()
    if "mapel" in df_res.columns:
        df_res["mapel"] = df_res["mapel"].fillna("UMUM").astype(str).str.strip().str.upper()
        df_res = df_res[df_res["username_clean"] != "nan"].drop_duplicates(subset=["username_clean", "mapel"]).copy()
    else:
        df_res = df_res[df_res["username_clean"] != "nan"].drop_duplicates("username_clean").copy()

    # Cek apakah kolom wilayah sudah ada dan valid di df_res
    has_prov = "nama_provinsi" in df_res.columns and (
        df_res["nama_provinsi"].notna()
        & (df_res["nama_provinsi"].astype(str).str.strip().str.upper() != "TIDAK TERDEFINISI")
        & (df_res["nama_provinsi"].astype(str).str.strip() != "")
    ).any()
    has_kab = "nama_kabupaten" in df_res.columns and (
        df_res["nama_kabupaten"].notna()
        & (df_res["nama_kabupaten"].astype(str).str.strip().str.upper() != "TIDAK TERDEFINISI")
        & (df_res["nama_kabupaten"].astype(str).str.strip() != "")
    ).any()

    # JALUR CEPAT: Jika data sudah memiliki provinsi & kabupaten valid (misal dari scoring/MySQL), gunakan langsung secara instan
    if has_prov and has_kab:
        if "kode_provinsi" not in df_res.columns and "kd_prop" in df_res.columns:
            df_res["kode_provinsi"] = df_res["kd_prop"]
        return df_res

    # Jika belum lengkap di df_res, coba ambil metadata wilayah dari DB MySQL
    if not (has_prov and has_kab):
        try:
            engine = get_db_connection()
            if engine:
                df_meta = pd.read_sql(
                    "SELECT username, mapel, nama_provinsi, nama_kabupaten, kode_provinsi FROM tb_peserta_skor WHERE username IS NOT NULL AND username != ''",
                    engine,
                )
                if not df_meta.empty:
                    df_meta["username_clean"] = df_meta["username"].astype(str).str.strip().str.lower()
                    if "mapel" in df_meta.columns and "mapel" in df_res.columns:
                        df_meta["mapel"] = df_meta["mapel"].fillna("UMUM").astype(str).str.strip().str.upper()
                        for c_drop in ["nama_provinsi", "nama_kabupaten", "kode_provinsi"]:
                            if c_drop in df_res.columns:
                                df_res = df_res.drop(columns=[c_drop])
                        df_res = df_res.merge(
                            df_meta.drop(columns=["username"]).drop_duplicates(subset=["username_clean", "mapel"]),
                            on=["username_clean", "mapel"],
                            how="left",
                        )
                    else:
                        for c_drop in ["nama_provinsi", "nama_kabupaten", "kode_provinsi"]:
                            if c_drop in df_res.columns:
                                df_res = df_res.drop(columns=[c_drop])
                        df_res = df_res.merge(
                            df_meta.drop(columns=["username"]).drop_duplicates("username_clean"),
                            on="username_clean",
                            how="left",
                        )
        except Exception:
            pass

    # Normalisasi Nama Provinsi dan Kabupaten dengan logika berlapis
    col_prov_src = next((c for c in df_res.columns if str(c).lower().strip() in ["nama_provinsi", "provinsi", "prov"]), None)
    col_kd_src = next((c for c in df_res.columns if str(c).lower().strip() in ["kode_provinsi", "kd_prop", "kode_prop", "kd_prov"]), None)
    col_kab_src = next((c for c in df_res.columns if str(c).lower().strip() in ["nama_kabupaten", "kabupaten", "kota", "nama_kota"]), None)

    prov_list = []
    kd_list = []
    kab_list = []

    prov_series = df_res[col_prov_src] if col_prov_src else pd.Series([None] * len(df_res), index=df_res.index)
    kd_series = df_res[col_kd_src] if col_kd_src else pd.Series([None] * len(df_res), index=df_res.index)
    u_series = df_res[col_user] if col_user in df_res.columns else df_res["username_clean"]
    kab_series = df_res[col_kab_src] if col_kab_src else pd.Series([None] * len(df_res), index=df_res.index)

    for p_val, k_val, u_val in zip(prov_series, kd_series, u_series):
        code_p, name_p = resolve_province_info(p_val, k_val, u_val)
        kd_list.append(code_p)
        prov_list.append(name_p)

    kab_map = get_kode_kabupaten_map()
    for kb_val, u_val in zip(kab_series, u_series):
        cleaned_kab = _clean_kabupaten_name(kb_val) if pd.notna(kb_val) and str(kb_val).strip() not in ["", "-", "nan", "none", "null", "TIDAK TERDEFINISI"] else None
        if cleaned_kab and cleaned_kab != "TIDAK TERDEFINISI":
            kab_list.append(cleaned_kab)
        else:
            # Fallback: jika nama kabupaten belum ada, gunakan kode rayon dari username kolom 2-5
            _, kd_rayon, _ = extract_region_codes(u_val)
            if kd_rayon and kd_rayon in kab_map:
                kab_list.append(kab_map[kd_rayon])
            elif kd_rayon:
                kab_list.append(f"KAB/KOTA {kd_rayon}")
            else:
                kab_list.append("TIDAK TERDEFINISI")

    df_res["kode_provinsi"] = kd_list
    df_res["nama_provinsi"] = prov_list
    df_res["nama_kabupaten"] = kab_list
    return df_res


def _calculate_region_stats(df_input, group_col, score_col):
    """Menghitung agregasi statistik wilayah lengkap."""
    if (
        df_input.empty
        or group_col not in df_input.columns
        or score_col not in df_input.columns
    ):
        return pd.DataFrame()

    grouped = (
        df_input.groupby(group_col)[score_col]
        .agg(
            Jumlah_Peserta="count",
            Rata_Rata="mean",
            SD="std",
            Min="min",
            Q1=lambda x: x.quantile(0.25),
            Median="median",
            Q3=lambda x: x.quantile(0.75),
            Max="max",
        )
        .reset_index()
    )

    grouped["SD"] = grouped["SD"].fillna(0.0)
    num_cols = ["Rata_Rata", "SD", "Min", "Q1", "Median", "Q3", "Max"]
    grouped[num_cols] = grouped[num_cols].round(2)

    return grouped.sort_values(by="Rata_Rata", ascending=False)


def render_tab_region(df_matrix_school, dfs):
    st.subheader("🗺️ Analisis Nilai Berbasis Wilayah & Peta Geografis")
    st.caption(
        "Memetakan sebaran nilai konversi hasil ujian, analisis kesenjangan"
        " (gap), serta visualisasi peta interaktif seluruh Indonesia."
    )

    if "selected_geo_prov" not in st.session_state:
        st.session_state.selected_geo_prov = None

    df_base = _get_region_df(df_matrix_school, dfs)
    if df_base.empty:
        st.warning(
            "⚠️ Belum ada data peserta atau informasi wilayah"
            " (Provinsi/Kabupaten) yang terdeteksi."
        )
        return

    # 1. Pastikan kolom skor CTT tersedia di df_base
    if "skor_konversi_ctt" in df_base.columns and df_base["skor_konversi_ctt"].notna().any():
        df_base["Klasik / CTT (Skala 0-100)"] = pd.to_numeric(df_base["skor_konversi_ctt"], errors="coerce")
    elif "skor_mentah" in df_base.columns:
        vals = pd.to_numeric(df_base["skor_mentah"], errors="coerce")
        n_soal = pd.to_numeric(df_base.get("Jumlah_Soal", 1), errors="coerce").fillna(1).clip(lower=1)
        df_base["Klasik / CTT (Skala 0-100)"] = ((vals / n_soal) * 100.0).round(2)

    # 2. Pastikan kolom skor IRT tersedia di df_base
    irt_results = st.session_state.get("irt_results", {})
    for m_key in ["rasch", "1pl", "2pl", "3pl"]:
        label_name = f"IRT {m_key.upper()} (Skala Konversi)"
        col_db = f"skor_konversi_{m_key}"
        if col_db in df_base.columns and df_base[col_db].notna().any():
            df_base[label_name] = pd.to_numeric(df_base[col_db], errors="coerce")
        elif m_key in irt_results and isinstance(irt_results[m_key], dict):
            df_p = irt_results[m_key].get("df_person")
            if df_p is not None and not df_p.empty:
                df_p = df_p.copy()
                u_col = next((c for c in df_p.columns if str(c).lower().strip() in ["username", "user_id", "id"]), df_p.columns[0])
                df_p["username_clean"] = df_p[u_col].astype(str).str.strip().str.lower()
                s_col = next((c for c in df_p.columns if str(c).lower().strip() in ["nilai konversi", "nilai_konversi", "skor_konversi", "nilai_scaled", "scaled_score", "skor_scaled"]), None)
                if not s_col:
                    num_cols = df_p.select_dtypes(include=[np.number]).columns
                    for nc in num_cols:
                        if str(nc).lower().strip() not in ["theta", "ability", "se", "se_theta", "se_ability", "z_score"]:
                            if df_p[nc].max() > 10 or df_p[nc].min() < -5:
                                s_col = nc
                                break
                if s_col:
                    p_map = dict(zip(df_p["username_clean"], pd.to_numeric(df_p[s_col], errors="coerce")))
                    df_base[label_name] = df_base["username_clean"].map(p_map)

    # Metrik skor yang valid
    metric_candidates = [
        "Klasik / CTT (Skala 0-100)",
        "IRT RASCH (Skala Konversi)",
        "IRT 1PL (Skala Konversi)",
        "IRT 2PL (Skala Konversi)",
        "IRT 3PL (Skala Konversi)",
    ]
    available_metrics = [m for m in metric_candidates if m in df_base.columns and df_base[m].notna().any()]

    if not available_metrics:
        st.info(
            "💡 Belum ada data nilai konversi yang tersedia. Silakan jalankan"
            " **Scoring Engine** atau **Analisis IRT** terlebih dahulu."
        )
        return

    # Sinkronisasi nama mata pelajaran dengan tabel master mapel jika ada
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

    if "mapel" in df_base.columns and mapel_lookup:
        df_base["mapel"] = df_base["mapel"].map(
            lambda x: mapel_lookup.get(str(x).strip().upper(), mapel_lookup.get(str(x).strip(), str(x).strip()))
        )

    # Deteksi Mata Pelajaran yang tersedia
    available_mapels = []
    if "mapel" in df_base.columns:
        available_mapels = sorted([
            str(m).strip() for m in df_base["mapel"].dropna().unique()
            if str(m).strip() not in ["", "nan", "None", "-"]
        ])

    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        prev_idx = 0
        if "selected_region_score_label" in st.session_state and st.session_state["selected_region_score_label"] in available_metrics:
            prev_idx = available_metrics.index(st.session_state["selected_region_score_label"])

        selected_score_label = st.selectbox(
            "🎯 Pilih Metode Skor Konversi:",
            options=available_metrics,
            index=prev_idx,
            key="tab6_score_dropdown",
            help="Pilih model nilai konversi (skala 0-100) yang akan dianalisis distribusinya secara geografis.",
        )
        st.session_state["selected_region_score_label"] = selected_score_label

    df_working = df_base.copy()

    with col_sel2:
        if available_mapels:
            selected_mapels = st.multiselect(
                "📚 Filter & Gabungan Mata Pelajaran:",
                options=available_mapels,
                default=available_mapels,
                key="tab6_mapel_multiselect",
                help="Pilih 1 atau beberapa mata pelajaran. Jika memilih lebih dari 1 (misal 3 mapel), nilai per peserta akan dihitung dari rerata gabungan sebelum dipetakan ke wilayah.",
            )
            if not selected_mapels:
                st.warning("⚠️ Silakan pilih setidaknya satu mata pelajaran untuk dianalisis.")
                return
            df_working = df_working[df_working["mapel"].isin(selected_mapels)].copy()
        else:
            selected_mapels = []

    if available_mapels and len(selected_mapels) > 1:
        st.info(f"✨ **Analisis Wilayah Gabungan ({len(selected_mapels)} Mapel):** {', '.join(selected_mapels)}. Statistik provinsi, peta, dan ranking dihitung dari nilai gabungan rata-rata peserta.")
    elif available_mapels and len(selected_mapels) == 1:
        st.caption(f"📌 **Mata Pelajaran Aktif:** {selected_mapels[0]}")

    val_col_name = selected_score_label
    df_working[val_col_name] = pd.to_numeric(df_working[val_col_name], errors="coerce")
    df_valid = df_working.dropna(subset=[val_col_name]).copy()

    if df_valid.empty:
        st.error("❌ Tidak ada data skor valid untuk mata pelajaran dan metode yang dipilih.")
        return

    # Kelompokkan per peserta terlebih dahulu untuk menghitung nilai rerata komposit gabungan mapel
    group_student_cols = ["username_clean", "kode_provinsi", "nama_provinsi", "nama_kabupaten"]
    for c_extra in ["nama_provinsi_singkat", "nama_singkat", "singkatan"]:
        if c_extra in df_valid.columns and c_extra not in group_student_cols:
            group_student_cols.append(c_extra)

    df_merged = (
        df_valid.groupby(group_student_cols, as_index=False)
        .agg({val_col_name: "mean"})
    )

    if df_merged.empty:
        st.error(
            "❌ Tidak dapat mengaitkan data skor peserta dengan data wilayah."
        )
        return

    st.divider()

    st.markdown("### 🇮🇩 1. Ringkasan & Kesenjangan (Gap) Statistik Nasional")

    avg_nat = df_merged[val_col_name].mean()
    total_peserta = len(df_merged)

    stats_prov = _calculate_region_stats(
        df_merged, "nama_provinsi", val_col_name
    )

    if not stats_prov.empty:
        std_val = df_merged[val_col_name].std()
        top_prov = stats_prov.iloc[0]
        bot_prov = stats_prov.iloc[-1]
        disparitas_val = top_prov["Rata_Rata"] - bot_prov["Rata_Rata"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            "Total Peserta Terjangkau", f"{total_peserta:,}".replace(",", ".")
        )
        m2.metric("Rata-Rata Nasional (Konversi)", f"{avg_nat:.2f}")
        m3.metric("Standar Deviasi", f"{std_val:.2f}")
        m4.metric(
            "Disparitas",
            f"{disparitas_val:.2f} Poin",
            delta=(
                f"Tertinggi: {top_prov['Rata_Rata']:.2f} | "
                f"Terendah: {bot_prov['Rata_Rata']:.2f}"
            ),
            delta_color="off",
        )

    st.divider()

    st.markdown("### 🗺️ 2. Peta Interaktif Sebaran Nilai (Provinsi & Kabupaten)")

    prov_list = sorted([
        p for p in df_merged["nama_provinsi"].unique()
        if p and p != "TIDAK TERDEFINISI" and not str(p).isdigit() and str(p).lower() != "nan"
    ])
    col_nav1, col_theme, col_nav2 = st.columns([5, 4, 3])

    with col_nav1:
        selected_prov_view = st.selectbox(
            "🔎 Pilih Provinsi untuk Drill-Down Detail Kabupaten/Kota (atau"
            " Pilih Nasional):",
            options=["-- TAMPILKAN SELURUH INDONESIA (PROVINSI) --"] + prov_list,
            index=0
            if not st.session_state.selected_geo_prov
            else (
                prov_list.index(st.session_state.selected_geo_prov) + 1
                if st.session_state.selected_geo_prov in prov_list
                else 0
            ),
        )

    with col_theme:
        color_theme_options = {
            "🎨 Elegan Lembut (Merah-Amber-Hijau-Biru)": ["#991B1B", "#D97706", "#059669", "#2563EB"],
            "🌊 Biru Samudra (Deep Ocean)": ["#0F172A", "#0284C7", "#38BDF8", "#93C5FD"],
            "🌿 Emerald Hijau (Teal & Mint)": ["#064E3B", "#059669", "#34D399", "#A7F3D0"],
            "🌌 Plasma Modern": "Plasma",
            "🔬 Viridis Standar": "Viridis",
            "🔥 Magma Hangat": "Magma",
        }
        selected_theme_name = st.selectbox(
            "🎨 Palet Warna Peta:",
            options=list(color_theme_options.keys()),
            index=0,
            help="Pilih gradasi warna peta yang nyaman di mata."
        )
        map_color_scale = color_theme_options[selected_theme_name]

    with col_nav2:
        st.write("")
        st.write("")
        if st.button("🔄 Reset ke Peta Nasional", use_container_width=True):
            st.session_state.selected_geo_prov = None
            st.rerun()

    if selected_prov_view != "-- TAMPILKAN SELURUH INDONESIA (PROVINSI) --":
        st.session_state.selected_geo_prov = selected_prov_view
    else:
        st.session_state.selected_geo_prov = None

    if st.session_state.selected_geo_prov is None:
        geojson_id = _load_geojson_indonesia()

        if not stats_prov.empty and geojson_id:
            for feature in geojson_id.get("features", []):
                props = feature.get("properties", {})
                found_name = None
                for k_prop in [
                    "PROVINSI",
                    "state",
                    "NAME_1",
                    "Propinsi",
                    "provinsi",
                    "name",
                    "NAME_0",
                    "name_province",
                    "nama",
                ]:
                    if k_prop in props and props[k_prop]:
                        found_name = props[k_prop]
                        break
                feature["properties"]["norm_name"] = _clean_province_name(
                    found_name
                )

            stats_prov["Provinsi_Clean"] = stats_prov["nama_provinsi"].apply(
                _clean_province_name
            )

            # Filter hanya provinsi yang valid dan cocok dengan GeoJSON
            valid_prov_features = {
                f["properties"].get("norm_name")
                for f in geojson_id.get("features", [])
                if f.get("properties", {}).get("norm_name")
            }
            stats_prov_map = stats_prov[
                stats_prov["Provinsi_Clean"].isin(valid_prov_features)
            ].copy()

            if not stats_prov_map.empty:
                valid_scores = stats_prov_map["Rata_Rata"].dropna()
                min_val = (
                    float(valid_scores.min()) if not valid_scores.empty else 0.0
                )
                max_val = (
                    float(valid_scores.max()) if not valid_scores.empty else 100.0
                )
                if max_val - min_val < 0.01:
                    min_val -= 1.0
                    max_val += 1.0

                fig_map = px.choropleth(
                    stats_prov_map,
                    geojson=geojson_id,
                    locations="Provinsi_Clean",
                    featureidkey="properties.norm_name",
                    color="Rata_Rata",
                    color_continuous_scale=map_color_scale,
                    range_color=(min_val, max_val),
                    labels={
                        "Rata_Rata": "Rata-Rata Skor",
                        "Provinsi_Clean": "Provinsi",
                    },
                    hover_data={
                        "Jumlah_Peserta": ":,.0f",
                        "Rata_Rata": ":.2f",
                        "Min": ":.2f",
                        "Max": ":.2f",
                    },
                    title=(
                        f"<b>Peta Wilayah Nilai {selected_score_label} per"
                        " Provinsi</b>"
                    ),
                )

                fig_map.update_traces(
                    marker_line_color="#ffffff", marker_line_width=1.2
                )

                # Tambahkan label teks nama singkat provinsi di peta nasional
                prov_centroids = {}
                for f in geojson_id.get("features", []):
                    p_name = f.get("properties", {}).get("norm_name")
                    if p_name:
                        c_lat, c_lon = _get_feature_centroid(f.get("geometry"))
                        if c_lat is not None and c_lon is not None:
                            prov_centroids[p_name] = (c_lat, c_lon)

                # Cek jika ada kolom nama singkat provinsi dari data sekolah / master peserta
                col_short = next(
                    (c for c in df_merged.columns if any(k in str(c).lower() for k in ["singkat", "short", "singkatan", "abbr"])),
                    None
                )
                short_name_map = {}
                if col_short:
                    for p_raw, s_raw in zip(df_merged["nama_provinsi"], df_merged[col_short]):
                        if pd.notna(p_raw) and pd.notna(s_raw) and str(s_raw).strip():
                            short_name_map[_clean_province_name(p_raw)] = str(s_raw).strip().upper()

                p_lats, p_lons, p_texts = [], [], []
                for _, r_p in stats_prov_map.iterrows():
                    pn = r_p["Provinsi_Clean"]
                    if pn in prov_centroids:
                        clat, clon = prov_centroids[pn]
                        p_lats.append(clat)
                        p_lons.append(clon)
                        # Gunakan nama singkat dari tabel sekolah jika ada, atau singkatan standar
                        label_name = short_name_map.get(pn, PROVINSI_SINGKAT_MAP.get(pn, pn))
                        p_texts.append(label_name)

                if p_lats:
                    fig_map.add_trace(
                        go.Scattergeo(
                            lon=p_lons,
                            lat=p_lats,
                            text=p_texts,
                            mode="text",
                            textposition="middle center",
                            textfont=dict(
                                family="Inter, Roboto, Arial, sans-serif",
                                size=9,
                                color="#ffffff",
                            ),
                            hoverinfo="skip",
                            showlegend=False,
                        )
                    )

                fig_map.update_geos(
                    fitbounds="locations",
                    visible=False,
                    showcoastlines=False,
                    showsubunits=False,
                    showland=True,
                    landcolor="#181c24",
                    showocean=True,
                    oceancolor="#0e1117",
                )

                fig_map.update_layout(
                    margin={"r": 0, "t": 40, "l": 0, "b": 0},
                    paper_bgcolor="#0e1117",
                    plot_bgcolor="#0e1117",
                    font_color="#ffffff",
                    height=550,
                )

                st.plotly_chart(fig_map, use_container_width=True)

                unmapped_mask = ~stats_prov["Provinsi_Clean"].isin(valid_prov_features)
                if unmapped_mask.any():
                    n_unmapped = stats_prov.loc[unmapped_mask, "Jumlah_Peserta"].sum()
                    st.caption(
                        f"ℹ️ Catatan: Terdapat {int(n_unmapped):,} peserta dengan informasi wilayah belum dapat dipetakan secara geografis."
                    )
            else:
                st.warning("⚠️ Tidak ada data provinsi yang cocok dengan batas peta GeoJSON.")
        else:
            st.warning(
                "⚠️ Gagal memuat data GeoJSON batas provinsi Indonesia."
            )

    else:
        target_prov = st.session_state.selected_geo_prov
        st.info(
            f"📍 **Peta Detail Kabupaten/Kota di Provinsi {target_prov}**"
        )

        df_prov_kab = df_merged[df_merged["nama_provinsi"] == target_prov]
        stats_kab_local = _calculate_region_stats(
            df_prov_kab, "nama_kabupaten", val_col_name
        )

        geojson_kab = _load_geojson_kabupaten()
        kab_map = get_kode_kabupaten_map()

        if not stats_kab_local.empty:
            # 1. Filter GeoJSON khusus untuk provinsi yang dipilih
            target_features = []
            if geojson_kab:
                for feature in geojson_kab.get("features", []):
                    props = feature.get("properties", {})
                    p_prov = props.get("NAME_1", "")
                    if _clean_province_name(p_prov) == target_prov:
                        fc = {
                            "type": "Feature",
                            "properties": dict(props),
                            "geometry": feature.get("geometry")
                        }
                        raw_kab = props.get("NAME_2") or props.get("kabupaten") or props.get("name")
                        fc["properties"]["norm_kab"] = _clean_kabupaten_name(raw_kab)
                        fc["properties"]["code_kab"] = str(props.get("CC_2", "")).strip()
                        target_features.append(fc)

            prov_geojson = {"type": "FeatureCollection", "features": target_features} if target_features else None

            # 2. Normalisasi penamaan kabupaten di data hasil olahan
            def _resolve_kab_entry(val):
                if not val or pd.isna(val):
                    return "TIDAK TERDEFINISI"
                val_s = str(val).strip()
                m = re.search(r"\b(\d{4})\b", val_s)
                if m and m.group(1) in kab_map:
                    return _clean_kabupaten_name(kab_map[m.group(1)])
                return _clean_kabupaten_name(val_s)

            stats_kab_local["Kabupaten_Clean"] = stats_kab_local["nama_kabupaten"].apply(_resolve_kab_entry)

            valid_kab_features = {
                f["properties"].get("norm_kab")
                for f in target_features
                if f.get("properties", {}).get("norm_kab")
            } if target_features else set()

            stats_kab_map = stats_kab_local[
                (stats_kab_local["Kabupaten_Clean"] != "TIDAK TERDEFINISI")
                & (stats_kab_local["Kabupaten_Clean"].isin(valid_kab_features))
            ].copy()

            if not stats_kab_map.empty and prov_geojson:
                v_scores = stats_kab_map["Rata_Rata"].dropna()
                min_k = float(v_scores.min()) if not v_scores.empty else 0.0
                max_k = float(v_scores.max()) if not v_scores.empty else 100.0

                if max_k - min_k < 0.01:
                    min_k -= 1.0
                    max_k += 1.0

                fig_kab_map = px.choropleth(
                    stats_kab_map,
                    geojson=prov_geojson,
                    locations="Kabupaten_Clean",
                    featureidkey="properties.norm_kab",
                    color="Rata_Rata",
                    color_continuous_scale=map_color_scale,
                    range_color=(min_k, max_k),
                    labels={
                        "Rata_Rata": "Rata-Rata Skor",
                        "Kabupaten_Clean": "Kabupaten / Kota",
                    },
                    hover_data={
                        "Jumlah_Peserta": ":,.0f",
                        "Rata_Rata": ":.2f",
                        "Min": ":.2f",
                        "Max": ":.2f",
                    },
                    title=(
                        f"<b>Sebaran Nilai Kabupaten/Kota di Provinsi {target_prov}</b>"
                    ),
                )

                fig_kab_map.update_traces(
                    marker_line_color="#ffffff", marker_line_width=1.5
                )

                # Tambahkan label teks nama kabupaten/kota di peta drill-down
                kab_centroids = {}
                for fc in target_features:
                    kn = fc["properties"].get("norm_kab")
                    if kn:
                        c_lat, c_lon = _get_feature_centroid(fc.get("geometry"))
                        if c_lat is not None and c_lon is not None:
                            kab_centroids[kn] = (c_lat, c_lon)

                k_lats, k_lons, k_texts = [], [], []
                for _, r_k in stats_kab_map.iterrows():
                    kn = r_k["Kabupaten_Clean"]
                    if kn in kab_centroids:
                        clat, clon = kab_centroids[kn]
                        k_lats.append(clat)
                        k_lons.append(clon)
                        k_texts.append(kn)

                if k_lats:
                    fig_kab_map.add_trace(
                        go.Scattergeo(
                            lon=k_lons,
                            lat=k_lats,
                            text=k_texts,
                            mode="text",
                            textposition="middle center",
                            textfont=dict(
                                family="Arial, sans-serif",
                                size=10,
                                color="#ffffff",
                            ),
                            hoverinfo="skip",
                            showlegend=False,
                        )
                    )

                fig_kab_map.update_geos(
                    fitbounds="locations",
                    visible=False,
                    showcoastlines=False,
                    showsubunits=False,
                    showland=False,
                    showocean=False,
                )

                fig_kab_map.update_layout(
                    margin={"r": 0, "t": 40, "l": 0, "b": 0},
                    paper_bgcolor="#0e1117",
                    plot_bgcolor="#0e1117",
                    font_color="#ffffff",
                    height=520,
                )

                st.plotly_chart(fig_kab_map, use_container_width=True)
            else:
                st.info(
                    f"ℹ️ Peta polygon kabupaten/kota untuk **{target_prov}** sedang tidak tersedia, menampilkan grafik sebaran nilai di bawah."
                )

            # Tampilkan grafik peringkat Kabupaten/Kota di provinsi terpilih
            df_chart_local = stats_kab_local[stats_kab_local["Kabupaten_Clean"] != "TIDAK TERDEFINISI"].sort_values(
                by="Rata_Rata", ascending=False
            )
            if not df_chart_local.empty:
                st.markdown(f"#### 📊 Peringkat Kabupaten/Kota di Provinsi {target_prov}")
                fig_local_bar = px.bar(
                    df_chart_local,
                    x="Kabupaten_Clean",
                    y="Rata_Rata",
                    color="Rata_Rata",
                    color_continuous_scale=map_color_scale,
                    text_auto=".1f",
                    labels={"Kabupaten_Clean": "Kabupaten / Kota", "Rata_Rata": "Rata-Rata Skor"},
                    title=f"<b>Rata-Rata Nilai per Kabupaten/Kota di {target_prov}</b>",
                )
                fig_local_bar.update_layout(
                    paper_bgcolor="#0e1117",
                    plot_bgcolor="#0e1117",
                    font_color="#ffffff",
                    height=380,
                    margin={"r": 0, "t": 40, "l": 0, "b": 0},
                )
                st.plotly_chart(fig_local_bar, use_container_width=True)
        else:
            st.warning(
                f"⚠️ Belum ada data peserta untuk provinsi **{target_prov}**."
            )

    st.divider()

    st.markdown("### 🏛️ 3. Grafik & Peringkat per Provinsi")

    fig_prov = px.bar(
        stats_prov,
        x="nama_provinsi",
        y="Rata_Rata",
        color="Rata_Rata",
        color_continuous_scale=map_color_scale,
        text_auto=".1f",
        title=(
            "<b>Rata-Rata Nilai Konversi"
            f" ({selected_score_label}) per Provinsi</b>"
        ),
        labels={"Rata_Rata": "Rata-Rata Nilai", "nama_provinsi": "Provinsi"},
    )
    fig_prov.add_hline(
        y=avg_nat,
        line_dash="dash",
        line_color="red",
        annotation_text=f"Rata-rata Nasional ({avg_nat:.2f})",
        annotation_position="top right",
    )
    fig_prov.update_layout(
        template="plotly_dark",
        height=450,
        xaxis_tickangle=-45,
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
    )
    st.plotly_chart(fig_prov, use_container_width=True)

    with st.expander(
        "📋 Tabel Agregasi Statistik Tingkat Provinsi", expanded=False
    ):
        st.dataframe(
            stats_prov.drop(columns=["Provinsi_Clean"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    st.markdown("### 🏙️ 4. Analisis Tingkat Kabupaten / Kota")

    tab_kab1, tab_kab2 = st.tabs(
        [
            "📌 Filter Berdasarkan Provinsi",
            "🌐 Peringkat Kabupaten/Kota Nasional",
        ]
    )

    with tab_kab1:
        list_prov = sorted(df_merged["nama_provinsi"].unique())
        selected_prov = st.selectbox(
            "Pilih Provinsi untuk Detail Kabupaten/Kota:", options=list_prov
        )

        df_sub_kab = df_merged[df_merged["nama_provinsi"] == selected_prov]
        stats_kab_sub = _calculate_region_stats(
            df_sub_kab, "nama_kabupaten", val_col_name
        )

        if not stats_kab_sub.empty:
            avg_sub_prov = df_sub_kab[val_col_name].mean()

            fig_kab_sub = px.bar(
                stats_kab_sub,
                x="nama_kabupaten",
                y="Rata_Rata",
                color="Rata_Rata",
                color_continuous_scale=map_color_scale,
                text_auto=".1f",
                title=(
                    "<b>Rata-Rata Nilai Konversi Kabupaten/Kota di"
                    f" {selected_prov}</b>"
                ),
                labels={
                    "Rata_Rata": "Rata-Rata Nilai",
                    "nama_kabupaten": "Kabupaten / Kota",
                },
            )
            fig_kab_sub.add_hline(
                y=avg_sub_prov,
                line_dash="dash",
                line_color="yellow",
                annotation_text=f"Rata-rata Provinsi ({avg_sub_prov:.2f})",
            )
            fig_kab_sub.update_layout(
                template="plotly_dark",
                height=420,
                xaxis_tickangle=-45,
                paper_bgcolor="#0e1117",
                plot_bgcolor="#0e1117",
            )
            st.plotly_chart(fig_kab_sub, use_container_width=True)

            st.dataframe(
                stats_kab_sub, use_container_width=True, hide_index=True
            )

    with tab_kab2:
        stats_kab_nat = _calculate_region_stats(
            df_merged, "nama_kabupaten", val_col_name
        )

        st.caption("Menampilkan 30 Kabupaten/Kota dengan capaian tertinggi:")
        fig_kab_nat = px.bar(
            stats_kab_nat.head(30),
            x="nama_kabupaten",
            y="Rata_Rata",
            color="Rata_Rata",
            color_continuous_scale=map_color_scale,
            text_auto=".1f",
            title="<b>Top 30 Kabupaten/Kota Tertinggi se-Indonesia</b>",
            labels={
                "Rata_Rata": "Rata-Rata Nilai",
                "nama_kabupaten": "Kabupaten / Kota",
            },
        )
        fig_kab_nat.update_layout(
            template="plotly_dark",
            height=450,
            xaxis_tickangle=-45,
            paper_bgcolor="#0e1117",
            plot_bgcolor="#0e1117",
        )
        st.plotly_chart(fig_kab_nat, use_container_width=True)

        with st.expander(
            "📋 Seluruh Data Agregasi Kabupaten/Kota se-Indonesia",
            expanded=False,
        ):
            st.dataframe(
                stats_kab_nat, use_container_width=True, hide_index=True
            )

    st.divider()

    st.markdown("### 💾 Unduh Laporan Wilayah")
    c_dl1, c_dl2 = st.columns(2)
    with c_dl1:
        csv_prov = convert_df_to_csv_bytes(
            stats_prov.drop(columns=["Provinsi_Clean"], errors="ignore")
        )
        st.download_button(
            "📄 Unduh CSV Statistik Provinsi",
            data=csv_prov,
            file_name=(
                "Statistik_Wilayah_Provinsi_"
                f"{selected_score_label.replace(' ', '_')}.csv"
            ),
            mime="text/csv",
            use_container_width=True,
        )
    with c_dl2:
        stats_kab_all = _calculate_region_stats(
            df_merged, "nama_kabupaten", val_col_name
        )
        csv_kab = convert_df_to_csv_bytes(stats_kab_all)
        st.download_button(
            "📄 Unduh CSV Statistik Kabupaten/Kota",
            data=csv_kab,
            file_name=(
                "Statistik_Wilayah_Kabupaten_"
                f"{selected_score_label.replace(' ', '_')}.csv"
            ),
            mime="text/csv",
            use_container_width=True,
        )