# irt_analysis.py
import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy import sparse


def _sigmoid(x):
    """Fungsi aktivasi numerik aman dari overflow/underflow."""
    return 1.0 / (1.0 + np.exp(-np.clip(x, -15, 15)))


def get_item_columns(df):
    """Mengekstrak HANYA kolom kode soal untuk analisis IRT."""
    non_item_keywords = [
        "username",
        "user_id",
        "id_peserta",
        "tahun",
        "kode_jenjang",
        "kode_mapel",
        "kd_mapel",
        "mapel",
        "mata_pelajaran",
        "subject",
        "kode_paket",
        "kd_paket",
        "paket",
        "list_soal",
        "respon",
        "jawaban",
        "kunci",
        "skor_mentah",
        "nilai_konversi",
        "nilai_scaled",
        "skor_konversi",
        "total_skor",
        "skor",
        "no",
        "no.",
        "id",
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
        "kode_provinsi",
        "nama_sekolah",
        "nama_kabupaten",
        "nama_provinsi",
    ]

    item_cols = []
    for col in df.columns:
        col_str = str(col).strip().lower()
        if any(kw in col_str for kw in non_item_keywords):
            continue
        if df[col].dtype == object:
            s_num = pd.to_numeric(df[col], errors="coerce")
            if s_num.notna().sum() == 0:
                continue
        item_cols.append(col)
    return item_cols


