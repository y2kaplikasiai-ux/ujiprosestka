# db_helper.py
import os
import urllib.parse
import pymysql
import pandas as pd
from sqlalchemy import create_engine, text

# Konfigurasi Default dari Environment
DEFAULT_HOST = os.getenv("MYSQL_HOST", "db")
DEFAULT_USER = os.getenv("MYSQL_USER", "root")
DEFAULT_PASS = os.getenv("MYSQL_PASSWORD", "password_rahasia_anda")
DEFAULT_DB = os.getenv("MYSQL_DATABASE", "db_psikometri")
DEFAULT_PORT = os.getenv("MYSQL_PORT", "3306")

# Cache koneksi aktif agar tidak mencoba fallback berulang-ulang
_ACTIVE_CONFIG = None


def get_active_config():
    """Mengambil konfigurasi aktif (dari session_state, env, atau cache)."""
    global _ACTIVE_CONFIG
    
    # Cek apakah ada konfigurasi di Streamlit session_state
    try:
        import streamlit as st
        if "custom_db_host" in st.session_state and st.session_state["custom_db_host"]:
            return {
                "host": st.session_state["custom_db_host"],
                "port": int(st.session_state.get("custom_db_port", 3306)),
                "user": st.session_state.get("custom_db_user", "root"),
                "password": st.session_state.get("custom_db_pass", ""),
                "database": st.session_state.get("custom_db_name", DEFAULT_DB),
            }
    except Exception:
        pass

    if _ACTIVE_CONFIG is not None:
        return _ACTIVE_CONFIG

    return {
        "host": DEFAULT_HOST,
        "port": int(DEFAULT_PORT),
        "user": DEFAULT_USER,
        "password": DEFAULT_PASS,
        "database": DEFAULT_DB,
    }


def _create_engine_from_config(cfg, timeout=3):
    """Membuat SQLAlchemy engine dengan timeout singkat untuk uji koneksi."""
    encoded_pass = urllib.parse.quote_plus(cfg["password"])
    url = (
        f"mysql+pymysql://{cfg['user']}:{encoded_pass}"
        f"@{cfg['host']}:{cfg['port']}/{cfg['database']}"
    )
    return create_engine(
        url,
        pool_recycle=3600,
        connect_args={"connect_timeout": timeout}
    )


