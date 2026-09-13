import numpy as np
import pandas as pd


def process_scoring(df_respon, df_kunci):
    """Memproses jawaban peserta menjadi matriks skor (0 / 1).

    Mendukung format data:
    1. Long (Baris per peserta-soal)
    2. List/Array String (Kolom 'list_soal' dan 'respon' dipisah koma)
    3. Wide (Setiap kolom adalah kode soal)
    """
    # 1. Normalisasi nama kolom menjadi huruf kecil & tanpa spasi
    df_respon.columns = df_respon.columns.astype(str).str.strip().str.lower()
    df_kunci.columns = df_kunci.columns.astype(str).str.strip().str.lower()

    # Deteksi kolom ID Peserta
    id_col_respon = None
    for col in ["username", "id_peserta", "id", "nisn", "no_peserta", "nama"]:
        if col in df_respon.columns:
            id_col_respon = col
            break
    if not id_col_respon:
        id_col_respon = df_respon.columns[0]

    # Deteksi kolom Kode Soal & Kunci Jawaban
    soal_col_kunci = None
    kunci_col_kunci = None
    for col in ["kode_soal", "id_soal", "soal", "no_soal"]:
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

    # Dictionary Kunci Jawaban
    kunci_dict = dict(
        zip(
            df_kunci[soal_col_kunci].astype(str).str.strip(),
            df_kunci[kunci_col_kunci].astype(str).str.strip().str.upper(),
        )
    )

    # 2. Kasus A: Format List String ('list_soal' & 'respon' dipisah koma) - SAFE & OPTIMIZED
    if "list_soal" in df_respon.columns and "respon" in df_respon.columns:
        item_cols = sorted(list(kunci_dict.keys()))
        item_to_idx = {item: i for i, item in enumerate(item_cols)}

        n_rows = len(df_respon)
        n_items = len(item_cols)

        # Pre-allocate matriks hemat memori (1 byte / sel)
        score_matrix = np.zeros((n_rows, n_items), dtype=np.uint8)
        jumlah_soal_list = np.zeros(n_rows, dtype=np.uint16)

        # Ambil raw values dari Pandas Series
        raw_list_soal = df_respon["list_soal"].values
        raw_respon = df_respon["respon"].values

        for idx in range(n_rows):
            val_soal = raw_list_soal[idx]
            val_resp = raw_respon[idx]

            # Penanganan aman jika data kosong/NaN/float
            str_soal = "" if pd.isna(val_soal) else str(val_soal).strip()
            str_resp = "" if pd.isna(val_resp) else str(val_resp).strip()

            soal_list = [s.strip() for s in str_soal.split(",") if s.strip()]
            respon_list = [r.strip().upper() for r in str_resp.split(",") if r.strip()]

            jumlah_soal_list[idx] = len(soal_list)

            for s_code, resp in zip(soal_list, respon_list):
                if s_code in item_to_idx:
                    kunci = kunci_dict.get(s_code)
                    if kunci is not None and resp == kunci:
                        score_matrix[idx, item_to_idx[s_code]] = 1

        df_matrix = pd.DataFrame(score_matrix, columns=item_cols, dtype=np.uint8)
        df_matrix.insert(0, id_col_respon, df_respon[id_col_respon].values)
        df_matrix["Jumlah_Soal"] = jumlah_soal_list

    # 3. Kasus B: Format 'Long' (Baris = Respon per Peserta-Soal)
    elif "kode_soal" in df_respon.columns and "jawaban" in df_respon.columns:
        df_respon["kode_soal_clean"] = df_respon["kode_soal"].astype(str).str.strip()
        df_respon["jawaban_clean"] = (
            df_respon["jawaban"].astype(str).str.strip().str.upper()
        )
        df_respon["kunci_true"] = df_respon["kode_soal_clean"].map(kunci_dict)

        df_respon["skor"] = np.where(
            (df_respon["jawaban_clean"] == df_respon["kunci_true"])
            & (df_respon["jawaban_clean"] != ""),
            1,
            0,
        ).astype(np.uint8)

        jml_soal_per_user = df_respon.groupby(id_col_respon)[
            "kode_soal_clean"
        ].nunique()

        df_matrix = (
            df_respon.pivot(
                index=id_col_respon, columns="kode_soal_clean", values="skor"
            )
            .fillna(0)
            .astype(np.uint8)
            .reset_index()
        )

        df_matrix["Jumlah_Soal"] = (
            df_matrix[id_col_respon].map(jml_soal_per_user).fillna(0).astype(int)
        )

    # 4. Kasus C: Format 'Wide' (Kolom berupa kode soal)
    else:
        df_matrix = pd.DataFrame()
        df_matrix[id_col_respon] = df_respon[id_col_respon]

        soal_cols = []
        for col in df_respon.columns:
            if col == id_col_respon:
                continue

            col_clean = str(col).strip()
            if col_clean in kunci_dict:
                soal_cols.append(col_clean)
                kunci_val = kunci_dict[col_clean]
                resp_val = df_respon[col].astype(str).str.strip().str.upper()
                df_matrix[col_clean] = np.where(resp_val == kunci_val, 1, 0).astype(
                    np.uint8
                )

        df_matrix["Jumlah_Soal"] = len(soal_cols)

    # 5. Mencegah duplikat nama kolom
    df_matrix = df_matrix.loc[:, ~df_matrix.columns.duplicated()].copy()

    # 6. Hitung Skor Mentah (Total Benar)
    non_item = [
        id_col_respon,
        "username",
        "skor_mentah",
        "nilai_konversi",
        "jumlah_soal",
    ]
    item_cols = [c for c in df_matrix.columns if c.lower() not in non_item]

    df_matrix["Skor_Mentah"] = df_matrix[item_cols].sum(axis=1).astype(np.uint16)

    # 7. Hitung Nilai Konversi = (Skor Benar / Jumlah Soal Peserta) * 100
    df_matrix["Nilai_Konversi"] = np.where(
        df_matrix["Jumlah_Soal"] > 0,
        (df_matrix["Skor_Mentah"] / df_matrix["Jumlah_Soal"]) * 100,
        0.0,
    ).round(2)

    return df_matrix