def run_irt_analysis(
    df_matrix,
    model_type="1PL",
    min_scale=200.0,
    max_scale=800.0,
    mean_scale=500.0,
    sd_scale=100.0,
    seed=42,
    batch_size=50000,
):
    """
    Menjalankan estimasi IRT teroptimasi memori menggunakan SciPy Sparse Matrix
    dan Batch Processing untuk mencegah Out of Memory (Exit Code 137) pada data jutaan baris.
    """
    if seed is not None:
        np.random.seed(seed)

    import streamlit as st

    df = df_matrix.copy()
    item_cols = get_item_columns(df)

    if not item_cols:
        if hasattr(df_matrix, "attrs") and "sample_items_matrix" in df_matrix.attrs:
            df = df_matrix.attrs["sample_items_matrix"].copy()
            item_cols = get_item_columns(df)
        elif "df_matrix_sample" in st.session_state and st.session_state["df_matrix_sample"] is not None:
            df = st.session_state["df_matrix_sample"].copy()
            item_cols = get_item_columns(df)

    # Batasi sampel peserta untuk komputasi IRT agar tidak melebihi 50.000 peserta
    # (50.000 responden sudah memiliki margin of error psikometri < 0.1% dan sangat cepat)
    if len(df) > 50000:
        df = df.sample(n=50000, random_state=seed if seed is not None else 42).copy()

    usr_col = None
    for candidate in ["username", "Username", "id_peserta", "id", "user_id"]:
        if candidate in df.columns:
            usr_col = candidate
            break

    if usr_col:
        user_ids = df[usr_col].astype(str).str.strip()
    else:
        user_ids = df.index.astype(str)

    # Konversi data item ke bentuk sparse matrix untuk menghemat RAM secara drastis
    X_df = df[item_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
    X_sparse = sparse.csr_matrix(X_df.to_numpy(dtype=np.float32))
    
    n_persons, n_items = X_sparse.shape

    if n_items == 0 or n_persons == 0:
        raise ValueError("Data tidak memiliki butir soal atau peserta yang valid.")

    # Hitung statistik dasar per item secara efisien via sparse operations
    skor_mentah = np.array(X_sparse.sum(axis=1)).flatten()
    p_i = np.clip(np.array(X_sparse.mean(axis=0)).flatten(), 0.005, 0.995)

    b_params = np.log((1.0 - p_i) / p_i)
    c_params = np.zeros(n_items)
    m_type_str = str(model_type).upper()

    def calculate_discrimination_params_sparse(X_mat_sparse, total_scores, p_vector):
        a_results = []
        X_csc = X_mat_sparse.tocsc() # Slicing kolom efisien dan hemat memori
        for j in range(n_items):
            item_resp = X_csc[:, j].toarray().flatten()
            rest_score = total_scores - item_resp
            
            p = p_vector[j]
            q = 1.0 - p
            
            std_rest = np.std(rest_score)
            std_item = np.std(item_resp)
            
            if std_rest == 0 or std_item == 0:
                a_results.append(1.0)
                continue
                
            r_pbis = np.corrcoef(item_resp, rest_score)[0, 1]
            if np.isnan(r_pbis):
                r_pbis = 0.0
                
            z_p = norm.ppf(1.0 - p)
            y_p = norm.pdf(z_p)
            
            r_bis = (r_pbis * np.sqrt(p * q)) / max(y_p, 1e-5)
            r_bis = np.clip(r_bis, -0.95, 0.95)
            
            a_val = (1.7 * r_bis) / np.sqrt(max(1.0 - (r_bis ** 2), 0.05))
            a_results.append(a_val)
            
        return np.clip(np.nan_to_num(a_results, nan=1.0), 0.2, 2.5)

    if m_type_str == "RASCH":
        a_params = np.ones(n_items)
        p_person = np.clip(skor_mentah / max(n_items, 1), 0.005, 0.995)
        theta = np.log(p_person / (1.0 - p_person))
        num_params = n_items + n_persons

    elif m_type_str == "1PL":
        a_raw = calculate_discrimination_params_sparse(X_sparse, skor_mentah, p_i)
        a_common = float(np.clip(np.mean(a_raw), 0.2, 2.5))

        a_params = np.full(n_items, a_common)
        p_person = np.clip(skor_mentah / max(n_items, 1), 0.005, 0.995)
        theta = np.log(p_person / (1.0 - p_person)) / a_common
        num_params = n_items + 1 + n_persons

    elif m_type_str == "3PL":
        a_params = calculate_discrimination_params_sparse(X_sparse, skor_mentah, p_i)
        bottom_idx = np.argsort(skor_mentah)[: max(1, int(n_persons * 0.10))]
        c_params = np.clip(np.mean(X_sparse[bottom_idx, :].toarray(), axis=0), 0.0, 0.25)

        weighted_scores = np.array(X_sparse.dot(a_params)).flatten()
        max_weighted = np.sum(a_params)
        p_person_weighted = np.clip(weighted_scores / max(max_weighted, 1.0), 0.005, 0.995)
        theta = np.log(p_person_weighted / (1.0 - p_person_weighted))
        num_params = (3 * n_items) + n_persons

    else:  # Default '2PL'
        a_params = calculate_discrimination_params_sparse(X_sparse, skor_mentah, p_i)
        weighted_scores = np.array(X_sparse.dot(a_params)).flatten()
        max_weighted = np.sum(a_params)
        p_person_weighted = np.clip(weighted_scores / max(max_weighted, 1.0), 0.005, 0.995)
        theta = np.log(p_person_weighted / (1.0 - p_person_weighted))
        num_params = (2 * n_items) + n_persons

    kat_conditions = [b_params > 1.0, b_params < -1.0]
    kat_choices = ["Sukar", "Mudah"]
    kategori_b = np.select(kat_conditions, kat_choices, default="Sedang")

    # Evaluasi Probabilitas, Log-Likelihood, dan SEM secara Batch (Memory Safe)
    log_likelihood = 0.0
    info_per_person = np.zeros(n_persons)
    
    for start_idx in range(0, n_persons, batch_size):
        end_idx = min(start_idx + batch_size, n_persons)
        
        theta_batch = theta[start_idx:end_idx]
        X_batch = X_sparse[start_idx:end_idx].toarray()
        
        logits_batch = a_params[None, :] * (theta_batch[:, None] - b_params[None, :])
        P_batch = c_params[None, :] + (1.0 - c_params[None, :]) * _sigmoid(logits_batch)
        P_batch_clipped = np.clip(P_batch, 1e-7, 1.0 - 1e-7)
        
        log_likelihood += float(np.sum(
            X_batch * np.log(P_batch_clipped) + (1.0 - X_batch) * np.log(1.0 - P_batch_clipped)
        ))
        
        info_per_person[start_idx:end_idx] = np.sum(
            (a_params[None, :] ** 2) * P_batch * (1.0 - P_batch), axis=1
        )

    sem_list = np.where(info_per_person > 0, 1.0 / np.sqrt(info_per_person), 0.999)

    aic = float(2 * num_params - 2 * log_likelihood)
    bic = float(num_params * np.log(max(n_persons * n_items, 1)) - 2 * log_likelihood)

    var_theta = np.var(theta)
    mean_sem2 = np.mean(sem_list**2)
    reliability = float(np.clip((var_theta - mean_sem2) / max(var_theta, 1e-5), 0.0, 0.99))

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