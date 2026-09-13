import numpy as np
import pandas as pd


def get_item_columns(df):
    """Mengekstrak kolom kode soal dari DataFrame."""
    non_item_keywords = [
        'username',
        'tahun',
        'kode_jenjang',
        'kode_mapel',
        'kode_paket',
        'list_soal',
        'respon',
        'skor_mentah',
        'nilai_konversi',
        'no',
        'no.',
        'id',
        'nama',
        'sekolah',
        'npsn',
        'kelas',
        'unnamed',
        'jumlah_soal_dikerjakan',
        'jumlah_soal',
    ]

    item_cols = []
    for col in df.columns:
        col_str = str(col).strip().lower()
        if any(kw in col_str for kw in non_item_keywords):
            continue
        item_cols.append(col)

    return item_cols


def calculate_reliability_by_package(df_matrix, df_respon=None):
    """Hitung Cronbach's Alpha per kode paket, lalu kembalikan rata-ratanya."""
    target_df = df_matrix.copy()
    col_paket = None

    for col in target_df.columns:
        if str(col).lower() in ['kode_paket', 'kd_paket', 'paket']:
            col_paket = col
            break

    if col_paket is None and df_respon is not None:
        col_resp_paket = None
        for col in df_respon.columns:
            if str(col).lower() in ['kode_paket', 'kd_paket', 'paket']:
                col_resp_paket = col
                break
        
        if col_resp_paket:
            id_col_matrix = target_df.columns[0]
            id_col_respon = df_respon.columns[0]
            for c in ['username', 'id_peserta', 'id']:
                if c in df_respon.columns:
                    id_col_respon = c
                    break
            
            df_merged = target_df.merge(
                df_respon[[id_col_respon, col_resp_paket]],
                left_on=id_col_matrix,
                right_on=id_col_respon,
                how='left'
            )
            col_paket = col_resp_paket
            target_df = df_merged

    if not col_paket or col_paket not in target_df.columns:
        return None

    alphas = []
    for _, group in target_df.groupby(col_paket):
        pkg_item_cols = [c for c in get_item_columns(group) if group[c].notna().sum() > 0]
        
        if len(pkg_item_cols) > 1 and len(group) > 1:
            X_pkg = group[pkg_item_cols].to_numpy(dtype=np.float32)
            item_vars = np.nanvar(X_pkg, axis=0, ddof=1).sum()
            
            total_scores = np.nansum(X_pkg, axis=1)
            total_var = float(np.var(total_scores, ddof=1))
            
            n_k = len(pkg_item_cols)
            if total_var > 0 and item_vars < total_var:
                a = (n_k / (n_k - 1)) * (1.0 - (item_vars / total_var))
                if 0.0 <= a <= 1.0:
                    alphas.append(a)

    if alphas:
        return round(float(np.mean(alphas)), 3)

    return None


def calculate_distractor_analysis(df_respon=None, df_kunci=None, df_matrix=None):
    """Analisis distractor/pengecoh."""
    return pd.DataFrame(
        columns=['Kode_Soal', 'Opsi', 'Jumlah_Pemilih', 'Persentase']
    )


def calculate_ctt_metrics(X_mat, item_cols, total_scores):
    """Menghitung metrik CTT per butir soal dengan mengabaikan NaN (Soal tidak diujikan)."""
    _, K = X_mat.shape
    item_stats = []

    for i in range(K):
        item_name = str(item_cols[i])
        col_data = X_mat[:, i]

        # Hanya sertakan peserta yang MENERIMA/MENGERJAKAN soal ini (bukan NaN)
        valid_mask = ~np.isnan(col_data)
        N_i = np.sum(valid_mask)

        if N_i > 0:
            valid_item_scores = col_data[valid_mask]
            valid_total_scores = total_scores[valid_mask]

            # 1. Tingkat Kesukaran (p): Rasio Benar / Siswa yang mendapat soal
            p_val = float(np.mean(valid_item_scores))

            # 2. Daya Beda (Point-Biserial Correlation)
            std_item = np.std(valid_item_scores, ddof=1) if N_i > 1 else 0.0
            std_total = np.std(valid_total_scores, ddof=1) if N_i > 1 else 0.0

            if std_item > 0 and std_total > 0 and N_i > 1:
                cov_val = np.cov(valid_item_scores, valid_total_scores)[0, 1]
                r_val = float(cov_val / (std_item * std_total))
                r_val = 0.0 if np.isnan(r_val) else r_val
            else:
                r_val = 0.0
        else:
            p_val = 0.0
            r_val = 0.0
            N_i = 0

        # Pengkategorian Tingkat Kesukaran (p)
        if p_val < 0.30:
            kategori_p = 'Sukar'
        elif p_val <= 0.70:
            kategori_p = 'Sedang'
        else:
            kategori_p = 'Mudah'

        # Pengkategorian Daya Beda (r_pbi)
        if r_val >= 0.40:
            kategori_r = 'Sangat Baik'
        elif r_val >= 0.30:
            kategori_r = 'Baik'
        elif r_val >= 0.20:
            kategori_r = 'Cukup (Perlu Revisi)'
        else:
            kategori_r = 'Buruk (Dibuang/Revisi Total)'

        # Penentuan Status Rekomendasi
        if r_val >= 0.30:
            rekomendasi = 'Diterima Baik'
        elif r_val >= 0.20:
            rekomendasi = 'Direvisi'
        else:
            rekomendasi = 'Dibuang / Diganti'

        item_stats.append({
            'Kode_Soal': item_name,
            'Item': item_name,
            'N_Responden': int(N_i),
            'Tingkat_Kesukaran_p': round(p_val, 3),
            'Kategori_Kesukaran': kategori_p,
            'Daya_Beda_r': round(r_val, 3),
            'Kategori_Daya_Beda': kategori_r,
            'Rekomendasi': rekomendasi,
        })

    return pd.DataFrame(item_stats)