def calculate_person_fit(df_matrix, df_params, b_col="b"):
    """Menghitung indeks fit peserta (Outfit MSQ) secara hemat memori."""
    id_col = df_matrix.columns[0]
    non_item = [
        id_col,
        "username",
        "skor_mentah",
        "skormentah",
        "jumlah_soal",
        "nilai_konversi",
    ]
    item_cols = [c for c in df_matrix.columns if c.lower() not in non_item]

    item_map = dict(zip(df_params[df_params.columns[0]].astype(str), df_params[b_col]))
    b_vec = np.array([item_map.get(str(c), 0.0) for c in item_cols])

    X = df_matrix[item_cols].to_numpy(dtype=np.float32)

    total_scores = X.sum(axis=1)
    p_scores = np.clip(total_scores / len(item_cols), 0.01, 0.99)
    theta_vec = np.log(p_scores / (1 - p_scores))

    theta_mat = theta_vec[:, np.newaxis]
    P = 1.0 / (1.0 + np.exp(-(theta_mat - b_vec)))
    P = np.clip(P, 1e-4, 0.9999)

    W = P * (1.0 - P)
    Z_sq = ((X - P) ** 2) / W
    outfit_msq = Z_sq.mean(axis=1)

    status = np.where(
        (outfit_msq >= 0.5) & (outfit_msq <= 1.5),
        "Pola Normal",
        np.where(outfit_msq > 1.5, "Menebak / Anomali", "Terlalu Menentu"),
    )

    df_res = pd.DataFrame({
        id_col: df_matrix[id_col],
        "Outfit_MSQ": np.round(outfit_msq, 2),
        "Status_Pola_Jawab": status,
    })

    return df_res.loc[:, ~df_res.columns.duplicated()].copy()