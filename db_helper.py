# db_helper.py
import os
import urllib.parse
import pandas as pd
from sqlalchemy import create_engine, text

# Konfigurasi Koneksi MySQL
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "db_psikometri")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")


def get_db_connection():
    """Membuat SQLAlchemy Engine untuk MySQL."""
    try:
        encoded_password = urllib.parse.quote_plus(MYSQL_PASSWORD)
        connection_string = (
            f"mysql+pymysql://{MYSQL_USER}:{encoded_password}"
            f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
        )
        engine = create_engine(connection_string, pool_recycle=3600)
        return engine
    except Exception as e:
        print(f"Gagal koneksi ke database: {e}")
        return None


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
                    Jumlah_Soal INT
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

            alter_commands = [
                ("tb_peserta_skor", "skor_konversi_1pl", "DECIMAL(10,2)"),
                ("tb_peserta_skor", "Jumlah_Soal", "INT"),
                ("tb_soal_parameter", "b_1pl", "FLOAT"),
                ("tb_soal_parameter", "rekomendasi", "VARCHAR(100)"),
                ("tb_sekolah_agregasi", "rata_skor_1pl", "DECIMAL(10,2)"),
            ]

            for table, column, col_type in alter_commands:
                check_query = text(
                    f"SHOW COLUMNS FROM {table} LIKE '{column}';"
                )
                res = conn.execute(check_query).fetchone()
                if not res:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type};")
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
    df_peserta: pd.DataFrame,
    df_soal: pd.DataFrame,
    df_summary: pd.DataFrame,
    df_sekolah: pd.DataFrame,
) -> tuple[bool, str]:
    """Menghapus tabel lama, membuat ulang tabel, membersihkan duplikasi, dan menyimpan hasil analisis baru ke MySQL Server."""
    try:
        engine = get_db_connection()
        if engine is None:
            return False, "Tidak dapat terhubung ke MySQL Server."

        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS tb_peserta_skor;"))
            conn.execute(text("DROP TABLE IF EXISTS tb_soal_parameter;"))
            conn.execute(text("DROP TABLE IF EXISTS tb_model_summary;"))
            conn.execute(text("DROP TABLE IF EXISTS tb_sekolah_agregasi;"))

        if not init_db_tables():
            return False, "Gagal membuat/menyiapkan tabel database."

        df_peserta_clean = _clean_dataframe(df_peserta, "username")
        df_soal_clean = _clean_dataframe(df_soal, "kode_soal")
        df_summary_clean = _clean_dataframe(df_summary, "metode_model")
        df_sekolah_clean = _clean_dataframe(df_sekolah, "kode_sekolah")

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
            if df_peserta_clean is not None and not df_peserta_clean.empty:
                df_peserta_clean.to_sql(
                    "tb_peserta_skor", conn, if_exists="append", index=False
                )

            if df_soal_clean is not None and not df_soal_clean.empty:
                df_soal_clean.to_sql(
                    "tb_soal_parameter", conn, if_exists="append", index=False
                )

            if df_summary_clean is not None and not df_summary_clean.empty:
                df_summary_clean.to_sql(
                    "tb_model_summary", conn, if_exists="append", index=False
                )

            if df_sekolah_clean is not None and not df_sekolah_clean.empty:
                df_sekolah_clean.to_sql(
                    "tb_sekolah_agregasi", conn, if_exists="append", index=False
                )

        return True, "Berhasil menyimpan ke MySQL Server."
    except Exception as e:
        return False, str(e)