def run_ctt_analysis(df_matrix, df_respon=None, df_kunci=None):
    """Fungsi utama analisis CTT yang menangani missing value (NaN) dengan benar."""
    raw_item_cols = get_item_columns(df_matrix)
    
    # Hanya sertakan kolom soal yang memiliki setidaknya 1 respon aktif (bukan full NaN)
    item_cols = [c for c in raw_item_cols if df_matrix[c].notna().sum() > 0]
    
    n_items = len(item_cols)
    n_persons = len(df_matrix)

    if n_items == 0:
        return {
            'cronbach_alpha': 0.0,
            'item_stats': pd.DataFrame(),
            'distractor_stats': pd.DataFrame(),
            'summary': {'cronbach_alpha': 0.0, 'n_peserta': n_persons, 'n_soal': 0},
            'df_result': df_matrix,
        }

    # Matriks numerik (float32) yang mendukung np.nan
    X_mat = df_matrix[item_cols].to_numpy(dtype=np.float32)

    # Hitung skor mentah per siswa (mengabaikan NaN)
    skor_mentah = np.nansum(X_mat, axis=1)

    df_result = df_matrix.copy()
    df_result['Skor_Mentah'] = skor_mentah

    # Jumlah soal riil yang dikerjakan masing-masing siswa
    if 'Jumlah_Soal' in df_matrix.columns:
        jml_soal_user = df_matrix['Jumlah_Soal'].values
    else:
        jml_soal_user = np.sum(~np.isnan(X_mat), axis=1)

    # Nilai Konversi skala 0 - 100 berdasarkan jumlah soal masing-masing siswa
    df_result['Nilai_Konversi'] = np.where(
        jml_soal_user > 0,
        np.round((skor_mentah / jml_soal_user) * 100, 2),
        0.0,
    )

    konversi_scores = df_result['Nilai_Konversi']

    # Perhitungan Cronbach's Alpha yang aman dari hasil minus akibat sparse matrix
    cronbach_alpha = 0.0
    if n_items > 1 and n_persons > 1:
        # Varians butir hanya dari data valid (bukan NaN)
        item_variances = np.nanvar(X_mat, axis=0, ddof=1).sum()
        total_variance = float(np.var(skor_mentah, ddof=1))

        if total_variance > 0 and item_variances < total_variance:
            val_alpha = (n_items / (n_items - 1)) * (
                1.0 - (item_variances / total_variance)
            )
            cronbach_alpha = round(float(val_alpha), 3)
        else:
            # Apabila item_variances > total_variance akibat sifat multi-paket/sparse
            # Lakukan fallback hitung rata-rata Alpha per paket
            alpha_by_pkg = calculate_reliability_by_package(df_matrix, df_respon)
            cronbach_alpha = alpha_by_pkg if alpha_by_pkg is not None else 0.0

    # Hitung metrik CTT per butir
    df_item_stats = calculate_ctt_metrics(X_mat, item_cols, total_scores=skor_mentah)
    df_distractor = calculate_distractor_analysis(df_respon, df_kunci, df_result)

    mean_val = round(float(konversi_scores.mean()), 2) if len(konversi_scores) > 0 else 0.0
    std_val = round(float(konversi_scores.std()), 2) if len(konversi_scores) > 0 else 0.0
    max_val = round(float(konversi_scores.max()), 2) if len(konversi_scores) > 0 else 0.0
    min_val = round(float(konversi_scores.min()), 2) if len(konversi_scores) > 0 else 0.0
    med_val = round(float(konversi_scores.median()), 2) if len(konversi_scores) > 0 else 0.0

    summary_stats = {
        'cronbach_alpha': cronbach_alpha,
        'n_peserta': n_persons,
        'n_soal': n_items,
        'n_items': n_items,
        'mean_score': mean_val,
        'std_score': std_val,
        'max_score': max_val,
        'min_score': min_val,
        'median_score': med_val,
        'Jumlah_Peserta': n_persons,
        'Rata_Rata': mean_val,
        'Standar_Deviasi': std_val,
        'Nilai_Tertinggi': max_val,
        'Nilai_Terendah': min_val,
        'Median': med_val,
    }

    # Hapus duplikasi nama kolom jika ada
    df_result = df_result.loc[:, ~df_result.columns.duplicated()].copy()

    return {
        'cronbach_alpha': cronbach_alpha,
        'item_stats': df_item_stats,
        'distractor_stats': df_distractor,
        'summary': summary_stats,
        'df_result': df_result,
    }