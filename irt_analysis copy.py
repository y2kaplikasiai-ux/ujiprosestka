# irt_analysis.py
import numpy as np
import pandas as pd
from scipy.stats import norm


def _sigmoid(x):
    """Fungsi aktivasi numerik aman dari overflow/underflow."""
    return 1.0 / (1.0 + np.exp(-np.clip(x, -15, 15)))


def get_item_columns(df):
    """Mengekstrak HANYA kolom kode soal untuk analisis IRT."""
    non_item_keywords = [
        "username",
        "user_id",
        "tahun",
        "kode_jenjang",
        "kode_mapel",
        "kode_paket",
        "list_soal",
        "respon",
        "skor_mentah",
        "nilai_konversi",
        "nilai_scaled",
        "no",
        "no.",
        "id",
        "id_peserta",
        "nama",
        "sekolah",
        "npsn",
        "kelas",
        "unnamed",
        "jumlah_soal_dikerjakan",
        "jumlah_soal",
        "_school_key",
        "_prop_key_user",
        "kd_prop",
        "nama_sekolah",
        "nama_kabupaten",
        "nama_provinsi",
    ]

    item_cols = [
        col
        for col in df.columns
        if not any(kw in str(col).strip().lower() for kw in non_item_keywords)
    ]
    return item_cols


