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
    """Mempersiapkan struktur tabel MySQL jika belum ada."""
    engine = get_db_connection()
    if engine is None:
        return False

    try:
        with engine.begin() as conn:
            # 1. Tabel Peserta & Skor (Primary Key: username)
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tb_peserta_skor (
                    username VARCHAR(100) PRIMARY KEY,
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
                    INDEX idx_sekolah (kode_sekolah),
                    INDEX idx_provinsi (kode_provinsi)
                );
            """
                )
            )

            # 2. Tabel Parameter Soal
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tb_soal_parameter (
                    kode_soal VARCHAR(100) PRIMARY KEY,
                    tingkat_kesukaran_ctt FLOAT,
                    daya_beda_ctt FLOAT,
                    rekomendasi VARCHAR(100),
                    b_rasch FLOAT,
                    b_1pl FLOAT,
                    a_2pl FLOAT,
                    b_2pl FLOAT,
                    a_3pl FLOAT,
                    b_3pl FLOAT,
                    c_3pl FLOAT
                );
            """
                )
            )

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
                "username", "nama_sekolah", "kode_sekolah", "nama_kabupaten",
                "nama_provinsi", "kode_provinsi", "skor_mentah", "skor_konversi_ctt",
                "skor_konversi_rasch", "skor_konversi_1pl", "skor_konversi_2pl",
                "skor_konversi_3pl", "Jumlah_Soal"
            ]
            for col in valid_cols:
                if col not in df_peserta_clean.columns:
                    df_peserta_clean[col] = None
            df_peserta_clean = df_peserta_clean[valid_cols]

        if df_soal_clean is not None and not df_soal_clean.empty:
            valid_soal_cols = [
                "kode_soal", "tingkat_kesukaran_ctt", "daya_beda_ctt", "rekomendasi",
                "b_rasch", "b_1pl", "a_2pl", "b_2pl", "a_3pl", "b_3pl", "c_3pl"
            ]
            for col in valid_soal_cols:
                if col not in df_soal_clean.columns:
                    df_soal_clean[col] = None
            df_soal_clean = df_soal_clean[valid_soal_cols]

        with engine.begin() as conn:
            # 1. Peserta & Skor
            if df_peserta_clean is not None and not df_peserta_clean.empty:
                conn.execute(text("TRUNCATE TABLE tb_peserta_skor;"))
                df_peserta_clean.to_sql(
                    "tb_peserta_skor", conn, if_exists="append", index=False, chunksize=5000
                )

            # 2. Parameter Soal
            if df_soal_clean is not None and not df_soal_clean.empty:
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

            # 4. Agregasi Sekolah (HANYA DITIMPA JIKA DATANYA ADA)
            if df_sekolah_clean is not None and not df_sekolah_clean.empty:
                conn.execute(text("TRUNCATE TABLE tb_sekolah_agregasi;"))
                df_sekolah_clean.to_sql(
                    "tb_sekolah_agregasi", conn, if_exists="append", index=False
                )

        return True, "Berhasil menyimpan seluruh data ke MySQL Server."
    except Exception as e:
        return False, f"Kendala penyimpanan DB: {e}"


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