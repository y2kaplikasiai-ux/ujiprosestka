# scoring.py
import numpy as np
import pandas as pd
import pymysql
from sqlalchemy import create_engine, text

# Konfigurasi Server MySQL Lokal
DB_HOST = "localhost"
DB_USER = "root"
DB_PASS = ""
DB_NAME = "db_psikometri"
DB_PORT = 3306

DB_URL = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def reset_and_create_tables():
    """
    Menghapus tabel lama jika ada (DROP), lalu membuat tabel baru dengan Primary Key `username`.
    """
    conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, port=DB_PORT)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`;")
        conn.commit()
    finally:
        conn.close()

    engine = create_engine(DB_URL)

    drop_query = "DROP TABLE IF EXISTS tb_peserta_skor;"
    create_query = """
    CREATE TABLE tb_peserta_skor (
        username VARCHAR(100) PRIMARY KEY,
        kode_sekolah VARCHAR(50),
        nama_sekolah VARCHAR(255),
        nama_kabupaten VARCHAR(100),
        kode_provinsi VARCHAR(10),
        nama_provinsi VARCHAR(100),
        skor_mentah FLOAT NULL,
        skor_konversi_ctt FLOAT NULL,
        skor_konversi_rasch FLOAT NULL,
        skor_konversi_1pl FLOAT NULL,
        skor_konversi_2pl FLOAT NULL,
        skor_konversi_3pl FLOAT NULL,
        Jumlah_Soal INT NULL,
        INDEX idx_sekolah (kode_sekolah),
        INDEX idx_provinsi (kode_provinsi)
    );
    """

    with engine.connect() as connection:
        connection.execute(text(drop_query))
        connection.execute(text(create_query))
        connection.commit()

    return engine


def scale_theta_custom(theta_series, min_target=200.0, max_target=800.0, mean_target=500.0, sd_target=100.0):
    """
    Mengonversi nilai Theta IRT ke skala kustom (Default UTBK: Mean=500, SD=100, Range 200-800).
    """
    if theta_series is None or theta_series.empty:
        return pd.Series(dtype=float)

    theta_clean = pd.to_numeric(theta_series, errors="coerce")
    scaled = np.clip(mean_target + (sd_target * theta_clean), min_target, max_target)
    return scaled.round(2)


def pipeline_proses_dan_simpan_mysql(df_matrix_school, irt_dict, scale_params=None):
    """
    Menggabungkan seluruh hasil kalkulasi (CTT & IRT) untuk SEMUA peserta,
    mereset tabel di database, dan menyimpan data terstruktur menggunakan `username`.
    """
    if df_matrix_school is None or df_matrix_school.empty:
        return

    if scale_params is None:
        scale_params = {"min": 200.0, "max": 800.0, "mean": 500.0, "sd": 100.0}

    engine = reset_and_create_tables()

    # Deteksi Kolom Username
    usr_col = df_matrix_school.columns[0]
    for c in ["username", "Username", "user_id", "ID", "nisn", "no_peserta"]:
        if c in df_matrix_school.columns:
            usr_col = c
            break

    df_final = pd.DataFrame()
    df_final["username"] = df_matrix_school[usr_col].astype(str).str.strip()

    # Ekstraksi atribut sekolah & wilayah
    df_final["kode_sekolah"] = (
        df_matrix_school["_school_key"]
        if "_school_key" in df_matrix_school.columns
        else (
            df_matrix_school["kode_sekolah"]
            if "kode_sekolah" in df_matrix_school.columns
            else df_final["username"].str[:9]
        )
    )
    df_final["nama_sekolah"] = (
        df_matrix_school["nama_sekolah"]
        if "nama_sekolah" in df_matrix_school.columns
        else df_final["kode_sekolah"]
    )
    df_final["nama_kabupaten"] = (
        df_matrix_school["nama_kabupaten"]
        if "nama_kabupaten" in df_matrix_school.columns
        else "-"
    )
    df_final["kode_provinsi"] = (
        df_matrix_school["kd_prop"]
        if "kd_prop" in df_matrix_school.columns
        else (
            df_matrix_school["kode_provinsi"]
            if "kode_provinsi" in df_matrix_school.columns
            else df_final["username"].str[1:3]
        )
    )
    df_final["nama_provinsi"] = (
        df_matrix_school["nama_provinsi"]
        if "nama_provinsi" in df_matrix_school.columns
        else df_final["kode_provinsi"]
    )

    # 1. Skor Mentah & Jumlah Soal
    df_final["skor_mentah"] = (
        pd.to_numeric(df_matrix_school["skor_mentah"], errors="coerce").fillna(0)
        if "skor_mentah" in df_matrix_school.columns
        else 0.0
    )
    df_final["Jumlah_Soal"] = (
        pd.to_numeric(df_matrix_school["Jumlah_Soal"], errors="coerce").fillna(1)
        if "Jumlah_Soal" in df_matrix_school.columns
        else 1
    )

    # 2. Skor CTT KLASIK
    df_final["skor_konversi_ctt"] = np.where(
        df_final["Jumlah_Soal"] > 0,
        (df_final["skor_mentah"] / df_final["Jumlah_Soal"]) * 100.0,
        0.0
    ).round(2)

    # 3. Skor IRT SEMUA Peserta (Rasch, 1PL, 2PL, 3PL)
    min_val = scale_params.get("min", 200.0)
    max_val = scale_params.get("max", 800.0)
    mean_val = scale_params.get("mean", 500.0)
    sd_val = scale_params.get("sd", 100.0)

    for model_key in ["rasch", "1pl", "2pl", "3pl"]:
        col_db_name = f"skor_konversi_{model_key}"
        irt_data = irt_dict.get(model_key) if irt_dict else None

        if irt_data and isinstance(irt_data, dict):
            # Ambil DataFrame Person dari key yang tersedia
            df_person = irt_data.get("person_params")
            if df_person is None or df_person.empty:
                df_person = irt_data.get("df_person")

            if df_person is not None and not df_person.empty:
                # Cari kolom ID yang tepat
                u_col_irt = None
                for candidate in ["username", "ID Peserta", "Username", "user_id", "ID"]:
                    if candidate in df_person.columns:
                        u_col_irt = candidate
                        break
                if not u_col_irt:
                    u_col_irt = df_person.columns[0]

                # Ambil atau Hitung Skor Scaled
                score_series = None
                if "Nilai_Scaled" in df_person.columns:
                    score_series = pd.to_numeric(df_person["Nilai_Scaled"], errors="coerce")
                else:
                    theta_col = None
                    for c in df_person.columns:
                        c_clean = str(c).lower()
                        if any(k in c_clean for k in ["theta", "kemampuan"]):
                            theta_col = c
                            break
                    if theta_col:
                        score_series = scale_theta_custom(
                            df_person[theta_col],
                            min_target=min_val,
                            max_target=max_val,
                            mean_target=mean_val,
                            sd_target=sd_val
                        )

                if score_series is not None:
                    # Mapping berdasarkan Username (dikast ke string & di-strip)
                    keys = df_person[u_col_irt].astype(str).str.strip().values
                    vals = score_series.values
                    map_score = dict(zip(keys, vals))

                    df_final[col_db_name] = df_final["username"].map(map_score)
                else:
                    df_final[col_db_name] = np.nan
            else:
                df_final[col_db_name] = np.nan
        else:
            df_final[col_db_name] = np.nan

    # Bersihkan duplikat Username
    df_final = df_final.drop_duplicates(subset=["username"]).copy()

    # Simpan ke tabel MySQL
    df_final.to_sql(
        name="tb_peserta_skor",
        con=engine,
        if_exists="append",
        index=False,
        chunksize=10000,
    )


def extract_active_soal_from_respon(df_respon):
    if "list_soal" not in df_respon.columns:
        return None

    active_soal = set()
    for raw_list in df_respon["list_soal"].dropna():
        items = [s.strip() for s in str(raw_list).split(",") if s.strip()]
        active_soal.update(items)

    return list(active_soal)


def process_scoring(df_respon, df_kunci):
    df_respon = df_respon.copy()
    df_kunci = df_kunci.copy()

    df_respon.columns = df_respon.columns.astype(str).str.strip().str.lower()
    df_kunci.columns = df_kunci.columns.astype(str).str.strip().str.lower()

    id_col_respon = None
    for col in ["username", "id", "nisn", "no_peserta", "user_id", "nama"]:
        if col in df_respon.columns:
            id_col_respon = col
            break
    if not id_col_respon:
        id_col_respon = df_respon.columns[0]

    kode_paket_col = None
    for col in ["kode_paket", "kd_paket", "paket"]:
        if col in df_respon.columns:
            kode_paket_col = col
            break

    soal_col_kunci = None
    kunci_col_kunci = None
    for col in ["kode_soal", "id_soal", "soal", "no_soal", "kd_soal"]:
        if col in df_kunci.columns:
            soal_col_kunci = col
            break
    for col in ["kunci", "kunci_jawaban", "jawaban", "key"]:
        if col in df_kunci.columns:
            kunci_col_kunci = col
            break

    if not soal_col_kunci:
        soal_col_kunci = df_kunci.columns[0]
    if not kunci_col_kunci:
        kunci_col_kunci = (
            df_kunci.columns[1] if len(df_kunci.columns) > 1 else df_kunci.columns[0]
        )

    kunci_dict = dict(
        zip(
            df_kunci[soal_col_kunci].astype(str).str.strip(),
            df_kunci[kunci_col_kunci].astype(str).str.strip().str.upper(),
        )
    )

    if "list_soal" in df_respon.columns and "respon" in df_respon.columns:
        used_items = sorted(list(kunci_dict.keys()))
        item_to_idx = {item: i for i, item in enumerate(used_items)}

        n_rows = len(df_respon)
        n_items = len(used_items)

        score_matrix = np.full((n_rows, n_items), np.nan, dtype=np.float32)
        jumlah_soal_list = np.zeros(n_rows, dtype=np.uint16)

        raw_list_soal = df_respon["list_soal"].values
        raw_respon = df_respon["respon"].values

        for idx in range(n_rows):
            val_soal = raw_list_soal[idx]
            val_resp = raw_respon[idx]

            str_soal = "" if pd.isna(val_soal) else str(val_soal).strip()
            str_resp = "" if pd.isna(val_resp) else str(val_resp).strip()

            soal_list = [s.strip() for s in str_soal.split(",") if s.strip()]
            respon_list = [r.strip().upper() for r in str_resp.split(",")]

            jumlah_soal_list[idx] = len(soal_list)

            for pos, s_code in enumerate(soal_list):
                if s_code in item_to_idx:
                    resp = respon_list[pos] if pos < len(respon_list) else ""
                    kunci = kunci_dict.get(s_code)

                    if kunci is not None:
                        score_matrix[idx, item_to_idx[s_code]] = (
                            1.0 if (resp != "" and resp == kunci) else 0.0
                        )

        df_matrix = pd.DataFrame(score_matrix, columns=used_items)
        df_matrix.insert(0, "username", df_respon[id_col_respon].values)
        if kode_paket_col:
            df_matrix.insert(1, "kode_paket", df_respon[kode_paket_col].values)
        df_matrix["Jumlah_Soal"] = jumlah_soal_list

    elif "kode_soal" in df_respon.columns and "jawaban" in df_respon.columns:
        df_respon["kode_soal_clean"] = df_respon["kode_soal"].astype(str).str.strip()
        df_respon["jawaban_clean"] = (
            df_respon["jawaban"].astype(str).str.strip().str.upper()
        )
        df_respon["kunci_true"] = df_respon["kode_soal_clean"].map(kunci_dict)

        df_respon["skor"] = np.where(
            df_respon["jawaban_clean"] == df_respon["kunci_true"],
            1.0,
            0.0,
        )

        jml_soal_per_user = df_respon.groupby(id_col_respon)[
            "kode_soal_clean"
        ].nunique()

        df_matrix = (
            df_respon.pivot(
                index=id_col_respon, columns="kode_soal_clean", values="skor"
            ).reset_index()
        )

        if id_col_respon != "username":
            df_matrix.rename(columns={id_col_respon: "username"}, inplace=True)
            id_col_respon = "username"

        if kode_paket_col:
            paket_map = df_respon.groupby(id_col_respon)[kode_paket_col].first()
            df_matrix.insert(1, "kode_paket", df_matrix["username"].map(paket_map))

        df_matrix["Jumlah_Soal"] = (
            df_matrix["username"].map(jml_soal_per_user).fillna(0).astype(int)
        )

    else:
        df_matrix = pd.DataFrame()
        df_matrix["username"] = df_respon[id_col_respon]

        if kode_paket_col:
            df_matrix["kode_paket"] = df_respon[kode_paket_col]

        soal_cols = []
        for col in df_respon.columns:
            if col in [id_col_respon, kode_paket_col]:
                continue

            col_clean = str(col).strip()
            if col_clean in kunci_dict:
                soal_cols.append(col_clean)
                kunci_val = kunci_dict[col_clean]
                resp_val = df_respon[col].astype(str).str.strip().str.upper()

                df_matrix[col_clean] = np.where(
                    df_respon[col].isna(),
                    np.nan,
                    np.where(resp_val == kunci_val, 1.0, 0.0),
                )

        df_matrix["Jumlah_Soal"] = df_matrix[soal_cols].notna().sum(axis=1)

    df_matrix = df_matrix.loc[:, ~df_matrix.columns.duplicated()].copy()

    non_item = [
        "username",
        "kode_paket",
        "skor_mentah",
        "nilai_konversi",
        "jumlah_soal",
    ]
    item_cols = [c for c in df_matrix.columns if c.lower() not in non_item]

    df_matrix["skor_mentah"] = df_matrix[item_cols].sum(axis=1, skipna=True).astype(int)

    df_matrix["Nilai_Konversi"] = np.where(
        df_matrix["Jumlah_Soal"] > 0,
        (df_matrix["skor_mentah"] / df_matrix["Jumlah_Soal"]) * 100.0,
        0.0,
    ).round(2)

    return df_matrix


def calculate_person_fit(df_matrix, df_params, b_col="b"):
    empty_res = pd.DataFrame(columns=["username", "Outfit_MSQ", "Status_Pola_Jawab"])

    if df_matrix is None or df_matrix.empty or df_params is None or df_params.empty:
        return empty_res

    usr_col = "username" if "username" in df_matrix.columns else df_matrix.columns[0]

    non_item_cols = [
        "username",
        "user_id",
        "nama",
        "tahun",
        "kode_paket",
        "nama_sekolah",
        "kode_sekolah",
        "nama_kabupaten",
        "nama_provinsi",
        "kode_provinsi",
        "nama_sekolah_master",
        "nama_kabupaten_master",
        "kd_prop_master",
        "nama_provinsi_master",
        "skor_mentah",
        "skormentah",
        "nilai_konversi",
        "Nilai_Konversi",
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
    ]

    item_cols = [
        c
        for c in df_matrix.columns
        if c.lower() not in [x.lower() for x in non_item_cols]
    ]

    if not item_cols:
        return empty_res

    item_map = dict(zip(df_params[df_params.columns[0]].astype(str), df_params[b_col]))
    b_vec = np.array([item_map.get(str(c), 0.0) for c in item_cols])

    df_items = df_matrix[item_cols].apply(pd.to_numeric, errors="coerce")
    X = df_items.to_numpy(dtype=np.float32)

    total_scores = np.nansum(X, axis=1)
    n_items_valid = np.sum(~np.isnan(X), axis=1)
    n_items_valid = np.where(n_items_valid == 0, 1, n_items_valid)

    p_scores = np.clip(total_scores / n_items_valid, 0.01, 0.99)
    theta_vec = np.log(p_scores / (1.0 - p_scores))

    theta_mat = theta_vec[:, np.newaxis]
    P = 1.0 / (1.0 + np.exp(-(theta_mat - b_vec)))
    P = np.clip(P, 1e-4, 0.9999)

    W = P * (1.0 - P)
    Z_sq = np.nan_to_num(((X - P) ** 2) / W, nan=0.0)

    valid_mask = ~np.isnan(X)
    outfit_msq = np.sum(Z_sq * valid_mask, axis=1) / n_items_valid

    status = np.where(
        (outfit_msq >= 0.5) & (outfit_msq <= 1.5),
        "Pola Normal",
        np.where(outfit_msq > 1.5, "Menebak / Anomali", "Terlalu Menentu"),
    )

    df_res = pd.DataFrame(
        {
            "username": df_matrix[usr_col],
            "Outfit_MSQ": np.round(outfit_msq, 2),
            "Status_Pola_Jawab": status,
        }
    )

    return df_res.loc[:, ~df_res.columns.duplicated()].copy()