def run_irt_analysis(
    df_matrix,
    model_type="1PL",
    min_scale=200.0,
    max_scale=800.0,
    mean_scale=500.0,
    sd_scale=100.0,
    seed=42,
):
    """
    Menjalankan estimasi IRT cepat berbasis Vektorisasi NumPy (Rasch, 1PL, 2PL, 3PL)
    dengan Deterministic Seed agar hasil selalu 100% konsisten pada setiap pengujian.
    """
    # Kunci Random Seed NumPy untuk Menjamin Konsistensi Desimal di Setiap Eksekusi
    if seed is not None:
        np.random.seed(seed)

    df = df_matrix.copy()

    # 1. Dapatkan kolom item murni
    item_cols = get_item_columns(df)

    # 2. Ambil ID Peserta & paksa ke Tipe String yang Bersih
    usr_col = None
    for candidate in ["username", "Username", "id_peserta", "id", "user_id"]:
        if candidate in df.columns:
            usr_col = candidate
            break

    if usr_col:
        user_ids = df[usr_col].astype(str).str.strip()
    else:
        user_ids = df.index.astype(str)

    # 3. Konversi matriks respon ke numerik float
    X_df = df[item_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
    X = X_df.to_numpy(dtype=float)
    n_persons, n_items = X.shape

    if n_items == 0 or n_persons == 0:
        raise ValueError("Data tidak memiliki butir soal atau peserta yang valid.")

    # 4. Hitung Proporsi Benar Item (p_i) & Skor Mentah Peserta
    p_i = np.clip(np.nanmean(X, axis=0), 0.005, 0.995)
    skor_mentah = np.nansum(X, axis=1)

    # Estimasi Parameter Kesukaran (b)
    b_params = np.log((1.0 - p_i) / p_i)
    c_params = np.zeros(n_items)

    # --- LOGIKA BERDASARKAN MODEL_TYPE ---
    m_type_str = str(model_type).upper()

    # Perhitungan Daya Beda (a) Berbasis Korelasi Point-Biserial & Biserial Murni
    def calculate_discrimination_params(X_mat, total_scores, p_vector):
        a_results = []
        for j in range(n_items):
            item_resp = X_mat[:, j]
            rest_score = total_scores - item_resp  # Rest-score tanpa bias item j
            
            p = p_vector[j]
            q = 1.0 - p
            
            std_rest = np.std(rest_score)
            std_item = np.std(item_resp)
            
            if std_rest == 0 or std_item == 0:
                a_results.append(1.0)
                continue
                
            # Korelasi Point-Biserial (r_pbis) antara item dan rest-score
            r_pbis = np.corrcoef(item_resp, rest_score)[0, 1]
            if np.isnan(r_pbis):
                r_pbis = 0.0
                
            # Konversi ke Korelasi Biserial (r_bis) menggunakan ordinat kurva normal
            z_p = norm.ppf(1.0 - p)
            y_p = norm.pdf(z_p)  # Ordinat Gauss
            
            r_bis = (r_pbis * np.sqrt(p * q)) / max(y_p, 1e-5)
            r_bis = np.clip(r_bis, -0.95, 0.95)
            
            # Konversi r_bis ke parameter daya beda IRT (a)
            a_val = (1.7 * r_bis) / np.sqrt(max(1.0 - (r_bis ** 2), 0.05))
            a_results.append(a_val)
            
        return np.clip(np.nan_to_num(a_results, nan=1.0), 0.2, 2.5)

    if m_type_str == "RASCH":
        a_params = np.ones(n_items)
        p_person = np.clip(skor_mentah / max(n_items, 1), 0.005, 0.995)
        theta = np.log(p_person / (1.0 - p_person))
        num_params = n_items + n_persons

    elif m_type_str == "1PL":
        a_raw = calculate_discrimination_params(X, skor_mentah, p_i)
        a_common = float(np.clip(np.mean(a_raw), 0.2, 2.5))

        a_params = np.full(n_items, a_common)
        p_person = np.clip(skor_mentah / max(n_items, 1), 0.005, 0.995)
        theta = np.log(p_person / (1.0 - p_person)) / a_common
        num_params = n_items + 1 + n_persons

    elif m_type_str == "3PL":
        a_params = calculate_discrimination_params(X, skor_mentah, p_i)

        bottom_idx = np.argsort(skor_mentah)[: max(1, int(n_persons * 0.10))]
        c_params = np.clip(np.mean(X[bottom_idx, :], axis=0), 0.0, 0.25)

        weighted_scores = np.dot(X, a_params)
        max_weighted = np.sum(a_params)
        p_person_weighted = np.clip(
            weighted_scores / max(max_weighted, 1.0), 0.005, 0.995
        )
        theta = np.log(p_person_weighted / (1.0 - p_person_weighted))
        num_params = (3 * n_items) + n_persons

    else:  # Default '2PL'
        a_params = calculate_discrimination_params(X, skor_mentah, p_i)

        weighted_scores = np.dot(X, a_params)
        max_weighted = np.sum(a_params)
        p_person_weighted = np.clip(
            weighted_scores / max(max_weighted, 1.0), 0.005, 0.995
        )
        theta = np.log(p_person_weighted / (1.0 - p_person_weighted))
        num_params = (2 * n_items) + n_persons

    # Kategori b
    kat_conditions = [b_params > 1.0, b_params < -1.0]
    kat_choices = ["Sukar", "Mudah"]
    kategori_b = np.select(kat_conditions, kat_choices, default="Sedang")

    # Probabilitas & Standard Error of Measurement (SEM) per Peserta
    logits = a_params[None, :] * (theta[:, None] - b_params[None, :])
    P_val = c_params[None, :] + (1.0 - c_params[None, :]) * _sigmoid(logits)
    P_val_clipped = np.clip(P_val, 1e-7, 1.0 - 1e-7)

    info_per_person = np.sum((a_params[None, :] ** 2) * P_val * (1.0 - P_val), axis=1)
    sem_list = np.where(info_per_person > 0, 1.0 / np.sqrt(info_per_person), 0.999)

    # --- HITUNG STATISTIK FIT MODEL ---
    log_likelihood = float(
        np.sum(X * np.log(P_val_clipped) + (1.0 - X) * np.log(1.0 - P_val_clipped))
    )
    aic = float(2 * num_params - 2 * log_likelihood)
    bic = float(num_params * np.log(max(n_persons * n_items, 1)) - 2 * log_likelihood)

    var_theta = np.var(theta)
    mean_sem2 = np.mean(sem_list**2)
    reliability = float(
        np.clip((var_theta - mean_sem2) / max(var_theta, 1e-5), 0.0, 0.99)
    )

    # DIBERSIHKAN: Hanya gunakan 1 kolom nama/kode soal
    df_item_params = pd.DataFrame(
        {
            "Kode Soal": [str(c) for c in item_cols],
            "a": np.round(a_params, 3),
            "b": np.round(b_params, 3),
            "c": np.round(c_params, 3),
            "Daya_Beda (a)": np.round(a_params, 3),
            "Tingkat_Kesukaran (b)": np.round(b_params, 3),
            "Tebakan_Pseudos (c)": np.round(c_params, 3),
            "Tingkat_Kesukaran": kategori_b,
        }
    )

    # Transformasi Skala Konversi Mengikuti min_scale dan max_scale dari UI Input
    t_min, t_max = np.min(theta), np.max(theta)
    if t_max != t_min:
        nilai_scaled = min_scale + ((theta - t_min) / (t_max - t_min)) * (max_scale - min_scale)
    else:
        nilai_scaled = np.full_like(theta, (min_scale + max_scale) / 2.0)

    df_person_params = pd.DataFrame(
        {
            "username": user_ids.values,
            "ID Peserta": user_ids.values,
            "skor_mentah": skor_mentah.astype(int),
            "Skor Mentah": skor_mentah.astype(int),
            "Kemampuan (Theta θ)": np.round(theta, 3),
            "theta": np.round(theta, 3),
            "Nilai_Scaled": np.round(nilai_scaled, 2),
            "Nilai Konversi": np.round(nilai_scaled, 2),
            "SEM": np.round(sem_list, 3),
        }
    )

    fit_stats = {
        "reliability": round(reliability, 4),
        "log_likelihood": round(log_likelihood, 2),
        "aic": round(aic, 2),
        "bic": round(bic, 2),
    }

    return {
        "item_params": df_item_params,
        "person_params": df_person_params,
        "df_person": df_person_params,
        "person_fit": df_person_params,
        "fit_stats": fit_stats,
        "model": model_type,
        "n_total": len(df_matrix),
        "n_sample": n_persons,
    }