def _ensure_database_exists(cfg, timeout=3):
    """Memastikan database dibuat jika belum ada di server MySQL."""
    try:
        conn = pymysql.connect(
            host=cfg["host"],
            user=cfg["user"],
            password=cfg["password"],
            port=cfg["port"],
            connect_timeout=timeout,
        )
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{cfg['database']}`;")
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_db_connection(force_reconnect=False):
    """
    Membuat SQLAlchemy Engine untuk MySQL dengan auto-discovery:
    1. Mencoba konfigurasi aktif (env/session/default 'db')
    2. Jika gagal (misal di luar Docker), mencoba 'localhost'/'127.0.0.1' dengan password kosong (XAMPP/Laragon)
    3. Jika gagal, mencoba 'localhost' dengan password docker default
    """
    global _ACTIVE_CONFIG

    if force_reconnect:
        _ACTIVE_CONFIG = None

    candidates = []

    # 1. Konfigurasi yang sedang aktif
    cfg = get_active_config()
    candidates.append(cfg)

    # 2. Kandidat fallback lokal jika host default ('db') gagal diakses
    if cfg["host"] != "127.0.0.1" and cfg["host"] != "localhost":
        candidates.append({
            "host": "127.0.0.1",
            "port": 3306,
            "user": "root",
            "password": "",  # Standar XAMPP/Laragon
            "database": DEFAULT_DB,
        })
        candidates.append({
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "",
            "database": DEFAULT_DB,
        })
        candidates.append({
            "host": "127.0.0.1",
            "port": 3306,
            "user": "root",
            "password": "password_rahasia_anda",
            "database": DEFAULT_DB,
        })

    for c in candidates:
        try:
            # Pastikan database ada sebelum connect
            _ensure_database_exists(c, timeout=2)
            
            engine = _create_engine_from_config(c, timeout=2)
            with engine.connect() as test_conn:
                test_conn.execute(text("SELECT 1;"))
            
            # Berhasil terkoneksi! Simpan ke cache
            _ACTIVE_CONFIG = c
            return engine
        except Exception:
            continue

    return None


def check_db_status():
    """Mengembalikan tuple (status_terhubung: bool, info_koneksi: str)."""
    engine = get_db_connection()
    if engine is None:
        cfg = get_active_config()
        return False, f"Tidak terhubung (Host: {cfg['host']}:{cfg['port']}, User: {cfg['user']})"
    cfg = get_active_config()
    return True, f"Terhubung ke MySQL ({cfg['host']}:{cfg['port']} / DB: {cfg['database']})"


def init_db_tables() -> bool:
    """Mempersiapkan struktur tabel MySQL jika belum ada, serta memastikan kolom mapel tersedia."""
    engine = get_db_connection()
    if engine is None:
        return False

    try:
        with engine.begin() as conn:
            # 1. Tabel Peserta & Skor (Primary Key: username, mapel)
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tb_peserta_skor (
                    username VARCHAR(100) NOT NULL,
                    mapel VARCHAR(100) NOT NULL DEFAULT 'UMUM',
                    nama_sekolah VARCHAR(255),
                    kode_sekolah VARCHAR(50),
                    nama_kabupaten VARCHAR(100),
                    nama_provinsi VARCHAR(100),
                    kode_provinsi VARCHAR(10),
                    skor_mentah FLOAT,
                    skor_konversi_ctt DECIMAL(10,2),
                    skor_konversi_rasch DECIMAL(10,2),
                    skor_konversi_1pl DECIMAL(10,2),
                    skor_konversi_2pl DECIMAL(10,2),
                    skor_konversi_3pl DECIMAL(10,2),
                    Jumlah_Soal INT,
                    PRIMARY KEY (username, mapel),
                    INDEX idx_sekolah (kode_sekolah),
                    INDEX idx_provinsi (kode_provinsi),
                    INDEX idx_mapel (mapel)
                );
            """
                )
            )

            # Cek apakah kolom mapel sudah ada di tb_peserta_skor (jika tabel lama sudah ada)
            try:
                res = conn.execute(text("SHOW COLUMNS FROM tb_peserta_skor LIKE 'mapel';")).fetchall()
                if not res:
                    conn.execute(text("ALTER TABLE tb_peserta_skor DROP PRIMARY KEY, ADD COLUMN mapel VARCHAR(100) NOT NULL DEFAULT 'UMUM' AFTER username, ADD PRIMARY KEY (username, mapel);"))
            except Exception:
                pass

            # 2. Tabel Parameter Soal (Primary Key: kode_soal, mapel)
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tb_soal_parameter (
                    kode_soal VARCHAR(100) NOT NULL,
                    mapel VARCHAR(100) NOT NULL DEFAULT 'UMUM',
                    tingkat_kesukaran_ctt FLOAT,
                    daya_beda_ctt FLOAT,
                    rekomendasi VARCHAR(100),
                    b_rasch FLOAT,
                    b_1pl FLOAT,
                    a_2pl FLOAT,
                    b_2pl FLOAT,
                    a_3pl FLOAT,
                    b_3pl FLOAT,
                    c_3pl FLOAT,
                    PRIMARY KEY (kode_soal, mapel),
                    INDEX idx_soal_mapel (mapel)
                );
            """
                )
            )

            try:
                res_soal = conn.execute(text("SHOW COLUMNS FROM tb_soal_parameter LIKE 'mapel';")).fetchall()
                if not res_soal:
                    conn.execute(text("ALTER TABLE tb_soal_parameter DROP PRIMARY KEY, ADD COLUMN mapel VARCHAR(100) NOT NULL DEFAULT 'UMUM' AFTER kode_soal, ADD PRIMARY KEY (kode_soal, mapel);"))
            except Exception:
                pass

            # 3. Tabel Ringkasan Model
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tb_model_summary (
                    metode_model VARCHAR(20) PRIMARY KEY,
                    reliabilitas FLOAT,
                    log_likelihood FLOAT,
                    aic FLOAT,
                    bic FLOAT
                );
            """
                )
            )

            # 4. Tabel Agregasi Sekolah
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tb_sekolah_agregasi (
                    kode_sekolah VARCHAR(50) PRIMARY KEY,
                    nama_sekolah VARCHAR(255),
                    nama_kabupaten VARCHAR(100),
                    nama_provinsi VARCHAR(100),
                    jumlah_peserta INT,
                    rata_skor_mentah FLOAT,
                    rata_skor_ctt DECIMAL(10,2),
                    rata_skor_rasch DECIMAL(10,2),
                    rata_skor_1pl DECIMAL(10,2),
                    rata_skor_2pl DECIMAL(10,2),
                    rata_skor_3pl DECIMAL(10,2)
                );
            """
                )
            )

            # 5. Tabel Master Sekolah
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tb_master_sekolah (
                    kode_sekolah VARCHAR(50) PRIMARY KEY,
                    nama_sekolah VARCHAR(255),
                    nama_kabupaten VARCHAR(100),
                    nama_provinsi VARCHAR(100),
                    kode_provinsi VARCHAR(10)
                );
            """
                )
            )

            # 6. Tabel Master Biodata Siswa
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tb_master_biodata (
                    username VARCHAR(100) PRIMARY KEY,
                    nama VARCHAR(255),
                    kode_sekolah VARCHAR(50),
                    nama_sekolah VARCHAR(255),
                    nama_kabupaten VARCHAR(100),
                    nama_provinsi VARCHAR(100),
                    kd_prop VARCHAR(10),
                    INDEX idx_bio_sekolah (kode_sekolah)
                );
            """
                )
            )

            # 7. Tabel Master Kunci Jawaban
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tb_master_kunci (
                    kode_soal VARCHAR(100) NOT NULL,
                    mapel VARCHAR(100) NOT NULL DEFAULT 'UMUM',
                    kunci VARCHAR(20),
                    PRIMARY KEY (kode_soal, mapel),
                    INDEX idx_mkunci_mapel (mapel)
                );
            """
                )
            )

            # 8. Tabel Master Mapel
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tb_master_mapel (
                    kode_mapel VARCHAR(50) PRIMARY KEY,
                    nama_mapel VARCHAR(100)
                );
            """
                )
            )

        return True
    except Exception as e:
        print(f"Gagal inisialisasi tabel database: {e}")
        return False


def _clean_dataframe(df: pd.DataFrame, key_column: str) -> pd.DataFrame:
    """Fungsi pembantu untuk membersihkan kolom primary key dari NaN/kosong & duplikasi."""
    if df is None or df.empty:
        return df

    df_clean = df.copy()

    if key_column not in df_clean.columns:
        if key_column == "username":
            for alt in ["ID Peserta", "id_peserta", "id", "user_id", "Username"]:
                if alt in df_clean.columns:
                    df_clean["username"] = df_clean[alt]
                    break
        elif key_column == "kode_soal":
            for alt in ["Kode_Soal", "Item", "item", "soal", "No."]:
                if alt in df_clean.columns:
                    df_clean["kode_soal"] = df_clean[alt]
                    break
        elif key_column == "kode_sekolah":
            for alt in ["Kode Sekolah", "npsn", "NPSN"]:
                if alt in df_clean.columns:
                    df_clean["kode_sekolah"] = df_clean[alt]
                    break

    if key_column not in df_clean.columns:
        return df_clean

    df_clean = df_clean.dropna(subset=[key_column])
    df_clean[key_column] = df_clean[key_column].astype(str).str.strip()
    df_clean = df_clean[~df_clean[key_column].isin(['', 'nan', 'None', 'NONE'])]

    # Jika ada kolom mapel dan key_column adalah username atau kode_soal, deduplikasi berdasarkan (key, mapel)
    if "mapel" in df_clean.columns and key_column in ["username", "kode_soal"]:
        df_clean["mapel"] = df_clean["mapel"].fillna("UMUM").astype(str).str.strip().str.upper()
        df_clean = df_clean.drop_duplicates(subset=[key_column, "mapel"], keep='first')
    else:
        df_clean = df_clean.drop_duplicates(subset=[key_column], keep='first')

    return df_clean


def prepare_and_save_analysis(
    df_peserta: pd.DataFrame = None,
    df_soal: pd.DataFrame = None,
    df_summary: pd.DataFrame = None,
    df_sekolah: pd.DataFrame = None,
) -> tuple[bool, str]:
    """
    Menyimpan hasil analisis baru ke MySQL Server dengan aman:
    Hanya menimpa (TRUNCATE) tabel yang datanya benar-benar disediakan,
    sehingga tabel yang tidak disertakan tetap utuh.
    """
    try:
        engine = get_db_connection()
        if engine is None:
            return False, "Tidak dapat terhubung ke MySQL Server (Periksa host/password)."

        if not init_db_tables():
            return False, "Gagal menginisialisasi skema tabel database."

        # Menormalisasi kolom sekolah pada data peserta
        if df_peserta is not None and not df_peserta.empty:
            df_peserta = df_peserta.copy()
            if "nama_sekolah" not in df_peserta.columns:
                for alt_n in ["sekolah", "nama_lembaga", "Nama_Sekolah"]:
                    if alt_n in df_peserta.columns:
                        df_peserta["nama_sekolah"] = df_peserta[alt_n]
                        break
            if "kode_sekolah" not in df_peserta.columns:
                for alt_k in ["npsn", "_school_key", "NPSN", "Kode Sekolah"]:
                    if alt_k in df_peserta.columns:
                        df_peserta["kode_sekolah"] = df_peserta[alt_k]
                        break

        df_peserta_clean = _clean_dataframe(df_peserta, "username") if df_peserta is not None else None
        df_soal_clean = _clean_dataframe(df_soal, "kode_soal") if df_soal is not None else None
        df_summary_clean = _clean_dataframe(df_summary, "metode_model") if df_summary is not None else None
        df_sekolah_clean = _clean_dataframe(df_sekolah, "kode_sekolah") if df_sekolah is not None else None

        # Filter kolom sesuai skema tabel
        if df_peserta_clean is not None and not df_peserta_clean.empty:
            valid_cols = [
                "username", "mapel", "nama_sekolah", "kode_sekolah", "nama_kabupaten",
                "nama_provinsi", "kode_provinsi", "skor_mentah", "skor_konversi_ctt",
                "skor_konversi_rasch", "skor_konversi_1pl", "skor_konversi_2pl",
                "skor_konversi_3pl", "Jumlah_Soal"
            ]
            for col in valid_cols:
                if col not in df_peserta_clean.columns:
                    if col == "mapel":
                        df_peserta_clean[col] = "UMUM"
                    else:
                        df_peserta_clean[col] = None
            df_peserta_clean = df_peserta_clean[valid_cols]

        if df_soal_clean is not None and not df_soal_clean.empty:
            valid_soal_cols = [
                "kode_soal", "mapel", "tingkat_kesukaran_ctt", "daya_beda_ctt", "rekomendasi",
                "b_rasch", "b_1pl", "a_2pl", "b_2pl", "a_3pl", "b_3pl", "c_3pl"
            ]
            for col in valid_soal_cols:
                if col not in df_soal_clean.columns:
                    if col == "mapel":
                        df_soal_clean[col] = "UMUM"
                    else:
                        df_soal_clean[col] = None
            df_soal_clean = df_soal_clean[valid_soal_cols]

        with engine.begin() as conn:
            # 1. Peserta & Skor (Mendukung mode Incremental per Mata Pelajaran)
            if df_peserta_clean is not None and not df_peserta_clean.empty:
                mapels_active = [
                    str(m).strip()
                    for m in df_peserta_clean["mapel"].dropna().unique()
                    if str(m).strip()
                ]

                # Hapus data sebelumnya hanya untuk mata pelajaran yang aktif diproses saat ini
                if mapels_active:
                    for m_act in mapels_active:
                        conn.execute(
                            text("DELETE FROM tb_peserta_skor WHERE mapel = :m;"),
                            {"m": m_act},
                        )
                else:
                    conn.execute(text("TRUNCATE TABLE tb_peserta_skor;"))

                df_peserta_clean.to_sql(
                    "tb_peserta_skor",
                    conn,
                    if_exists="append",
                    index=False,
                    chunksize=10000,
                )

            # 2. Parameter Soal
            if df_soal_clean is not None and not df_soal_clean.empty:
                mapels_soal = [
                    str(m).strip()
                    for m in df_soal_clean["mapel"].dropna().unique()
                    if str(m).strip()
                ]
                if mapels_soal:
                    for m_soal in mapels_soal:
                        conn.execute(
                            text("DELETE FROM tb_soal_parameter WHERE mapel = :m;"),
                            {"m": m_soal},
                        )
                else:
                    conn.execute(text("TRUNCATE TABLE tb_soal_parameter;"))

                df_soal_clean.to_sql(
                    "tb_soal_parameter", conn, if_exists="append", index=False
                )

            # 3. Model Summary
            if df_summary_clean is not None and not df_summary_clean.empty:
                conn.execute(text("TRUNCATE TABLE tb_model_summary;"))
                df_summary_clean.to_sql(
                    "tb_model_summary", conn, if_exists="append", index=False
                )

            # 4. Agregasi Sekolah (Hitung ulang otomatis dari akumulasi seluruh mapel di tb_peserta_skor)
            try:
                conn.execute(text("TRUNCATE TABLE tb_sekolah_agregasi;"))
                conn.execute(
                    text(
                        """
                    INSERT INTO tb_sekolah_agregasi (
                        kode_sekolah, nama_sekolah, nama_kabupaten, nama_provinsi,
                        jumlah_peserta, rata_skor_mentah, rata_skor_ctt,
                        rata_skor_rasch, rata_skor_1pl, rata_skor_2pl, rata_skor_3pl
                    )
                    SELECT 
                        kode_sekolah,
                        MAX(COALESCE(nama_sekolah, kode_sekolah)) as nama_sekolah,
                        MAX(COALESCE(nama_kabupaten, '-')) as nama_kabupaten,
                        MAX(COALESCE(nama_provinsi, '-')) as nama_provinsi,
                        COUNT(DISTINCT username) as jumlah_peserta,
                        ROUND(AVG(skor_mentah), 2) as rata_skor_mentah,
                        ROUND(AVG(skor_konversi_ctt), 2) as rata_skor_ctt,
                        ROUND(AVG(skor_konversi_rasch), 2) as rata_skor_rasch,
                        ROUND(AVG(skor_konversi_1pl), 2) as rata_skor_1pl,
                        ROUND(AVG(skor_konversi_2pl), 2) as rata_skor_2pl,
                        ROUND(AVG(skor_konversi_3pl), 2) as rata_skor_3pl
                    FROM tb_peserta_skor
                    WHERE kode_sekolah IS NOT NULL AND TRIM(kode_sekolah) != ''
                    GROUP BY kode_sekolah;
                """
                    )
                )
            except Exception as e_agg:
                # Fallback jika query agregasi SQL mengalami kendala
                if df_sekolah_clean is not None and not df_sekolah_clean.empty:
                    df_sekolah_clean.to_sql(
                        "tb_sekolah_agregasi", conn, if_exists="append", index=False
                    )

        return True, "Berhasil menyimpan seluruh data ke MySQL Server."
    except Exception as e:
        return False, f"Kendala penyimpanan DB: {e}"


def reset_database(mode: str = "response_only") -> tuple[bool, str]:
    """
    Mereset database.
    - 'response_only': Mengosongkan data respon, skor, butir, dan agregasi sekolah.
                       Tabel master biodata, sekolah, mapel, dan kunci TETAP AMAN.
    - 'full': Mengosongkan seluruh tabel database termasuk master.
    """
    try:
        engine = get_db_connection()
        if engine is None:
            return False, "Tidak dapat terhubung ke MySQL Server."

        # Pastikan seluruh struktur tabel sudah diinisialisasi terlebih dahulu
        try:
            init_db_tables()
        except Exception:
            pass

        tables_to_clear = [
            "tb_peserta_skor",
            "tb_soal_parameter",
            "tb_sekolah_agregasi",
            "tb_model_summary",
        ]
        if mode == "full":
            tables_to_clear.extend([
                "tb_master_biodata",
                "tb_master_sekolah",
                "tb_master_kunci",
                "tb_master_mapel",
            ])

        with engine.begin() as conn:
            for tbl in tables_to_clear:
                try:
                    conn.execute(text(f"TRUNCATE TABLE {tbl};"))
                except Exception:
                    try:
                        conn.execute(text(f"DELETE FROM {tbl};"))
                    except Exception:
                        pass

        if mode == "full":
            msg = "Berhasil melakukan Reset Total Database (Semua data respon & tabel master telah dibersihkan)."
        else:
            msg = "Berhasil membersihkan data respon & hasil analisis. Tabel master siswa & sekolah tetap aman tersimpan."
        return True, msg
    except Exception as e:
        return False, f"Gagal mereset database: {e}"


def save_master_data_to_db(dfs: dict) -> tuple[bool, str]:
    """Menyimpan berkas master (biodata, sekolah, kunci, mapel) ke MySQL jika diunggah."""
    if not dfs or not isinstance(dfs, dict):
        return True, "Tidak ada data master."
    try:
        engine = get_db_connection()
        if engine is None:
            return False, "Koneksi DB gagal."

        with engine.begin() as conn:
            # 1. Master Sekolah
            if "sekolah" in dfs and dfs["sekolah"] is not None and not dfs["sekolah"].empty:
                df_sek = dfs["sekolah"].copy()
                df_sek.columns = [str(c).strip().lower() for c in df_sek.columns]
                col_k = next((c for c in df_sek.columns if "sekolah" in c and ("kode" in c or "id" in c or "npsn" in c)), df_sek.columns[0])
                col_n = next((c for c in df_sek.columns if "nama" in c and "sekolah" in c), None)
                col_kab = next((c for c in df_sek.columns if "kabupaten" in c or "kota" in c), None)
                col_prov = next((c for c in df_sek.columns if "provinsi" in c or "propinsi" in c), None)
                col_kdp = next((c for c in df_sek.columns if "kd_prop" in c or "kode_prov" in c), None)

                df_sek_save = pd.DataFrame()
                df_sek_save["kode_sekolah"] = df_sek[col_k].astype(str).str.strip().str.upper()
                df_sek_save["nama_sekolah"] = df_sek[col_n].astype(str).str.strip() if col_n else df_sek_save["kode_sekolah"]
                df_sek_save["nama_kabupaten"] = df_sek[col_kab].astype(str).str.strip() if col_kab else "-"
                df_sek_save["nama_provinsi"] = df_sek[col_prov].astype(str).str.strip() if col_prov else "-"
                df_sek_save["kode_provinsi"] = df_sek[col_kdp].astype(str).str.strip() if col_kdp else "-"
                df_sek_save = df_sek_save.drop_duplicates(subset=["kode_sekolah"])

                conn.execute(text("TRUNCATE TABLE tb_master_sekolah;"))
                df_sek_save.to_sql("tb_master_sekolah", conn, if_exists="append", index=False, chunksize=5000)

            # 2. Master Biodata
            if "biodata" in dfs and dfs["biodata"] is not None and not dfs["biodata"].empty:
                df_bio = dfs["biodata"].copy()
                df_bio.columns = [str(c).strip().lower() for c in df_bio.columns]
                col_u = next((c for c in df_bio.columns if str(c) in ["username", "user_id", "id_peserta", "nisn", "id"]), df_bio.columns[0])
                col_n = next((c for c in df_bio.columns if "nama" in c and "sekolah" not in c and "kabupaten" not in c and "provinsi" not in c), None)
                col_sek = next((c for c in df_bio.columns if "sekolah" in c), None)
                col_kab = next((c for c in df_bio.columns if "kabupaten" in c or "kota" in c), None)
                col_prov = next((c for c in df_bio.columns if "provinsi" in c or "propinsi" in c), None)
                col_kdp = next((c for c in df_bio.columns if "kd_prop" in c or "kode_prov" in c), None)

                df_bio_save = pd.DataFrame()
                df_bio_save["username"] = df_bio[col_u].astype(str).str.strip()
                df_bio_save["nama"] = df_bio[col_n].astype(str).str.strip() if col_n else "-"
                df_bio_save["kode_sekolah"] = df_bio[col_sek].astype(str).str[:9].str.upper() if col_sek else "-"
                df_bio_save["nama_sekolah"] = df_bio[col_sek].astype(str).str.strip() if col_sek else "-"
                df_bio_save["nama_kabupaten"] = df_bio[col_kab].astype(str).str.strip() if col_kab else "-"
                df_bio_save["nama_provinsi"] = df_bio[col_prov].astype(str).str.strip() if col_prov else "-"
                df_bio_save["kd_prop"] = df_bio[col_kdp].astype(str).str.strip() if col_kdp else "-"
                df_bio_save = df_bio_save.drop_duplicates(subset=["username"])

                conn.execute(text("TRUNCATE TABLE tb_master_biodata;"))
                df_bio_save.to_sql("tb_master_biodata", conn, if_exists="append", index=False, chunksize=10000)

            # 3. Master Kunci
            if "kunci" in dfs and dfs["kunci"] is not None and not dfs["kunci"].empty:
                df_k = dfs["kunci"].copy()
                df_k.columns = [str(c).strip().lower() for c in df_k.columns]
                col_s = next((c for c in df_k.columns if any(kw in c for kw in ["kode_soal", "id_soal", "soal", "kd_soal"])), df_k.columns[0])
                col_m = next((c for c in df_k.columns if any(kw in c for kw in ["mapel", "mata_pelajaran", "subject"])), None)
                col_ans = next((c for c in df_k.columns if any(kw in c for kw in ["kunci", "jawaban", "key"])), df_k.columns[1] if len(df_k.columns)>1 else df_k.columns[0])

                df_k_save = pd.DataFrame()
                df_k_save["kode_soal"] = df_k[col_s].astype(str).str.strip()
                df_k_save["mapel"] = df_k[col_m].astype(str).str.strip().str.upper() if col_m else "UMUM"
                df_k_save["kunci"] = df_k[col_ans].astype(str).str.strip().str.upper()
                df_k_save = df_k_save.drop_duplicates(subset=["kode_soal", "mapel"])

                for mpl in df_k_save["mapel"].unique():
                    conn.execute(text("DELETE FROM tb_master_kunci WHERE mapel = :m;"), {"m": mpl})
                df_k_save.to_sql("tb_master_kunci", conn, if_exists="append", index=False)

            # 4. Master Mapel
            if "mapel" in dfs and dfs["mapel"] is not None and not dfs["mapel"].empty:
                df_m = dfs["mapel"].copy()
                df_m.columns = [str(c).strip().lower() for c in df_m.columns]
                col_km = next((c for c in df_m.columns if "kode" in c or "id" in c), df_m.columns[0])
                col_nm = next((c for c in df_m.columns if "nama" in c or "mapel" in c), df_m.columns[1] if len(df_m.columns)>1 else df_m.columns[0])

                df_m_save = pd.DataFrame()
                df_m_save["kode_mapel"] = df_m[col_km].astype(str).str.strip().str.upper()
                df_m_save["nama_mapel"] = df_m[col_nm].astype(str).str.strip()
                df_m_save = df_m_save.drop_duplicates(subset=["kode_mapel"])

                conn.execute(text("TRUNCATE TABLE tb_master_mapel;"))
                df_m_save.to_sql("tb_master_mapel", conn, if_exists="append", index=False)

        return True, "Data master berhasil disimpan ke MySQL."
    except Exception as e:
        return False, f"Gagal simpan data master: {e}"


def load_master_data_from_db() -> dict:
    """Mengambil tabel master dari MySQL jika tidak diunggah oleh pengguna."""
    res = {}
    try:
        engine = get_db_connection()
        if engine is None:
            return res

        with engine.connect() as conn:
            try:
                df_sek = pd.read_sql_query("SELECT * FROM tb_master_sekolah", conn)
                if not df_sek.empty:
                    res["sekolah"] = df_sek
            except Exception:
                pass

            try:
                df_bio = pd.read_sql_query("SELECT * FROM tb_master_biodata", conn)
                if not df_bio.empty:
                    res["biodata"] = df_bio
            except Exception:
                pass

            try:
                df_k = pd.read_sql_query("SELECT * FROM tb_master_kunci", conn)
                if not df_k.empty:
                    res["kunci"] = df_k
            except Exception:
                pass

            try:
                df_m = pd.read_sql_query("SELECT * FROM tb_master_mapel", conn)
                if not df_m.empty:
                    res["mapel"] = df_m
            except Exception:
                pass
    except Exception:
        pass
    return res


def get_database_status() -> dict:
    """Mengembalikan ringkasan data yang tersimpan di MySQL."""
    status = {
        "connected": False,
        "n_peserta_skor": 0,
        "mapels_in_db": [],
        "n_master_sekolah": 0,
        "n_master_biodata": 0,
        "n_master_kunci": 0,
        "n_master_mapel": 0,
    }
    try:
        engine = get_db_connection()
        if engine is None:
            return status

        status["connected"] = True
        try:
            init_db_tables()
        except Exception:
            pass

        with engine.connect() as conn:
            try:
                r1 = conn.execute(text("SELECT COUNT(*), COUNT(DISTINCT mapel) FROM tb_peserta_skor;")).fetchone()
                status["n_peserta_skor"] = r1[0] or 0
                if status["n_peserta_skor"] > 0:
                    r_m = conn.execute(text("SELECT DISTINCT mapel FROM tb_peserta_skor;")).fetchall()
                    status["mapels_in_db"] = [str(row[0]).strip() for row in r_m if row[0]]
            except Exception:
                pass

            try:
                r2 = conn.execute(text("SELECT COUNT(*) FROM tb_master_sekolah;")).fetchone()
                status["n_master_sekolah"] = r2[0] or 0
            except Exception:
                pass

            try:
                r3 = conn.execute(text("SELECT COUNT(*) FROM tb_master_biodata;")).fetchone()
                status["n_master_biodata"] = r3[0] or 0
            except Exception:
                pass

            try:
                r4 = conn.execute(text("SELECT COUNT(*) FROM tb_master_kunci;")).fetchone()
                status["n_master_kunci"] = r4[0] or 0
            except Exception:
                pass

            try:
                r5 = conn.execute(text("SELECT COUNT(*) FROM tb_master_mapel;")).fetchone()
                status["n_master_mapel"] = r5[0] or 0
            except Exception:
                pass
    except Exception:
        pass
    return status


def update_irt_model_in_db(
    selected_model: str,
    df_persons: pd.DataFrame,
    df_params: pd.DataFrame,
    fit_stats: dict = None,
) -> tuple[bool, str]:
    """
    Memperbarui kolom skor IRT tertentu (misal skor_konversi_2pl) dan parameternya di DB
    tanpa menghapus tabel lain (seperti tb_sekolah_agregasi atau model IRT lainnya).
    """
    try:
        engine = get_db_connection()
        if engine is None:
            return False, "Tidak dapat terhubung ke MySQL Server."

        model_lower = selected_model.lower().strip()
        col_skor_target = f"skor_konversi_{model_lower}"

        # 1. Update skor peserta jika ada
        if df_persons is not None and not df_persons.empty:
            usr_col = next(
                (c for c in df_persons.columns if c.lower().strip() in ["username", "user_id", "id_peserta", "id"]),
                df_persons.columns[0]
            )
            val_col = next(
                (c for c in df_persons.columns if c.lower().strip() in ["nilai_scaled", "nilai konversi", "nilai_konversi", col_skor_target]),
                None
            )

            if val_col:
                # Buat tabel temporary untuk batch update yang cepat
                df_up = pd.DataFrame({
                    "username": df_persons[usr_col].astype(str).str.strip(),
                    col_skor_target: pd.to_numeric(df_persons[val_col], errors="coerce")
                }).dropna().drop_duplicates("username")

                with engine.begin() as conn:
                    conn.execute(text(f"""
                        CREATE TEMPORARY TABLE temp_irt_update (
                            username VARCHAR(100) PRIMARY KEY,
                            skor FLOAT
                        );
                    """))
                    df_up.to_sql("temp_irt_update", conn, if_exists="append", index=False)
                    conn.execute(text(f"""
                        UPDATE tb_peserta_skor p
                        JOIN temp_irt_update t ON p.username = t.username
                        SET p.{col_skor_target} = t.skor;
                    """))
                    conn.execute(text("DROP TEMPORARY TABLE IF EXISTS temp_irt_update;"))

        # 2. Update parameter soal jika ada
        if df_params is not None and not df_params.empty:
            item_col = df_params.columns[0]
            with engine.begin() as conn:
                for _, row in df_params.iterrows():
                    kode_soal = str(row[item_col]).strip()
                    updates = []
                    params = {"k": kode_soal}
                    if "b" in row and pd.notna(row["b"]):
                        col_b = f"b_{model_lower}"
                        updates.append(f"{col_b} = :b_val")
                        params["b_val"] = float(row["b"])
                    if "a" in row and pd.notna(row["a"]):
                        col_a = f"a_{model_lower}"
                        updates.append(f"{col_a} = :a_val")
                        params["a_val"] = float(row["a"])
                    if "c" in row and pd.notna(row["c"]):
                        col_c = f"c_{model_lower}"
                        updates.append(f"{col_c} = :c_val")
                        params["c_val"] = float(row["c"])

                    if updates:
                        sql = f"UPDATE tb_soal_parameter SET {', '.join(updates)} WHERE kode_soal = :k;"
                        conn.execute(text(sql), params)

        # 3. Update tb_model_summary
        if fit_stats:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO tb_model_summary (metode_model, reliabilitas, log_likelihood, aic, bic)
                        VALUES (:m, :rel, :ll, :aic, :bic)
                        ON DUPLICATE KEY UPDATE
                            reliabilitas = VALUES(reliabilitas),
                            log_likelihood = VALUES(log_likelihood),
                            aic = VALUES(aic),
                            bic = VALUES(bic);
                    """),
                    {
                        "m": selected_model.upper(),
                        "rel": fit_stats.get("reliability"),
                        "ll": fit_stats.get("log_likelihood"),
                        "aic": fit_stats.get("aic"),
                        "bic": fit_stats.get("bic"),
                    }
                )

        return True, f"Model {selected_model} berhasil diperbarui di database."
    except Exception as e:
        return False, str(e)